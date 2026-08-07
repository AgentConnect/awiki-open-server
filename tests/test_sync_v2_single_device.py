from __future__ import annotations

import pytest

from tests.conftest import rpc
from tests.helpers import did_keypair_document, register, sign_did_document


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
    return did, response["result"]["access_token"], response["result"]["user_id"]


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


@pytest.mark.asyncio
async def test_sync_v2_single_device_bootstrap_delta_and_hydration(client):
    owner, owner_token, account_id = await _register_single_device(client, "sync-v2-owner")
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
    owner, token, _ = await _register_single_device(client, "sync-v2-single")
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
