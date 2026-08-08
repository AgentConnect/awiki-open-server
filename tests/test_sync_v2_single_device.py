from __future__ import annotations

import pytest

from tests.conftest import rpc
from tests.helpers import did_keypair_document, origin_proof, register, sign_did_document


async def _register_single_device(client, handle: str, *, device_id: str = "device-primary"):
    did = f"did:wba:testserver:user:{handle}:e1_device"
    private_key, document = did_keypair_document(did)
    document["service"][0].update(
        {"serviceEndpoint": "http://testserver/anp-im/rpc", "serviceDid": "did:wba:testserver"}
    )
    document["deviceManifest"] = {
        "devices": [
            {
                "device_id": device_id,
                "signing_key_id": f"{did}#key-1",
            }
        ]
    }
    document = sign_did_document(document, private_key)
    response = await rpc(
        client,
        "/user-service/v1/did-auth/rpc",
        "register",
        {"handle": handle, "did_document": document},
    )
    return did, response["result"]["access_token"], response["result"]["user_id"], private_key


def _v2_params(did: str, operation_id: str, body: dict) -> dict:
    return {
        "meta": {
            "profile": "anp.sync.local.v2",
            "security_profile": "transport-protected",
            "sender_did": did,
            "operation_id": operation_id,
        },
        "body": body,
    }


def _group_params(*, method: str, sender_did: str, target_did: str, operation_id: str, body: dict, private_key, target_kind: str = "group") -> dict:
    meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "target": {"kind": target_kind, "did": target_did},
        "operation_id": operation_id,
        "content_type": "text/plain" if method == "group.send" else "application/json",
    }
    if method == "group.send":
        meta["message_id"] = body.get("client_message_id") or f"msg-{operation_id}"
    return {
        "meta": meta,
        "auth": {
            "scheme": "anp-rfc9421-origin-proof-v1",
            "origin_proof": origin_proof(meta, body, private_key, method=method),
        },
        "body": body,
    }


@pytest.mark.asyncio
async def test_sync_v2_single_device_bootstrap_delta_and_hydration(client):
    owner, owner_token, account_id, _ = await _register_single_device(client, "sync-v2-owner")
    peer, peer_token = await register(client, "sync-v2-peer")

    capabilities = await rpc(client, "/im/rpc", "anp.get_capabilities", {}, token=owner_token)
    result = capabilities["result"]
    assert "anp.sync.local.v2" in result["profiles"]
    assert result["disabled_features"]["multi_device"] == "not_supported"
    assert result["disabled_features"]["sync_v2_mode"] == "single_device_pull_only"
    assert result["features"]["methods"]["sync.delta"]["profiles"] == [
        "anp.sync.local.v1",
        "anp.sync.local.v2",
    ]

    bootstrap = await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(
            owner,
            "op-sync-v2-bootstrap",
            {
                "client_instance_id": "client-instance-primary",
                "capabilities": {"sync_profile": "anp.sync.local.v2", "event_schema_max": 1},
            },
        ),
        token=owner_token,
    )
    bootstrap_result = bootstrap["result"]
    assert bootstrap_result["mode"] == "tail_only"
    assert bootstrap_result["account_id"] == account_id
    assert bootstrap_result["device_id"] == "device-primary"
    assert bootstrap_result["cursor"] == {"stream_epoch": "1", "scan_seq": "0"}
    assert bootstrap_result["warnings"] == ["single_device_pull_only"]

    sent = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {"recipient_did": owner, "text": "single-device v2 delta"},
        token=peer_token,
    )
    delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        _v2_params(
            owner,
            "op-sync-v2-delta",
            {
                "cursor": bootstrap_result["cursor"],
                "limit": 100,
                "reason": "foreground_reconcile",
            },
        ),
        token=owner_token,
    )
    delta_result = delta["result"]
    assert delta_result["mode"] == "delta"
    assert delta_result["next_cursor"] == {"stream_epoch": "1", "scan_seq": "1"}
    event = delta_result["events"][0]
    assert event["event_type"] == "message.created"
    assert event["account_id"] == account_id
    assert event["recipient_device_id"] is None
    assert event["payload"]["message_kind"] == "direct_plain"
    assert event["payload"]["direction"] == "incoming"
    assert event["thread_key"] == f"direct:{peer}"

    batch = await rpc(
        client,
        "/im/rpc",
        "message.get_batch",
        _v2_params(owner, "op-sync-v2-batch", {"event_ids": [event["event_id"]]}),
        token=owner_token,
    )
    assert batch["result"]["unavailable"] == []
    hydrated = batch["result"]["items"][0]["message"]
    assert hydrated["message_id"] == sent["result"]["message_id"]
    assert hydrated["thread_kind"] == "direct"
    assert hydrated["content"] == "single-device v2 delta"


@pytest.mark.asyncio
async def test_sync_v2_rejects_a_second_client_instance_and_multiple_manifest_devices(client):
    owner, token, _, _ = await _register_single_device(client, "sync-v2-single")
    first = await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(
            owner,
            "op-first-bootstrap",
            {
                "client_instance_id": "only-client",
                "capabilities": {"sync_profile": "anp.sync.local.v2", "event_schema_max": 1},
            },
        ),
        token=token,
    )
    assert first["result"]["mode"] == "tail_only"
    second = await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(
            owner,
            "op-second-bootstrap",
            {
                "client_instance_id": "second-client",
                "capabilities": {"sync_profile": "anp.sync.local.v2", "event_schema_max": 1},
            },
        ),
        token=token,
    )
    assert second["error"]["message"] == "sync.multiple_devices_not_supported"

    did = "did:wba:testserver:user:sync-v2-multi:e1_device"
    private_key, document = did_keypair_document(did)
    document["service"][0].update(
        {"serviceEndpoint": "http://testserver/anp-im/rpc", "serviceDid": "did:wba:testserver"}
    )
    document["deviceManifest"] = {
        "devices": [
            {"device_id": "device-one", "signing_key_id": f"{did}#key-1"},
            {"device_id": "device-two", "signing_key_id": f"{did}#key-1"},
        ]
    }
    document = sign_did_document(document, private_key)
    rejected = await rpc(
        client,
        "/user-service/v1/did-auth/rpc",
        "register",
        {"handle": "sync-v2-multi", "did_document": document},
    )
    assert rejected["error"]["message"] == "multiple_devices_not_supported"


@pytest.mark.asyncio
async def test_sync_v2_group_delta_batch_and_thread_after(client):
    owner, owner_token, account_id, owner_key = await _register_single_device(client, "sync-v2-group-owner")
    peer, peer_token, _, peer_key = await _register_single_device(client, "sync-v2-group-peer")

    bootstrap = await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(
            owner,
            "op-sync-v2-group-bootstrap",
            {
                "client_instance_id": "group-client-primary",
                "capabilities": {"sync_profile": "anp.sync.local.v2", "event_schema_max": 1},
            },
        ),
        token=owner_token,
    )
    cursor = bootstrap["result"]["cursor"]

    created = await rpc(
        client,
        "/im/rpc",
        "group.create",
        _group_params(
            method="group.create",
            sender_did=owner,
            target_did="did:wba:testserver",
            target_kind="service",
            operation_id="op-sync-v2-group-create",
            private_key=owner_key,
            body={
                "group_profile": {"display_name": "Sync v2 Group"},
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
                    "attachments_allowed": True,
                    "max_members": "100",
                },
            },
        ),
        token=owner_token,
    )
    assert "error" not in created
    group_did = created["result"]["group_did"]
    added = await rpc(
        client,
        "/im/rpc",
        "group.add",
        _group_params(
            method="group.add",
            sender_did=owner,
            target_did=group_did,
            operation_id="op-sync-v2-group-add",
            private_key=owner_key,
            body={"member_did": peer, "role": "member"},
        ),
        token=owner_token,
    )
    assert added["result"]["membership_status"] == "active"

    first = await rpc(
        client,
        "/im/rpc",
        "group.send",
        _group_params(
            method="group.send",
            sender_did=peer,
            target_did=group_did,
            operation_id="op-sync-v2-group-send-first",
            private_key=peer_key,
            body={"text": "group v2 first", "client_message_id": "msg-sync-v2-group-first"},
        ),
        token=peer_token,
    )
    second = await rpc(
        client,
        "/im/rpc",
        "group.send",
        _group_params(
            method="group.send",
            sender_did=owner,
            target_did=group_did,
            operation_id="op-sync-v2-group-send-second",
            private_key=owner_key,
            body={"text": "group v2 second", "client_message_id": "msg-sync-v2-group-second"},
        ),
        token=owner_token,
    )

    delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        _v2_params(
            owner,
            "op-sync-v2-group-delta",
            {"cursor": cursor, "limit": 100, "reason": "foreground_reconcile"},
        ),
        token=owner_token,
    )
    message_events = [
        event
        for event in delta["result"]["events"]
        if event["event_type"] == "message.created" and event["payload"].get("group_did") == group_did
    ]
    assert len(message_events) == 2
    assert {event["aggregate_id"] for event in message_events} == {
        first["result"]["message_id"],
        second["result"]["message_id"],
    }
    for event in message_events:
        assert event["account_id"] == account_id
        assert event["recipient_device_id"] is None
        assert event["aggregate_kind"] == "group_message"
        assert event["thread_key"] == group_did
        assert event["payload"]["message_kind"] == "group_plain"

    hydrated = await rpc(
        client,
        "/im/rpc",
        "message.get_batch",
        _v2_params(owner, "op-sync-v2-group-batch", {"event_ids": [event["event_id"] for event in message_events]}),
        token=owner_token,
    )
    assert hydrated["result"]["unavailable"] == []
    messages = [item["message"] for item in hydrated["result"]["items"]]
    assert {message["message_id"] for message in messages} == {
        first["result"]["message_id"],
        second["result"]["message_id"],
    }
    assert all(message["thread_kind"] == "group" and message["group_did"] == group_did for message in messages)

    first_page = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        _v2_params(
            owner,
            "op-sync-v2-group-thread-first",
            {"thread_key": group_did, "after_server_seq": "0", "limit": 1},
        ),
        token=owner_token,
    )
    assert len(first_page["result"]["messages"]) == 1
    assert first_page["result"]["has_more"] is True
    first_seq = first_page["result"]["next_after_server_seq"]

    second_page = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        _v2_params(
            owner,
            "op-sync-v2-group-thread-second",
            {"thread_key": f"group:{group_did}", "after_server_seq": first_seq, "limit": 10},
        ),
        token=owner_token,
    )
    assert len(second_page["result"]["messages"]) == 1
    assert second_page["result"]["messages"][0]["message_id"] != first_page["result"]["messages"][0]["message_id"]
    assert second_page["result"]["has_more"] is False
    assert all(item["thread_kind"] == "group" for item in first_page["result"]["messages"] + second_page["result"]["messages"])

    tail = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        _v2_params(
            owner,
            "op-sync-v2-group-thread-tail",
            {
                "thread_key": group_did,
                "after_server_seq": second_page["result"]["next_after_server_seq"],
                "limit": 10,
            },
        ),
        token=owner_token,
    )
    assert tail["result"]["messages"] == []
    assert tail["result"]["has_more"] is False


@pytest.mark.asyncio
async def test_sync_v2_group_thread_after_enforces_membership(client):
    owner, owner_token, _, owner_key = await _register_single_device(client, "sync-v2-thread-owner")
    outsider, outsider_token, _, _ = await _register_single_device(client, "sync-v2-thread-outsider")
    created = await rpc(
        client,
        "/im/rpc",
        "group.create",
        _group_params(
            method="group.create",
            sender_did=owner,
            target_did="did:wba:testserver",
            target_kind="service",
            operation_id="op-sync-v2-thread-create",
            private_key=owner_key,
            body={
                "group_profile": {"display_name": "Private thread"},
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
        ),
        token=owner_token,
    )
    group_did = created["result"]["group_did"]
    denied = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        _v2_params(
            outsider,
            "op-sync-v2-thread-denied",
            {"thread_key": group_did, "after_server_seq": "0", "limit": 10},
        ),
        token=outsider_token,
    )
    assert denied["error"]["message"] == "group.not_member"
