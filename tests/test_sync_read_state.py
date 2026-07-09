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
async def test_sync_delta_thread_after_and_read_state_standard_shapes(client):
    alice, alice_token = await register(client, "sync-alice")
    bob, bob_token = await register(client, "sync-bob")

    sent = await rpc(client, "/im/rpc", "direct.send", {"to": bob, "text": "sync hello"}, token=alice_token)
    message_id = sent["result"]["message_id"]

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
    assert result["events"][0]["event_type"] == "message.created"
    assert result["events"][0]["owner_subject_id"] == bob
    assert result["events"][0]["aggregate_kind"] == "direct_message"
    assert result["events"][0]["payload"]["thread"] == {"kind": "direct", "peer_did": alice}
    assert result["events"][0]["payload"]["message"]["id"] == message_id
    assert result["events"][0]["payload"]["message"]["sender_did"] == alice
    assert result["events"][0]["payload"]["message"]["receiver_did"] == bob
    assert result["events"][0]["payload"]["message"]["content"] == "sync hello"

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
    assert thread["result"]["messages"][0]["message_id"] == message_id
    assert thread["result"]["next_after_server_seq"] == str(thread["result"]["next_server_seq"])

    read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "meta": {"profile": "anp.read_state.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "read_up_to_server_seq": str(thread["result"]["next_server_seq"]),
                "read_up_to_message_id": message_id,
            },
        },
        token=bob_token,
    )
    assert read["result"]["remote_acknowledged"] is True
    assert read["result"]["pending_remote_ack"] is False
    assert read["result"]["read_watermark_server_seq"] == str(thread["result"]["next_server_seq"])
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
    assert read_by_id["result"]["read_watermark_server_seq"] == str(thread["result"]["next_server_seq"])
    assert read_by_id["result"]["updated_count"] == 0

    mismatch = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "direct", "peer_did": alice},
            "read_up_to_server_seq": str(int(thread["result"]["next_server_seq"]) + 1),
            "read_up_to_message_id": message_id,
        },
        token=bob_token,
    )
    assert mismatch["error"]["message"] == "read_state.watermark_mismatch"

    after_read_delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {"body": {"user_did": bob, "since_event_seq": "1", "limit": 100}},
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
