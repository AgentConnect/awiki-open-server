from __future__ import annotations

from dataclasses import replace
import json
import os
import copy

import httpx
import pytest
from anp.proof import verify_group_receipt_proof

import awiki_open_server.messaging.groups.service as group_service
import awiki_open_server.messaging.groups.outbox as group_outbox
import awiki_open_server.shared.runtime as runtime
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.messaging.groups.identity import VerifiedHandleBinding
from awiki_open_server.messaging.groups.outbox import drain_group_outbox_once
from awiki_open_server.service_identity import (
    build_service_did_document,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
)
from awiki_open_server.shared.errors import InvalidParams
from tests.conftest import rpc
from tests.helpers import did_keypair_document, origin_proof, register_with_key, sign_did_document


def _group_envelope(
    *,
    method: str,
    sender_did: str,
    target_did: str,
    operation_id: str,
    body: dict,
    private_key,
    target_kind: str = "group",
) -> dict:
    meta = {
        "anp_version": "1.0",
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "target": {"kind": target_kind, "did": target_did},
        "operation_id": operation_id,
        "content_type": "application/json",
    }
    if method == "group.send":
        meta["message_id"] = f"msg-{operation_id}"
        meta["content_type"] = "text/plain"
    return {
        "meta": meta,
        "auth": {
            "scheme": "anp-rfc9421-origin-proof-v1",
            "origin_proof": origin_proof(meta, body, private_key, method=method),
        },
        "body": body,
    }


async def _group_rpc(
    client,
    *,
    method: str,
    sender_did: str,
    token: str,
    private_key,
    target_did: str,
    operation_id: str,
    body: dict,
    target_kind: str = "group",
):
    return await rpc(
        client,
        "/im/rpc",
        method,
        _group_envelope(
            method=method,
            sender_did=sender_did,
            target_did=target_did,
            operation_id=operation_id,
            body=body,
            private_key=private_key,
            target_kind=target_kind,
        ),
        token=token,
    )


def _assert_receipt(result: dict, *, method: str, state_version: str, event_seq: str) -> None:
    receipt = result["group_receipt"]
    assert receipt["subject_method"] == method
    assert receipt["group_did"] == result["group_did"]
    assert receipt["group_state_version"] == state_version
    assert receipt["group_event_seq"] == event_seq
    assert receipt["proof"]["verificationMethod"] == f"{result['group_did']}#key-1"
    assert receipt["proof"]["proofValue"].startswith("z")


@pytest.mark.asyncio
async def test_managed_group_lifecycle_permissions_versions_and_receipts(client):
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "host-owner")
    admin_did, admin_token, admin_key, _ = await register_with_key(client, "host-admin")
    member_did, member_token, member_key, _ = await register_with_key(client, "host-member")
    joiner_did, joiner_token, joiner_key, _ = await register_with_key(client, "host-joiner")

    policy = {
        "message_security_profile": "transport-protected",
        "bootstrap_security_profile": "transport-protected",
        "admission_mode": "admin-add",
        "permissions": {
            "send": "member",
            "add": "admin",
            "remove": "admin",
            "update_profile": "admin",
            "update_policy": "owner",
        },
        "attachments_allowed": False,
        "max_members": "100",
    }
    created = await _group_rpc(
        client,
        method="group.create",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did="did:wba:testserver",
        target_kind="service",
        operation_id="op-create-host-group",
        body={"group_profile": {"display_name": "Host Group"}, "group_policy": policy},
    )
    assert "error" not in created
    group = created["result"]
    group_did = group["group_did"]
    assert group_did.startswith("did:wba:testserver:groups:")
    assert group["creator_did"] == owner_did
    assert group["group_state_version"] == "1"
    assert group["group_event_seq"] == "1"
    _assert_receipt(group, method="group.create", state_version="1", event_seq="1")

    document_path = "/" + "/".join(group_did.split(":")[3:]) + "/did.json"
    group_document = (await client.get(document_path)).json()
    assert group_document["id"] == group_did
    assert group_document["service"][0]["serviceDid"] == "did:wba:testserver"
    assert verify_group_receipt_proof(group["group_receipt"], group_document) is True
    with client._transport.app.state.store.connect() as conn:
        key_reference = conn.execute(
            "SELECT key_reference FROM group_did_documents WHERE group_did = ?",
            (group_did,),
        ).fetchone()["key_reference"]
    assert os.stat(key_reference).st_mode & 0o777 == 0o600
    assert os.stat(os.path.dirname(key_reference)).st_mode & 0o777 == 0o700

    denied_join = await _group_rpc(
        client,
        method="group.join",
        sender_did=joiner_did,
        token=joiner_token,
        private_key=joiner_key,
        target_did=group_did,
        operation_id="op-join-policy-denied",
        body={},
    )
    assert denied_join["error"]["message"] == "group.policy_violation"

    added_admin = await _group_rpc(
        client,
        method="group.add",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-add-admin",
        body={"member_did": admin_did, "role": "admin"},
    )
    assert added_admin["result"]["membership_status"] == "active"
    assert added_admin["result"]["member_did"] == admin_did
    _assert_receipt(added_admin["result"], method="group.add", state_version="2", event_seq="2")
    replayed_admin = await _group_rpc(
        client,
        method="group.add",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-add-admin",
        body={"member_did": admin_did, "role": "admin"},
    )
    assert replayed_admin["result"]["idempotent_replay"] is True
    assert replayed_admin["result"]["group_receipt"] == added_admin["result"]["group_receipt"]
    conflicting_admin = await _group_rpc(
        client,
        method="group.add",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-add-admin",
        body={"member_did": admin_did, "role": "member"},
    )
    assert conflicting_admin["error"]["message"] == "group.operation_id_conflict"

    added_member = await _group_rpc(
        client,
        method="group.add",
        sender_did=admin_did,
        token=admin_token,
        private_key=admin_key,
        target_did=group_did,
        operation_id="op-add-member",
        body={"member_did": member_did},
    )
    assert added_member["result"]["membership_status"] == "active"
    _assert_receipt(added_member["result"], method="group.add", state_version="3", event_seq="3")

    updated_policy = await _group_rpc(
        client,
        method="group.update_policy",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-open-join",
        body={"group_policy_patch": {"admission_mode": "open-join"}},
    )
    assert updated_policy["result"]["group_policy"]["admission_mode"] == "open-join"
    _assert_receipt(updated_policy["result"], method="group.update_policy", state_version="4", event_seq="4")

    joined = await _group_rpc(
        client,
        method="group.join",
        sender_did=joiner_did,
        token=joiner_token,
        private_key=joiner_key,
        target_did=group_did,
        operation_id="op-join-open",
        body={},
    )
    assert joined["result"]["membership_status"] == "active"
    _assert_receipt(joined["result"], method="group.join", state_version="5", event_seq="5")

    sent = await _group_rpc(
        client,
        method="group.send",
        sender_did=joiner_did,
        token=joiner_token,
        private_key=joiner_key,
        target_did=group_did,
        operation_id="op-send-group-message",
        body={"text": "managed group message"},
    )
    assert sent["result"]["group_state_version"] == "5"
    assert sent["result"]["group_event_seq"] == "6"
    _assert_receipt(sent["result"], method="group.send", state_version="5", event_seq="6")

    thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "thread": {"kind": "group", "group_did": group_did},
            "after_server_seq": "0",
        },
        token=joiner_token,
    )
    assert [item["message_id"] for item in thread["result"]["messages"]] == [sent["result"]["message_id"]]
    assert thread["result"]["messages"][0]["group_event_seq"] == "6"
    assert thread["result"]["messages"][0]["group_receipt"] == sent["result"]["group_receipt"]

    read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "group", "group_did": group_did},
            "read_up_to_server_seq": "6",
            "read_up_to_message_id": sent["result"]["message_id"],
        },
        token=joiner_token,
    )
    assert read["result"]["read_watermark_server_seq"] == "6"
    assert read["result"]["updated_count"] == 1
    assert read["result"]["unread_count"] == 0

    updated_profile = await _group_rpc(
        client,
        method="group.update_profile",
        sender_did=admin_did,
        token=admin_token,
        private_key=admin_key,
        target_did=group_did,
        operation_id="op-update-profile",
        body={"group_profile_patch": {"description": "updated by admin"}},
    )
    assert updated_profile["result"]["group_profile"]["description"] == "updated by admin"
    _assert_receipt(updated_profile["result"], method="group.update_profile", state_version="6", event_seq="7")

    removed = await _group_rpc(
        client,
        method="group.remove",
        sender_did=admin_did,
        token=admin_token,
        private_key=admin_key,
        target_did=group_did,
        operation_id="op-remove-joiner",
        body={"member_did": joiner_did},
    )
    assert removed["result"]["membership_status"] == "removed"
    _assert_receipt(removed["result"], method="group.remove", state_version="7", event_seq="8")

    denied_send = await _group_rpc(
        client,
        method="group.send",
        sender_did=joiner_did,
        token=joiner_token,
        private_key=joiner_key,
        target_did=group_did,
        operation_id="op-send-after-remove",
        body={"text": "must be rejected"},
    )
    assert denied_send["error"]["message"] == "group.not_member"

    left = await _group_rpc(
        client,
        method="group.leave",
        sender_did=member_did,
        token=member_token,
        private_key=member_key,
        target_did=group_did,
        operation_id="op-member-leave",
        body={},
    )
    assert left["result"]["leaver_did"] == member_did
    _assert_receipt(left["result"], method="group.leave", state_version="8", event_seq="9")

    members = await rpc(
        client,
        "/im/rpc",
        "group.list_members",
        {"group_did": group_did},
        token=owner_token,
    )
    assert {item["agent_did"] for item in members["result"]["members"]} == {owner_did, admin_did}
    with client._transport.app.state.store.connect() as conn:
        tombstones = conn.execute(
            """
            SELECT agent_did, status FROM hosted_group_members
            WHERE group_did = ? AND status != 'active' ORDER BY agent_did
            """,
            (group_did,),
        ).fetchall()
    assert {row["agent_did"]: row["status"] for row in tombstones} == {
        joiner_did: "removed",
        member_did: "left",
    }


@pytest.mark.asyncio
async def test_managed_group_requires_origin_proof_and_rejects_nonstandard_join_credentials(client):
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "contract-owner")
    body = {
        "group_profile": {"display_name": "Contract Group"},
        "group_policy": {
            "message_security_profile": "transport-protected",
            "bootstrap_security_profile": "transport-protected",
            "admission_mode": "open-join",
            "permissions": {
                "send": "member",
                "add": "admin",
                "remove": "admin",
                "update_profile": "admin",
                "update_policy": "owner",
            },
            "max_members": "100",
        },
    }
    unsigned_meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": owner_did,
        "target": {"kind": "service", "did": "did:wba:testserver"},
        "operation_id": "op-unsigned-create",
    }
    unsigned = await rpc(
        client,
        "/im/rpc",
        "group.create",
        {"meta": unsigned_meta, "body": body},
        token=owner_token,
    )
    assert unsigned["error"]["message"] == "missing_origin_proof"

    oversized = await _group_rpc(
        client,
        method="group.create",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did="did:wba:testserver",
        target_kind="service",
        operation_id="op-oversized-group",
        body={
            **body,
            "group_policy": {**body["group_policy"], "max_members": "101"},
        },
    )
    assert oversized["error"]["message"] == "group.max_members_exceeded"

    for method in ("group.invite", "group.accept_invite"):
        response = await rpc(client, "/im/rpc", method, {}, token=owner_token)
        assert response["error"]["message"] == "method_not_found"

    for path in ("/group/rpc", "/user-service/group/rpc"):
        for method in ("refresh_join_code", "get_join_code"):
            response = await rpc(client, path, method, {"group_id": "ignored"}, token=owner_token)
            assert response["error"]["message"] == "group_join_code_not_supported"
        legacy_join = await rpc(client, path, "join", {"passcode": "012589"}, token=owner_token)
        assert legacy_join["error"]["message"] == "legacy_group_join_code_not_supported"


@pytest.mark.asyncio
async def test_group_get_info_enforces_discoverability_and_private_field_visibility(client):
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "privacy-owner")
    _, viewer_token, _, _ = await register_with_key(client, "privacy-viewer")
    policy = {
        "message_security_profile": "transport-protected",
        "bootstrap_security_profile": "transport-protected",
        "admission_mode": "open-join",
        "permissions": {
            "send": "member",
            "add": "admin",
            "remove": "admin",
            "update_profile": "admin",
            "update_policy": "owner",
        },
        "max_members": "100",
    }

    groups = {}
    for discoverability in ("private", "listed"):
        created = await _group_rpc(
            client,
            method="group.create",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did="did:wba:testserver",
            target_kind="service",
            operation_id=f"op-create-{discoverability}-group",
            body={
                "group_profile": {
                    "display_name": f"{discoverability.title()} Group",
                    "discoverability": discoverability,
                },
                "group_policy": policy,
            },
        )
        groups[discoverability] = created["result"]["group_did"]

    def anonymous_get(group_did: str, **body):
        return client.post(
            "/anp-im/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "group.get_info",
                "params": {
                    "meta": {
                        "anp_version": "1.0",
                        "profile": "anp.group.base.v1",
                        "security_profile": "transport-protected",
                        "target": {"kind": "group", "did": group_did},
                    },
                    "body": body,
                },
                "id": f"get-{discoverability}",
            },
        )

    private_response = await anonymous_get(groups["private"])
    assert private_response.json()["error"]["message"] == "group.policy_violation"

    listed_response = await anonymous_get(groups["listed"])
    listed_result = listed_response.json()["result"]
    assert listed_result["group_did"] == groups["listed"]
    assert listed_result["group_profile"]["discoverability"] == "listed"
    assert "group_policy" not in listed_result
    assert "member_list" not in listed_result

    listed_private_fields = await anonymous_get(
        groups["listed"],
        include_policy=True,
        include_member_list=True,
    )
    assert listed_private_fields.json()["error"]["message"] == "group.policy_violation"

    viewer_result = await rpc(
        client,
        "/im/rpc",
        "group.get_info",
        {"group_did": groups["listed"]},
        token=viewer_token,
    )
    assert "group_policy" not in viewer_result["result"]

    owner_result = await rpc(
        client,
        "/im/rpc",
        "group.get_info",
        {
            "group_did": groups["private"],
            "include_policy": True,
            "include_member_list": True,
        },
        token=owner_token,
    )
    assert owner_result["result"]["group_policy"]["admission_mode"] == "open-join"
    assert [item["agent_did"] for item in owner_result["result"]["member_list"]] == [owner_did]


@pytest.mark.asyncio
async def test_group_send_enforces_message_size_and_outbox_backpressure(client):
    app = client._transport.app
    app.state.settings = replace(
        app.state.settings,
        group_max_message_bytes=32,
        group_outbox_max_pending=1,
    )
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "capacity-owner")
    created = await _group_rpc(
        client,
        method="group.create",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did="did:wba:testserver",
        target_kind="service",
        operation_id="op-capacity-create",
        body={
            "group_profile": {"display_name": "Capacity Group"},
            "group_policy": {
                "message_security_profile": "transport-protected",
                "bootstrap_security_profile": "transport-protected",
                "admission_mode": "admin-add",
                "permissions": {
                    "send": "member",
                    "add": "admin",
                    "remove": "admin",
                    "update_profile": "admin",
                    "update_policy": "owner",
                },
                "max_members": "100",
            },
        },
    )
    group_did = created["result"]["group_did"]
    with app.state.store.connect() as conn:
        conn.execute(
            """
            INSERT INTO hosted_group_members(
              group_did, agent_did, home_service_did, role, status, joined_at
            ) VALUES (?, ?, ?, 'member', 'active', ?)
            """,
            (group_did, "did:wba:remote.test:users:member:e1_remote", "did:wba:remote.test", "2026-07-16T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO group_delivery_outbox(
              delivery_id, group_did, group_event_seq, target_did, target_service_did,
              method, envelope_json, status, next_attempt_at, created_at, updated_at
            ) VALUES ('gdlv-capacity', ?, 1, ?, 'did:wba:remote.test',
                      'group.state_changed', '{}', 'pending', ?, ?, ?)
            """,
            (
                group_did,
                "did:wba:remote.test:users:member:e1_remote",
                "2026-07-16T00:00:00Z",
                "2026-07-16T00:00:00Z",
                "2026-07-16T00:00:00Z",
            ),
        )

    backpressured = await _group_rpc(
        client,
        method="group.send",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-capacity-send",
        body={"text": "small"},
    )
    assert backpressured["error"]["message"] == "group.delivery_backlog_full"

    management = await _group_rpc(
        client,
        method="group.update_profile",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-capacity-management",
        body={"group_profile_patch": {"description": "management reserve remains available"}},
    )
    assert management["result"]["group_state_version"] == "2"

    oversized = await _group_rpc(
        client,
        method="group.send",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-capacity-oversized",
        body={"text": "x" * 64},
    )
    assert oversized["error"]["message"] == "group.message_too_large"
    with app.state.store.connect() as conn:
        group = conn.execute(
            "SELECT group_state_version, group_event_seq FROM hosted_groups WHERE group_did = ?",
            (group_did,),
        ).fetchone()
        messages = conn.execute(
            "SELECT COUNT(*) AS count FROM hosted_group_messages WHERE group_did = ?",
            (group_did,),
        ).fetchone()["count"]
    assert (group["group_state_version"], group["group_event_seq"], messages) == (2, 2, 0)


@pytest.mark.asyncio
async def test_handle_backed_member_rebind_revokes_the_previous_did(client, monkeypatch):
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "rebind-owner")
    previous_did, previous_token, previous_key, _ = await register_with_key(client, "rebind-old")
    new_did, new_token, new_key, _ = await register_with_key(client, "rebind-new")
    handle = "member.testserver"
    current = {"binding": VerifiedHandleBinding(handle, previous_did, "8")}
    monkeypatch.setattr(group_service, "resolve_handle_binding", lambda _: current["binding"])

    created = await _group_rpc(
        client,
        method="group.create",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did="did:wba:testserver",
        target_kind="service",
        operation_id="op-create-rebind-group",
        body={
            "group_profile": {"display_name": "Rebind Group"},
            "group_policy": {
                "message_security_profile": "transport-protected",
                "bootstrap_security_profile": "transport-protected",
                "admission_mode": "admin-add",
                "permissions": {
                    "send": "member",
                    "add": "admin",
                    "remove": "admin",
                    "update_profile": "admin",
                    "update_policy": "owner",
                },
                "max_members": "100",
            },
        },
    )
    group_did = created["result"]["group_did"]
    added = await _group_rpc(
        client,
        method="group.add",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did=group_did,
        operation_id="op-add-handle-member",
        body={"member_handle": handle},
    )
    assert added["result"]["member_did"] == previous_did
    assert added["result"]["member_handle"] == handle
    assert added["result"]["handle_binding_generation"] == "8"

    current["binding"] = VerifiedHandleBinding(handle, new_did, "9")
    rebound = await _group_rpc(
        client,
        method="group.rebind_member",
        sender_did=new_did,
        token=new_token,
        private_key=new_key,
        target_did=group_did,
        operation_id="op-rebind-handle-member",
        body={
            "member_handle": handle,
            "previous_member_did": previous_did,
            "new_member_did": new_did,
            "handle_binding_generation": "9",
        },
    )
    assert rebound["result"]["member_did"] == new_did
    assert rebound["result"]["previous_member_did"] == previous_did
    assert rebound["result"]["handle_binding_generation"] == "9"
    assert rebound["result"]["membership_status"] == "active"
    _assert_receipt(rebound["result"], method="group.rebind_member", state_version="3", event_seq="3")

    previous_send = await _group_rpc(
        client,
        method="group.send",
        sender_did=previous_did,
        token=previous_token,
        private_key=previous_key,
        target_did=group_did,
        operation_id="op-old-did-after-rebind",
        body={"text": "old DID must be denied"},
    )
    assert previous_send["error"]["message"] == "group.not_member"

    new_send = await _group_rpc(
        client,
        method="group.send",
        sender_did=new_did,
        token=new_token,
        private_key=new_key,
        target_did=group_did,
        operation_id="op-new-did-after-rebind",
        body={"text": "new DID is active"},
    )
    assert new_send["result"]["accepted"] is True
    assert new_send["result"]["group_state_version"] == "3"
    assert new_send["result"]["group_event_seq"] == "4"


@pytest.mark.asyncio
async def test_public_group_send_requires_peer_service_bound_to_sender_did(tmp_path, monkeypatch):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=False,
        )
    )
    remote_user_did = "did:wba:remote.example:users:member:e1_remote"
    remote_user_key, remote_user_document = did_keypair_document(remote_user_did)
    remote_user_document["service"][0]["serviceEndpoint"] = "https://awiki.info/anp-im/rpc"
    remote_user_document["service"][0]["serviceDid"] = "did:wba:remote.example"
    remote_service_key = generate_ed25519_private_key_pem()
    remote_service_document = build_service_did_document(
        "did:wba:remote.example",
        "https://awiki.info/anp-im/rpc",
        remote_service_key,
    )
    remote_identity = service_identity_from_settings(
        service_did="did:wba:remote.example",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=remote_service_key,
    )
    attacker_key = generate_ed25519_private_key_pem()
    attacker_document = build_service_did_document(
        "did:wba:attacker.example",
        "https://awiki.info/anp-im/rpc",
        attacker_key,
    )
    attacker_identity = service_identity_from_settings(
        service_did="did:wba:attacker.example",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=attacker_key,
    )
    assert remote_identity is not None
    assert attacker_identity is not None

    def fake_get_json(url: str):
        documents = {
            "https://remote.example/users/member/e1_remote/did.json": remote_user_document,
            "https://remote.example/.well-known/did.json": remote_service_document,
            "https://attacker.example/.well-known/did.json": attacker_document,
        }
        return documents[url]

    monkeypatch.setattr(runtime, "_http_get_json", fake_get_json)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as local_client:
        owner_did, owner_token, owner_key, _ = await register_with_key(local_client, "peer-owner")
        created = await _group_rpc(
            local_client,
            method="group.create",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did="did:wba:testserver",
            target_kind="service",
            operation_id="op-peer-group-create",
            body={
                "group_profile": {"display_name": "Peer Group"},
                "group_policy": {
                    "message_security_profile": "transport-protected",
                    "bootstrap_security_profile": "transport-protected",
                    "admission_mode": "admin-add",
                    "permissions": {
                        "send": "member",
                        "add": "admin",
                        "remove": "admin",
                        "update_profile": "admin",
                        "update_policy": "owner",
                    },
                    "max_members": "100",
                },
            },
        )
        group_did = created["result"]["group_did"]
        await _group_rpc(
            local_client,
            method="group.add",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did=group_did,
            operation_id="op-add-remote-member",
            body={"member_did": remote_user_did},
        )

        body = {"text": "public group message"}
        envelope = _group_envelope(
            method="group.send",
            sender_did=remote_user_did,
            target_did=group_did,
            operation_id="op-public-group-send",
            body=body,
            private_key=remote_user_key,
        )
        payload = {"jsonrpc": "2.0", "method": "group.send", "params": envelope, "id": "public-send"}
        raw_body = json.dumps(payload).encode()

        attacker_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:attacker.example"}
        attacker_headers.update(
            attacker_identity.sign_headers(
                "http://testserver/anp-im/rpc",
                "POST",
                attacker_headers,
                raw_body,
            )
        )
        attacker_response = await local_client.post("/anp-im/rpc", content=raw_body, headers=attacker_headers)
        assert attacker_response.json()["error"]["message"] == "source_service_did_caller_anchor_mismatch"

        peer_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:remote.example"}
        peer_headers.update(
            remote_identity.sign_headers(
                "http://testserver/anp-im/rpc",
                "POST",
                peer_headers,
                raw_body,
            )
        )
        accepted = await local_client.post("/anp-im/rpc", content=raw_body, headers=peer_headers)
        result = accepted.json()["result"]
        assert result["accepted"] is True
        assert result["sender_did"] == remote_user_did
        assert result["group_state_version"] == "2"
        assert result["group_event_seq"] == "3"
        assert result["group_receipt"]["proof"]["verificationMethod"] == f"{group_did}#key-1"
        with app.state.store.connect() as conn:
            outbox_rows = conn.execute(
                """
                SELECT method, envelope_json, status, attempt_count
                FROM group_delivery_outbox
                WHERE group_did = ? AND target_did = ?
                ORDER BY group_event_seq
                """,
                (group_did, remote_user_did),
            ).fetchall()
        assert [row["method"] for row in outbox_rows] == ["group.state_changed", "group.incoming"]
        for row in outbox_rows:
            envelope = json.loads(row["envelope_json"])
            assert "id" not in envelope
            assert row["status"] == "pending"
            assert row["attempt_count"] == 0
            serialized = json.dumps(envelope)
            assert "delivery_id" not in serialized
            assert '"attempt"' not in serialized
            assert '"trace"' not in serialized

        app.state.group_outbox_lock.acquire()
        try:
            overlapping = drain_group_outbox_once(app)
        finally:
            app.state.group_outbox_lock.release()
        assert overlapping == {"selected": 0, "delivered": 0, "retried": 0, "dead": 0}

        monkeypatch.setattr(
            runtime,
            "_http_post_json",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("temporary peer outage")),
        )
        first_drain = drain_group_outbox_once(app)
        assert first_drain == {"selected": 1, "delivered": 0, "retried": 1, "dead": 0}
        with app.state.store.connect() as conn:
            retry_rows = conn.execute(
                """
                SELECT status, attempt_count, last_error FROM group_delivery_outbox
                WHERE group_did = ? ORDER BY group_event_seq
                """,
                (group_did,),
            ).fetchall()
            conn.execute(
                "UPDATE group_delivery_outbox SET next_attempt_at = '2000-01-01T00:00:00+00:00' WHERE group_did = ?",
                (group_did,),
            )
        assert [(row["status"], row["attempt_count"]) for row in retry_rows] == [
            ("retry", 1),
            ("pending", 0),
        ]
        assert "temporary peer outage" in retry_rows[0]["last_error"]
        assert retry_rows[1]["last_error"] is None

        deliveries = []

        def accept_delivery(url, payload, *, headers=None, body_bytes=None):
            deliveries.append((url, payload, headers, body_bytes))
            return {}

        monkeypatch.setattr(runtime, "_http_post_json", accept_delivery)
        restarted_app = create_app(app.state.settings)
        second_drain = drain_group_outbox_once(restarted_app)
        assert second_drain == {"selected": 1, "delivered": 1, "retried": 0, "dead": 0}
        third_drain = drain_group_outbox_once(restarted_app)
        assert third_drain == {"selected": 1, "delivered": 1, "retried": 0, "dead": 0}
        assert [payload["method"] for _, payload, _, _ in deliveries] == [
            "group.state_changed",
            "group.incoming",
        ]
        assert all("id" not in payload for _, payload, _, _ in deliveries)
        assert all(headers.get("Signature") for _, _, headers, _ in deliveries)
        with restarted_app.state.store.connect() as conn:
            delivered_rows = conn.execute(
                "SELECT status, attempt_count, last_error FROM group_delivery_outbox WHERE group_did = ?",
                (group_did,),
            ).fetchall()
        assert {(row["status"], row["attempt_count"], row["last_error"]) for row in delivered_rows} == {
            ("delivered", 2, None),
            ("delivered", 1, None),
        }


@pytest.mark.asyncio
async def test_two_server_notifications_build_remote_member_projection(tmp_path, monkeypatch):
    host_key = generate_ed25519_private_key_pem()
    home_key = generate_ed25519_private_key_pem()
    host_app = create_app(
        Settings(
            data_dir=tmp_path / "host",
            public_base_url="http://127.0.0.1:18081",
            service_did="did:wba:host.test",
            did_domain="host.test",
            service_private_key_pem=host_key,
            allow_unsigned_peer_dev=False,
            did_resolver_base_urls={"home.test": "http://127.0.0.1:18082"},
        )
    )
    home_app = create_app(
        Settings(
            data_dir=tmp_path / "home",
            public_base_url="http://127.0.0.1:18082",
            service_did="did:wba:home.test",
            did_domain="home.test",
            service_private_key_pem=home_key,
            allow_unsigned_peer_dev=False,
            did_resolver_base_urls={"host.test": "http://127.0.0.1:18081"},
        )
    )
    owner_did = "did:wba:host.test:users:owner:e1_owner"
    owner_key, owner_document = did_keypair_document(owner_did)
    owner_document["service"][0].update(
        {"serviceEndpoint": "http://127.0.0.1:18081/anp-im/rpc", "serviceDid": "did:wba:host.test"}
    )
    owner_document = sign_did_document(owner_document, owner_key)
    member_did = "did:wba:home.test:users:member:e1_member"
    member_key, member_document = did_keypair_document(member_did)
    member_document["service"][0].update(
        {"serviceEndpoint": "http://127.0.0.1:18082/anp-im/rpc", "serviceDid": "did:wba:home.test"}
    )
    member_document = sign_did_document(member_document, member_key)
    host_service_document = host_app.state.service_identity.did_document
    home_service_document = home_app.state.service_identity.did_document
    documents = {
        "http://127.0.0.1:18081/users/owner/e1_owner/did.json": owner_document,
        "http://127.0.0.1:18081/.well-known/did.json": host_service_document,
        "http://127.0.0.1:18082/users/member/e1_member/did.json": member_document,
        "http://127.0.0.1:18082/.well-known/did.json": home_service_document,
    }

    def fake_get_json(url: str, **_kwargs):
        return documents[url]

    monkeypatch.setattr(runtime, "_http_get_json", fake_get_json)
    host_transport = httpx.ASGITransport(app=host_app)
    home_transport = httpx.ASGITransport(app=home_app)
    async with (
        httpx.AsyncClient(transport=host_transport, base_url="http://127.0.0.1:18081") as host_client,
        httpx.AsyncClient(transport=home_transport, base_url="http://127.0.0.1:18082") as home_client,
    ):
        owner_registration = await rpc(
            host_client,
            "/did-auth/rpc",
            "register",
            {"handle": "owner", "did_document": owner_document},
        )
        owner_token = owner_registration["result"]["token"]
        member_registration = await rpc(
            home_client,
            "/did-auth/rpc",
            "register",
            {"handle": "member", "did_document": member_document},
        )
        member_token = member_registration["result"]["token"]
        created = await _group_rpc(
            host_client,
            method="group.create",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did="did:wba:host.test",
            target_kind="service",
            operation_id="op-two-server-create",
            body={
                "group_profile": {"display_name": "Two Server Group"},
                "group_policy": {
                    "message_security_profile": "transport-protected",
                    "bootstrap_security_profile": "transport-protected",
                    "admission_mode": "admin-add",
                    "permissions": {
                        "send": "member",
                        "add": "admin",
                        "remove": "admin",
                        "update_profile": "admin",
                        "update_policy": "owner",
                    },
                    "max_members": "100",
                },
            },
        )
        group_did = created["result"]["group_did"]
        with host_app.state.store.connect() as conn:
            group_document = json.loads(
                conn.execute(
                    "SELECT document_json FROM group_did_documents WHERE group_did = ?",
                    (group_did,),
                ).fetchone()["document_json"]
            )
        group_path = "/".join(group_did.split(":")[3:])
        documents[f"http://127.0.0.1:18081/{group_path}/did.json"] = group_document

        await _group_rpc(
            host_client,
            method="group.add",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did=group_did,
            operation_id="op-two-server-add",
            body={"member_did": member_did},
        )
        sent = await _group_rpc(
            host_client,
            method="group.send",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did=group_did,
            operation_id="op-two-server-send",
            body={"text": "cross-domain projection"},
        )
        with host_app.state.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT envelope_json FROM group_delivery_outbox
                WHERE group_did = ? AND target_did = ? ORDER BY group_event_seq
                """,
                (group_did, member_did),
            ).fetchall()
        assert len(rows) == 2

        for row in rows:
            envelope = json.loads(row["envelope_json"])
            tampered = copy.deepcopy(envelope)
            if envelope["method"] == "group.state_changed":
                tampered["params"]["body"]["group_receipt"]["proof"]["proofValue"] = "zInvalid"
                expected_error = "group.invalid_group_receipt"
            else:
                tampered["params"]["auth"]["origin_proof"]["signature"] = "sig1=:AAAA:"
                expected_error = "invalid_origin_proof_signature"
            tampered_raw = json.dumps(tampered, ensure_ascii=False, separators=(",", ":")).encode()
            tampered_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:host.test"}
            tampered_headers.update(
                host_app.state.service_identity.sign_headers(
                    "http://127.0.0.1:18082/anp-im/rpc",
                    "POST",
                    tampered_headers,
                    tampered_raw,
                )
            )
            tampered_response = await home_client.post(
                "/anp-im/rpc",
                content=tampered_raw,
                headers=tampered_headers,
            )
            assert tampered_response.json()["error"]["message"] == expected_error

            raw_body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
            headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:host.test"}
            headers.update(
                host_app.state.service_identity.sign_headers(
                    "http://127.0.0.1:18082/anp-im/rpc",
                    "POST",
                    headers,
                    raw_body,
                )
            )
            response = await home_client.post("/anp-im/rpc", content=raw_body, headers=headers)
            assert response.status_code == 204
            duplicate = await home_client.post("/anp-im/rpc", content=raw_body, headers=headers)
            assert duplicate.status_code == 204

            request_shaped = {**envelope, "id": "notifications-must-not-have-id"}
            request_raw = json.dumps(request_shaped, ensure_ascii=False, separators=(",", ":")).encode()
            request_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:host.test"}
            request_headers.update(
                host_app.state.service_identity.sign_headers(
                    "http://127.0.0.1:18082/anp-im/rpc",
                    "POST",
                    request_headers,
                    request_raw,
                )
            )
            request_response = await home_client.post(
                "/anp-im/rpc",
                content=request_raw,
                headers=request_headers,
            )
            assert request_response.json()["error"]["message"] == "group.notification_must_not_have_id"

        projected = await rpc(home_client, "/im/rpc", "group.get", {"group_did": group_did}, token=member_token)
        assert projected["result"]["group_profile"]["display_name"] == "Two Server Group"
        assert projected["result"]["group_state_version"] == "2"
        assert projected["result"]["group_event_seq"] == "3"
        projected_messages = await rpc(
            home_client,
            "/im/rpc",
            "group.list_messages",
            {"group_did": group_did},
            token=member_token,
        )
        assert projected_messages["result"]["source"] == "remote_projection"
        assert projected_messages["result"]["messages"][0]["message_id"] == sent["result"]["message_id"]
        assert projected_messages["result"]["messages"][0]["content"] == "cross-domain projection"

        host_snapshot = await rpc(
            host_client,
            "/im/rpc",
            "group.get_info",
            {"group_did": group_did, "include_policy": True, "include_member_list": True},
            token=owner_token,
        )
        host_snapshot["result"].pop("host_service_did", None)
        host_snapshot["result"].pop("group_event_seq", None)
        refresh_requests = []

        def refresh_from_host(url, payload, *, headers=None, body_bytes=None):
            refresh_requests.append((url, payload, headers, body_bytes))
            return host_snapshot

        monkeypatch.setattr(runtime, "_http_post_json", refresh_from_host)
        projected_members = await rpc(
            home_client,
            "/im/rpc",
            "group.list_members",
            {"group_did": group_did},
            token=member_token,
        )
        assert projected_members["result"]["source"] == "remote_projection"
        assert projected_members["result"]["projection_refresh"] == {"status": "refreshed"}
        assert {item["member_did"] for item in projected_members["result"]["members"]} == {
            owner_did,
            member_did,
        }
        refresh_url, refresh_payload, refresh_headers, refresh_body = refresh_requests[0]
        assert refresh_url == "http://127.0.0.1:18081/anp-im/rpc"
        assert refresh_payload["method"] == "group.get_info"
        assert refresh_payload["params"]["meta"]["profile"] == "anp.group.base.v1"
        assert refresh_payload["params"]["meta"]["sender_did"] == member_did
        assert refresh_payload["params"]["meta"]["target"] == {"kind": "group", "did": group_did}
        assert refresh_payload["params"]["body"] == {
            "include_policy": True,
            "include_member_list": True,
        }
        assert "auth" not in refresh_payload["params"]
        assert "client" not in refresh_payload["params"]
        assert "server" not in refresh_payload["params"]
        assert refresh_headers["Signature"]
        assert refresh_headers["Content-Digest"]
        assert refresh_body == json.dumps(
            refresh_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

        member_body = {"text": "member to remote host"}
        member_envelope = _group_envelope(
            method="group.send",
            sender_did=member_did,
            target_did=group_did,
            operation_id="op-home-to-host-send",
            body=member_body,
            private_key=member_key,
        )
        host_payload = {
            "jsonrpc": "2.0",
            "method": "group.send",
            "params": member_envelope,
            "id": "op-home-to-host-send",
        }
        host_raw = json.dumps(host_payload, ensure_ascii=False, separators=(",", ":")).encode()
        home_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:home.test"}
        home_headers.update(
            home_app.state.service_identity.sign_headers(
                "http://127.0.0.1:18081/anp-im/rpc",
                "POST",
                home_headers,
                host_raw,
            )
        )
        host_response = await host_client.post("/anp-im/rpc", content=host_raw, headers=home_headers)
        assert host_response.json()["result"]["accepted"] is True

        forwarded_payloads = []

        def forward_to_host(url, payload, *, headers=None, body_bytes=None):
            forwarded_payloads.append((url, payload, headers, body_bytes))
            return host_response.json()

        monkeypatch.setattr(runtime, "_http_post_json", forward_to_host)
        routed = await rpc(
            home_client,
            "/im/rpc",
            "group.send",
            member_envelope,
            token=member_token,
        )
        assert routed["result"]["message_id"] == host_response.json()["result"]["message_id"]
        assert forwarded_payloads[0][0] == "http://127.0.0.1:18081/anp-im/rpc"
        assert forwarded_payloads[0][1]["method"] == "group.send"
        assert forwarded_payloads[0][1]["params"] == member_envelope
        assert "relay" not in json.dumps(forwarded_payloads[0][1])

        forged_response = copy.deepcopy(host_response.json())
        forged_response["result"]["group_receipt"]["proof"]["proofValue"] = "zInvalid"
        monkeypatch.setattr(runtime, "_http_post_json", lambda *_args, **_kwargs: forged_response)
        forged = await rpc(
            home_client,
            "/im/rpc",
            "group.send",
            member_envelope,
            token=member_token,
        )
        assert forged["error"]["message"] == "group.invalid_group_receipt"

        monkeypatch.setattr(
            runtime,
            "_http_post_json",
            lambda *_args, **_kwargs: {
                "jsonrpc": "2.0",
                "id": "op-home-to-host-send",
                "error": {
                    "code": 3000,
                    "message": "actor is not active in the target group",
                    "data": {"anp_code": "group.not_member"},
                },
            },
        )
        rejected = await rpc(
            home_client,
            "/im/rpc",
            "group.send",
            member_envelope,
            token=member_token,
        )
        assert rejected["error"]["message"] == "group.not_member"
        assert rejected["error"]["data"] == {
            "remote_code": 3000,
            "anp_code": "group.not_member",
        }


@pytest.mark.asyncio
async def test_two_server_open_join_routes_original_request_and_bootstraps_projection(tmp_path, monkeypatch):
    host_app = create_app(
        Settings(
            data_dir=tmp_path / "join-host",
            public_base_url="http://127.0.0.1:18181",
            service_did="did:wba:join-host.test",
            did_domain="join-host.test",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            did_resolver_base_urls={"join-home.test": "http://127.0.0.1:18182"},
        )
    )
    home_app = create_app(
        Settings(
            data_dir=tmp_path / "join-home",
            public_base_url="http://127.0.0.1:18182",
            service_did="did:wba:join-home.test",
            did_domain="join-home.test",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            did_resolver_base_urls={"join-host.test": "http://127.0.0.1:18181"},
        )
    )
    owner_did = "did:wba:join-host.test:users:owner:e1_owner"
    owner_key, owner_document = did_keypair_document(owner_did)
    owner_document["service"][0].update(
        {
            "serviceEndpoint": "http://127.0.0.1:18181/anp-im/rpc",
            "serviceDid": "did:wba:join-host.test",
        }
    )
    owner_document = sign_did_document(owner_document, owner_key)
    joiner_did = "did:wba:join-home.test:users:joiner:e1_joiner"
    joiner_key, joiner_document = did_keypair_document(joiner_did)
    joiner_document["service"][0].update(
        {
            "serviceEndpoint": "http://127.0.0.1:18182/anp-im/rpc",
            "serviceDid": "did:wba:join-home.test",
        }
    )
    joiner_document = sign_did_document(joiner_document, joiner_key)
    documents = {
        "http://127.0.0.1:18181/users/owner/e1_owner/did.json": owner_document,
        "http://127.0.0.1:18181/.well-known/did.json": host_app.state.service_identity.did_document,
        "http://127.0.0.1:18182/users/joiner/e1_joiner/did.json": joiner_document,
        "http://127.0.0.1:18182/.well-known/did.json": home_app.state.service_identity.did_document,
    }
    monkeypatch.setattr(runtime, "_http_get_json", lambda url, **_kwargs: documents[url])

    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=host_app), base_url="http://127.0.0.1:18181") as host_client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=home_app), base_url="http://127.0.0.1:18182") as home_client,
    ):
        owner_registration = await rpc(
            host_client,
            "/did-auth/rpc",
            "register",
            {"handle": "owner", "did_document": owner_document},
        )
        joiner_registration = await rpc(
            home_client,
            "/did-auth/rpc",
            "register",
            {"handle": "joiner", "did_document": joiner_document},
        )
        created = await _group_rpc(
            host_client,
            method="group.create",
            sender_did=owner_did,
            token=owner_registration["result"]["token"],
            private_key=owner_key,
            target_did="did:wba:join-host.test",
            target_kind="service",
            operation_id="op-cross-domain-open-create",
            body={
                "group_profile": {"display_name": "Cross-domain Open Group"},
                "group_policy": {
                    "message_security_profile": "transport-protected",
                    "bootstrap_security_profile": "transport-protected",
                    "admission_mode": "open-join",
                    "permissions": {
                        "send": "member",
                        "add": "admin",
                        "remove": "admin",
                        "update_profile": "admin",
                        "update_policy": "owner",
                    },
                    "max_members": "100",
                },
            },
        )
        group_did = created["result"]["group_did"]
        with host_app.state.store.connect() as conn:
            group_document = json.loads(
                conn.execute(
                    "SELECT document_json FROM group_did_documents WHERE group_did = ?",
                    (group_did,),
                ).fetchone()["document_json"]
            )
        group_path = "/".join(group_did.split(":")[3:])
        documents[f"http://127.0.0.1:18181/{group_path}/did.json"] = group_document

        join_envelope = _group_envelope(
            method="group.join",
            sender_did=joiner_did,
            target_did=group_did,
            operation_id="op-cross-domain-open-join",
            body={},
            private_key=joiner_key,
        )
        host_payload = {
            "jsonrpc": "2.0",
            "method": "group.join",
            "params": join_envelope,
            "id": "op-cross-domain-open-join",
        }
        host_raw = json.dumps(host_payload, ensure_ascii=False, separators=(",", ":")).encode()
        home_headers = {
            "Content-Type": "application/json",
            "x-anp-source-service-did": "did:wba:join-home.test",
        }
        home_headers.update(
            home_app.state.service_identity.sign_headers(
                "http://127.0.0.1:18181/anp-im/rpc",
                "POST",
                home_headers,
                host_raw,
            )
        )
        host_response = await host_client.post("/anp-im/rpc", content=host_raw, headers=home_headers)
        host_result = host_response.json()["result"]
        assert host_result["membership_status"] == "active"
        assert host_result["member_did"] == joiner_did
        assert host_result["group_receipt"]["subject_method"] == "group.join"
        assert "token" not in json.dumps(host_response.json()).lower()
        assert "join_code" not in json.dumps(host_response.json()).lower()

        forwarded = []

        def route_to_host(url, payload, *, headers=None, body_bytes=None):
            forwarded.append((url, payload, headers, body_bytes))
            return host_response.json()

        monkeypatch.setattr(runtime, "_http_post_json", route_to_host)
        routed = await rpc(
            home_client,
            "/im/rpc",
            "group.join",
            join_envelope,
            token=joiner_registration["result"]["token"],
        )
        assert routed["result"]["membership_status"] == "active"
        assert forwarded[0][0] == "http://127.0.0.1:18181/anp-im/rpc"
        assert forwarded[0][1]["method"] == "group.join"
        assert forwarded[0][1]["params"] == join_envelope
        assert forwarded[0][2]["Signature"]

        with host_app.state.store.connect() as conn:
            delivery = conn.execute(
                """
                SELECT envelope_json FROM group_delivery_outbox
                WHERE group_did = ? AND target_did = ? AND method = 'group.state_changed'
                """,
                (group_did, joiner_did),
            ).fetchone()
        notification = json.loads(delivery["envelope_json"])
        notification_raw = json.dumps(notification, ensure_ascii=False, separators=(",", ":")).encode()
        host_headers = {
            "Content-Type": "application/json",
            "x-anp-source-service-did": "did:wba:join-host.test",
        }
        host_headers.update(
            host_app.state.service_identity.sign_headers(
                "http://127.0.0.1:18182/anp-im/rpc",
                "POST",
                host_headers,
                notification_raw,
            )
        )
        projected = await home_client.post("/anp-im/rpc", content=notification_raw, headers=host_headers)
        assert projected.status_code == 204
        duplicate = await home_client.post("/anp-im/rpc", content=notification_raw, headers=host_headers)
        assert duplicate.status_code == 204
        local_view = await rpc(
            home_client,
            "/im/rpc",
            "group.get",
            {"group_did": group_did},
            token=joiner_registration["result"]["token"],
        )
        assert local_view["result"]["membership_status"] == "active"
        assert local_view["result"]["group_state_version"] == "2"
        assert local_view["result"]["group_event_seq"] == "2"


@pytest.mark.asyncio
async def test_three_domain_fanout_isolates_offline_target_and_recovers_in_fifo_after_restart(client, monkeypatch):
    app = client._transport.app
    owner_did, owner_token, owner_key, _ = await register_with_key(client, "fanout-owner")
    remote_b = "did:wba:fanout-b.test:users:member:e1_b"
    remote_c = "did:wba:fanout-c.test:users:member:e1_c"
    home_services = {
        remote_b: "did:wba:fanout-b.test",
        remote_c: "did:wba:fanout-c.test",
    }
    monkeypatch.setattr(group_service, "_home_service_did", lambda _request, did: home_services[did])

    created = await _group_rpc(
        client,
        method="group.create",
        sender_did=owner_did,
        token=owner_token,
        private_key=owner_key,
        target_did="did:wba:testserver",
        target_kind="service",
        operation_id="op-three-domain-create",
        body={
            "group_profile": {"display_name": "Three Domain Fanout"},
            "group_policy": {
                "message_security_profile": "transport-protected",
                "bootstrap_security_profile": "transport-protected",
                "admission_mode": "admin-add",
                "permissions": {
                    "send": "member",
                    "add": "admin",
                    "remove": "admin",
                    "update_profile": "admin",
                    "update_policy": "owner",
                },
                "max_members": "100",
            },
        },
    )
    group_did = created["result"]["group_did"]
    for suffix, member_did in (("b", remote_b), ("c", remote_c)):
        added = await _group_rpc(
            client,
            method="group.add",
            sender_did=owner_did,
            token=owner_token,
            private_key=owner_key,
            target_did=group_did,
            operation_id=f"op-three-domain-add-{suffix}",
            body={"member_did": member_did},
        )
        assert added["result"]["membership_status"] == "active"

    send_envelope = _group_envelope(
        method="group.send",
        sender_did=owner_did,
        target_did=group_did,
        operation_id="op-three-domain-send",
        body={"text": "fanout message"},
        private_key=owner_key,
    )
    sent = await rpc(client, "/im/rpc", "group.send", send_envelope, token=owner_token)
    assert sent["result"]["group_event_seq"] == "4"
    replay = await rpc(client, "/im/rpc", "group.send", send_envelope, token=owner_token)
    assert replay["result"]["idempotent_replay"] is True

    with app.state.store.connect() as conn:
        rows = conn.execute(
            """
            SELECT target_did, group_event_seq, method, envelope_json, status
            FROM group_delivery_outbox WHERE group_did = ?
            ORDER BY target_did, group_event_seq
            """,
            (group_did,),
        ).fetchall()
    assert [(row["target_did"], row["group_event_seq"], row["method"]) for row in rows] == [
        (remote_b, 2, "group.state_changed"),
        (remote_b, 3, "group.state_changed"),
        (remote_b, 4, "group.incoming"),
        (remote_c, 3, "group.state_changed"),
        (remote_c, 4, "group.incoming"),
    ]
    incoming = [json.loads(row["envelope_json"]) for row in rows if row["method"] == "group.incoming"]
    assert {item["params"]["meta"]["message_id"] for item in incoming} == {sent["result"]["message_id"]}
    assert {
        item["params"]["body"]["group_receipt"]["proof"]["proofValue"] for item in incoming
    } == {sent["result"]["group_receipt"]["proof"]["proofValue"]}

    delivered = []

    def deliver_with_b_offline(_app, row):
        if row["target_did"] == remote_b:
            raise OSError("fanout-b offline")
        delivered.append((row["target_did"], row["group_event_seq"], row["method"]))

    monkeypatch.setattr(group_outbox, "_deliver", deliver_with_b_offline)
    first = drain_group_outbox_once(app)
    assert first == {"selected": 2, "delivered": 1, "retried": 1, "dead": 0}
    second = drain_group_outbox_once(app)
    assert second == {"selected": 1, "delivered": 1, "retried": 0, "dead": 0}
    assert delivered == [
        (remote_c, 3, "group.state_changed"),
        (remote_c, 4, "group.incoming"),
    ]

    with app.state.store.connect() as conn:
        conn.execute(
            """
            UPDATE group_delivery_outbox SET next_attempt_at = '2000-01-01T00:00:00+00:00'
            WHERE group_did = ? AND target_did = ? AND status = 'retry'
            """,
            (group_did, remote_b),
        )
    recovered = []
    monkeypatch.setattr(
        group_outbox,
        "_deliver",
        lambda _app, row: recovered.append((row["target_did"], row["group_event_seq"], row["method"])),
    )
    restarted_app = create_app(app.state.settings)
    for expected_seq in (2, 3, 4):
        result = drain_group_outbox_once(restarted_app)
        assert result == {"selected": 1, "delivered": 1, "retried": 0, "dead": 0}
        assert recovered[-1][1] == expected_seq
    assert recovered == [
        (remote_b, 2, "group.state_changed"),
        (remote_b, 3, "group.state_changed"),
        (remote_b, 4, "group.incoming"),
    ]
    with restarted_app.state.store.connect() as conn:
        final_rows = conn.execute(
            "SELECT status FROM group_delivery_outbox WHERE group_did = ?",
            (group_did,),
        ).fetchall()
    assert {row["status"] for row in final_rows} == {"delivered"}


def test_public_outbound_url_validation_rejects_private_and_credentialed_targets(monkeypatch):
    monkeypatch.setattr(
        runtime.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(runtime.socket.AF_INET, runtime.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(InvalidParams, match="outbound_url_private_address_not_allowed"):
        runtime._validate_outbound_url("https://resolver.example/did.json")
    with pytest.raises(InvalidParams, match="outbound_url_scheme_not_allowed"):
        runtime._validate_outbound_url("http://resolver.example/did.json")
    with pytest.raises(InvalidParams, match="outbound_url_userinfo_not_allowed"):
        runtime._validate_outbound_url("https://user:password@resolver.example/did.json")
    runtime._validate_outbound_url("http://127.0.0.1:8765/did.json", allow_private=True)
