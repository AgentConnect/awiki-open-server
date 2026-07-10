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


def _contains_key(value, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


@pytest.mark.asyncio
async def test_sync_delta_thread_after_and_read_state_standard_shapes(client):
    alice, alice_token = await register(client, "sync-alice")
    bob, bob_token = await register(client, "sync-bob")

    first = await rpc(client, "/im/rpc", "direct.send", {"to": bob, "text": "sync hello 1"}, token=alice_token)
    second = await rpc(client, "/im/rpc", "direct.send", {"to": bob, "text": "sync hello 2"}, token=alice_token)
    message_id = first["result"]["message_id"]

    delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {"user_did": bob, "since_event_seq": "0", "limit": 100},
        },
        token=bob_token,
    )
    result = delta["result"]
    assert result["owner_subject_id"] == bob
    assert result["has_more"] is False
    assert result["snapshot_required"] is False
    assert result["warnings"] == []
    assert result["events"][0]["event_seq"] == "1"
    assert result["events"][0]["owner_subject_id"] == bob
    assert result["events"][0]["aggregate_kind"] == "direct_message"
    assert result["events"][0]["aggregate_id"] == message_id
    payload = result["events"][0]["payload"]
    assert payload["thread"] == {"kind": "direct", "peer_did": alice}
    assert payload["message"]["message_id"] == message_id
    assert payload["message"]["server_seq"] == str(first["result"]["server_seq"])
    assert "sync hello" not in json.dumps(payload)
    assert not _contains_key(payload, "body")
    assert not _contains_key(payload, "content")

    limited_delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {"body": {"user_did": bob, "since_event_seq": "0", "limit": 1}},
        token=bob_token,
    )
    assert len(limited_delta["result"]["events"]) == 1
    assert limited_delta["result"]["has_more"] is True

    thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "after_server_seq": "0",
                "limit": 100,
            },
        },
        token=bob_token,
    )
    assert thread["result"]["thread"]["peer_did"] == alice
    assert [message["message_id"] for message in thread["result"]["messages"]] == [message_id, second["result"]["message_id"]]
    assert thread["result"]["next_after_server_seq"] == str(thread["result"]["next_server_seq"])
    assert thread["result"]["has_more"] is False

    limited_thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "after_server_seq": "0",
                "limit": 1,
            },
        },
        token=bob_token,
    )
    assert [message["message_id"] for message in limited_thread["result"]["messages"]] == [message_id]
    assert limited_thread["result"]["has_more"] is True

    read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "meta": {"profile": "anp.read_state.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "read_up_to_server_seq": str(first["result"]["server_seq"]),
                "read_up_to_message_id": message_id,
            },
        },
        token=bob_token,
    )
    assert read["result"]["remote_acknowledged"] is True
    assert read["result"]["pending_remote_ack"] is False
    assert read["result"]["updated_count"] == 1
    assert read["result"]["unread_count"] == 1
    assert read["result"]["read_watermark_server_seq"] == str(first["result"]["server_seq"])
    assert read["result"]["thread"]["kind"] == "direct"

    read_by_id = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "meta": {"profile": "anp.read_state.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "read_up_to_message_id": message_id,
            },
        },
        token=bob_token,
    )
    assert read_by_id["result"]["read_watermark_server_seq"] == str(first["result"]["server_seq"])
    assert read_by_id["result"]["updated_count"] == 0
    assert read_by_id["result"]["unread_count"] == 1

    mismatch = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "direct", "peer_did": alice},
            "read_up_to_server_seq": str(second["result"]["server_seq"]),
            "read_up_to_message_id": message_id,
        },
        token=bob_token,
    )
    assert mismatch["error"]["message"] == "read_state.watermark_mismatch"

    after_read_delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {"body": {"user_did": bob, "since_event_seq": result["next_event_seq"], "limit": 100}},
        token=bob_token,
    )
    assert after_read_delta["result"]["events"] == []

    bad_read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {"thread": {"kind": "direct", "peer_did": alice}, "event_seq": "1"},
        token=bob_token,
    )
    assert bad_read["error"]["message"] == "read_state.server_seq_invalid"


@pytest.mark.asyncio
async def test_group_read_state_uses_thread_watermark_without_sync_event(client):
    alice, alice_token = await register(client, "sync-group-alice")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    first = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "group sync 1"}, token=alice_token)
    second = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "group sync 2"}, token=alice_token)

    delta = await rpc(client, "/im/rpc", "sync.delta", {"after_event_seq": 0}, token=alice_token)
    message_events = [event for event in delta["result"]["events"] if event["event_type"] == "group.message.created"]
    assert message_events[0]["aggregate_kind"] == "group_message"
    assert message_events[0]["aggregate_id"] == first["result"]["message_id"]
    assert message_events[0]["payload"]["thread"] == {"kind": "group", "group_did": group_did}
    assert not _contains_key(message_events[0]["payload"], "body")
    assert "group sync" not in json.dumps(message_events[0]["payload"])

    read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "group", "group_did": group_did},
            "read_up_to_server_seq": str(first["result"]["server_seq"]),
        },
        token=alice_token,
    )
    assert read["result"]["updated_count"] == 1
    assert read["result"]["unread_count"] == 1
    assert read["result"]["read_watermark_server_seq"] == str(first["result"]["server_seq"])

    replay = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "group", "group_did": group_did},
            "read_up_to_server_seq": str(first["result"]["server_seq"]),
        },
        token=alice_token,
    )
    assert replay["result"]["updated_count"] == 0
    assert replay["result"]["unread_count"] == 1

    final_read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "group", "group_did": group_did},
            "read_up_to_server_seq": str(second["result"]["server_seq"]),
        },
        token=alice_token,
    )
    assert final_read["result"]["updated_count"] == 1
    assert final_read["result"]["unread_count"] == 0

    after_read_delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {"since_event_seq": delta["result"]["next_event_seq"]},
        token=alice_token,
    )
    assert after_read_delta["result"]["events"] == []
