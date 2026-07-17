from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

import awiki_open_server.messaging.core as messaging_services
import awiki_open_server.shared.runtime as runtime
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import (
    build_service_did_document,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
    verify_peer_http_signature,
)
from awiki_open_server.shared.errors import InvalidParams
from tests.conftest import rpc
from tests.helpers import did_keypair_document, origin_proof, register, register_with_key, remote_direct_result

@pytest.mark.asyncio
async def test_group_participant_local_views_require_membership(client):
    alice_did, alice_token = await register(client, "group-member-alice")
    bob_did, bob_token = await register(client, "group-member-bob")
    group_did = "did:wba:testserver:groups:open"

    info = await rpc(client, "/im/rpc", "group.get_info", {"group_did": group_did}, token=bob_token)
    assert info["result"]["group_did"] == group_did

    bob_members_denied = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=bob_token)
    assert bob_members_denied["error"]["message"] == "group.not_member"

    bob_messages_denied = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=bob_token)
    assert bob_messages_denied["error"]["message"] == "group.not_member"

    bob_leave_denied = await rpc(client, "/im/rpc", "group.leave", {"group_did": group_did}, token=bob_token)
    assert bob_leave_denied["error"]["message"] == "group.not_member"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    sent = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "member only"}, token=alice_token)
    assert sent["result"]["accepted"] is True

    alice_members = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=alice_token)
    assert [member["member_did"] for member in alice_members["result"]["members"]] == [alice_did]

    alice_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert [message["message_id"] for message in alice_messages["result"]["messages"]] == [sent["result"]["message_id"]]

    bob_messages_still_denied = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=bob_token)
    assert bob_messages_still_denied["error"]["message"] == "group.not_member"

    bob_thread_denied = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {"thread": {"kind": "group", "group_did": group_did}, "after_server_seq": 0},
        token=bob_token,
    )
    assert bob_thread_denied["error"]["message"] == "group.not_member"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=bob_token)
    bob_members = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=bob_token)
    assert {member["member_did"] for member in bob_members["result"]["members"]} == {alice_did, bob_did}

    bob_thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {"thread": {"kind": "group", "group_did": group_did}, "after_server_seq": 0},
        token=bob_token,
    )
    assert [message["message_id"] for message in bob_thread["result"]["messages"]] == [sent["result"]["message_id"]]

    left = await rpc(client, "/im/rpc", "group.leave", {"group_did": group_did}, token=alice_token)
    assert left["result"]["left"] is True

    alice_after_leave_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert alice_after_leave_messages["error"]["message"] == "group.not_member"

    alice_send_after_leave = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "after leave"}, token=alice_token)
    assert alice_send_after_leave["error"]["message"] == "not_group_member"


@pytest.mark.asyncio
async def test_group_local_views_support_anp_params_and_pagination(client):
    alice_did, alice_token = await register(client, "group-page-alice")
    bob_did, bob_token = await register(client, "group-page-bob")
    group_did = "did:wba:testserver:groups:open"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=bob_token)

    first = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "first"}, token=alice_token)
    second = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "second"}, token=alice_token)
    third = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "third"}, token=bob_token)

    listed = await rpc(
        client,
        "/im/rpc",
        "group.list",
        {
            "meta": {"profile": "anp.group.local.v1", "sender_did": alice_did},
            "body": {"user_did": alice_did, "limit": 1},
        },
        token=alice_token,
    )
    assert [group["group_did"] for group in listed["result"]["groups"]] == [group_did]

    members = await rpc(
        client,
        "/im/rpc",
        "group.list_members",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {"user_did": alice_did, "group_did": group_did, "limit": 1},
        },
        token=alice_token,
    )
    assert [member["member_did"] for member in members["result"]["members"]] == [alice_did]

    first_page = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {
                "user_did": alice_did,
                "group_did": group_did,
                "since_seq": str(first["result"]["server_seq"]),
                "limit": 1,
            },
        },
        token=alice_token,
    )
    assert [message["message_id"] for message in first_page["result"]["messages"]] == [second["result"]["message_id"]]
    assert first_page["result"]["next_since_seq"] == str(second["result"]["server_seq"])
    assert first_page["result"]["total"] == 2
    assert first_page["result"]["has_more"] is True

    page = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {
                "user_did": alice_did,
                "group_did": group_did,
                "since_seq": str(first["result"]["server_seq"]),
                "skip": 1,
                "limit": 1,
            },
        },
        token=alice_token,
    )
    assert [message["message_id"] for message in page["result"]["messages"]] == [third["result"]["message_id"]]
    assert page["result"]["next_since_seq"] == str(third["result"]["server_seq"])
    assert page["result"]["total"] == 2
    assert page["result"]["has_more"] is False

    mismatch = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": bob_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {"user_did": alice_did, "group_did": group_did},
        },
        token=alice_token,
    )
    assert mismatch["error"]["message"] == "group.local.sender_did_mismatch"

    target_mismatch = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": "did:wba:testserver:groups:other"},
            },
            "body": {"user_did": alice_did, "group_did": group_did},
        },
        token=alice_token,
    )
    assert target_mismatch["error"]["message"] == "group.local_target_did_mismatch"

    invalid_since = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did, "since_seq": "bad"}, token=alice_token)
    assert invalid_since["error"]["message"] == "group.messages_since_seq_invalid"

    too_large = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did, "limit": 101}, token=alice_token)
    assert too_large["error"]["message"] == "limit_too_large"


@pytest.mark.asyncio
async def test_group_send_is_idempotent_for_same_message_and_rejects_conflicts(client):
    alice_did, alice_token = await register(client, "group-idem-alice")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice_did,
        "target": {"kind": "group", "did": group_did},
        "operation_id": "op-group-idem",
        "message_id": "msg-group-idem",
        "content_type": "text/plain",
    }
    body = {"text": "idempotent group"}

    first = await rpc(client, "/im/rpc", "group.send", {"meta": meta, "body": body}, token=alice_token)
    replay = await rpc(client, "/im/rpc", "group.send", {"meta": meta, "body": body}, token=alice_token)
    assert replay["result"]["idempotent_replay"] is True
    assert replay["result"]["message_id"] == first["result"]["message_id"]
    assert replay["result"]["server_seq"] == first["result"]["server_seq"]

    messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert [message["message_id"] for message in messages["result"]["messages"]] == ["msg-group-idem"]

    changed_body = await rpc(
        client,
        "/im/rpc",
        "group.send",
        {"meta": meta, "body": {"text": "changed group"}},
        token=alice_token,
    )
    assert changed_body["error"]["message"] == "message_id_conflict"
    assert changed_body["error"]["data"]["fields"] == ["body"]

    changed_operation_meta = {**meta, "operation_id": "op-group-idem-other"}
    changed_operation = await rpc(
        client,
        "/im/rpc",
        "group.send",
        {"meta": changed_operation_meta, "body": body},
        token=alice_token,
    )
    assert changed_operation["error"]["message"] == "message_id_conflict"
    assert changed_operation["error"]["data"]["fields"] == ["operation_id"]


@pytest.mark.asyncio
async def test_public_anp_group_join_requires_origin_and_peer_signature(tmp_path, monkeypatch):
    local_private_key = generate_ed25519_private_key_pem()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=local_private_key,
            allow_unsigned_peer_dev=False,
        )
    )
    remote_private_key = generate_ed25519_private_key_pem()
    remote_doc = build_service_did_document("did:wba:awiki.info", "https://awiki.info/anp-im/rpc", remote_private_key)
    remote_user_did = "did:wba:awiki.info:users:group-joiner"
    remote_user_key, remote_user_doc = did_keypair_document(remote_user_did)
    remote_identity = service_identity_from_settings(
        service_did="did:wba:awiki.info",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=remote_private_key,
        document_json=None,
    )

    def fake_get_json(url: str):
        if url == "https://awiki.info/users/group-joiner/did.json":
            return remote_user_doc
        assert url == "https://awiki.info/.well-known/did.json"
        return remote_doc

    monkeypatch.setattr(runtime, "_http_get_json", fake_get_json)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as signed_client:
        group_did = "did:wba:testserver:groups:open"
        meta = {
            "anp_version": "1.0",
            "profile": "anp.group.base.v1",
            "security_profile": "transport-protected",
            "sender_did": remote_user_did,
            "target": {"kind": "group", "did": group_did},
            "operation_id": "op-group-join",
            "created_at": "2026-07-03T00:00:00Z",
            "content_type": "application/json",
        }
        body_payload = {"group_did": group_did}
        unsigned_payload = {
            "jsonrpc": "2.0",
            "method": "group.join",
            "params": {"meta": meta, "body": body_payload},
            "id": "group-join-unsigned",
        }
        unsigned_response = await signed_client.post("/anp-im/rpc", json=unsigned_payload)
        assert unsigned_response.json()["error"]["message"] == "missing_origin_proof"

        signed_payload = {
            "jsonrpc": "2.0",
            "method": "group.join",
            "params": {
                "meta": meta,
                "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body_payload, remote_user_key, method="group.join")},
                "body": body_payload,
            },
            "id": "group-join-signed",
        }
        raw_body = __import__("json").dumps(signed_payload).encode()
        base_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:awiki.info"}
        signature_headers = remote_identity.sign_headers("http://testserver/anp-im/rpc", "POST", base_headers, raw_body)
        response = await signed_client.post("/anp-im/rpc", content=raw_body, headers={**base_headers, **signature_headers})
        data = response.json()
        assert data["result"]["joined"] is True
        assert data["result"]["group_did"] == group_did
        assert data["result"]["member_did"] == remote_user_did
