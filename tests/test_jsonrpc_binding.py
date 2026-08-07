from __future__ import annotations

import pytest


def _capabilities_payload(request_id: object = "req-cap") -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "anp.get_capabilities",
        "params": {
            "meta": {
                "profile": "anp.core.binding.v1",
                "security_profile": "transport-protected",
                "operation_id": "op-cap",
            },
            "body": {},
        },
        "id": request_id,
    }


@pytest.mark.asyncio
async def test_public_binding_parse_batch_params_and_id_rules(client) -> None:
    parse = await client.post(
        "/anp-im/rpc",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    batch = await client.post("/anp-im/rpc", json=[_capabilities_payload()])
    array_params_payload = _capabilities_payload()
    array_params_payload["params"] = []
    array_params = await client.post("/anp-im/rpc", json=array_params_payload)

    assert parse.json()["error"] == {"code": -32700, "message": "Parse error"}
    assert parse.json()["id"] is None
    assert batch.json()["error"]["code"] == 1004
    assert batch.json()["error"]["data"]["anp_code"] == "anp.batch_not_supported"
    assert array_params.json()["error"]["code"] == 1003
    assert array_params.json()["error"]["data"]["anp_code"] == "anp.invalid_params_shape"

    for invalid_id in (1, None, ""):
        response = await client.post("/anp-im/rpc", json=_capabilities_payload(invalid_id))
        error = response.json()["error"]
        assert error["code"] == 1000
        assert error["data"]["anp_code"] == "anp.invalid_request_id"

    missing_id = _capabilities_payload()
    del missing_id["id"]
    response = await client.post("/anp-im/rpc", json=missing_id)
    assert response.json()["error"]["data"]["anp_code"] == "anp.invalid_request_id"


@pytest.mark.asyncio
async def test_public_binding_requires_closed_profile_envelope(client) -> None:
    success = await client.post("/anp-im/rpc", json=_capabilities_payload())
    assert success.status_code == 200
    assert success.json()["result"]["service_did"] == "did:wba:testserver"

    wrong_profile = _capabilities_payload()
    wrong_profile["params"]["meta"]["profile"] = "anp.core.binding.v2"
    response = await client.post("/anp-im/rpc", json=wrong_profile)
    assert response.json()["error"]["data"]["anp_code"] == "anp.unsupported_profile"

    wrong_security = _capabilities_payload()
    wrong_security["params"]["meta"]["security_profile"] = "direct-e2ee"
    response = await client.post("/anp-im/rpc", json=wrong_security)
    assert response.json()["error"]["data"]["anp_code"] == "anp.unsupported_security_profile"

    unexpected = _capabilities_payload()
    unexpected["params"]["client"] = {"response_mode": "wait-final"}
    response = await client.post("/anp-im/rpc", json=unexpected)
    assert response.json()["error"]["data"]["anp_code"] == "anp.invalid_params_shape"

    target = _capabilities_payload()
    target["params"]["meta"]["target"] = {"kind": "service", "did": "did:wba:testserver"}
    response = await client.post("/anp-im/rpc", json=target)
    assert response.json()["error"]["data"]["anp_code"] == "anp.invalid_target_binding"


@pytest.mark.asyncio
async def test_public_binding_notification_semantics(client) -> None:
    notification = {
        "jsonrpc": "2.0",
        "method": "group.state_changed",
        "params": {
            "meta": {
                "profile": "anp.group.base.v1",
                "security_profile": "transport-protected",
                "sender_did": "did:wba:host.test:groups:g1",
                "target": {"kind": "agent", "did": "did:wba:testserver:users:alice:e1_default"},
                "operation_id": "event-1",
            },
            "body": {
                "group_did": "did:wba:host.test:groups:g1",
                "event_id": "event-1",
                "event_type": "group-profile-updated",
                "group_event_seq": "1",
                "group_state_version": "1",
            },
        },
    }
    response = await client.post("/anp-im/rpc", json=notification)
    assert response.status_code == 204
    assert response.content == b""

    notification["id"] = "not-allowed"
    response = await client.post("/anp-im/rpc", json=notification)
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32600
    assert response.json()["id"] == "not-allowed"


@pytest.mark.asyncio
async def test_public_binding_business_errors_have_anp_code(client) -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "direct.send",
        "params": {
            "meta": {
                "profile": "anp.direct.base.v1",
                "security_profile": "transport-protected",
                "sender_did": "did:wba:testserver:users:alice:e1_default",
                "target": {"kind": "agent", "did": "did:wba:testserver:users:bob:e1_default"},
                "operation_id": "op-direct",
                "message_id": "msg-direct",
                "content_type": "text/plain",
            },
            "body": {"text": "hello"},
        },
        "id": "req-direct",
    }
    response = await client.post("/anp-im/rpc", json=payload)
    error = response.json()["error"]
    if error["code"] >= 1000:
        assert error["data"]["anp_code"].startswith("anp.")
    else:
        assert error["code"] == -32602


@pytest.mark.asyncio
async def test_public_binding_method_not_found_keeps_jsonrpc_standard_code(client) -> None:
    payload = _capabilities_payload()
    payload["method"] = "sync.delta"
    response = await client.post("/anp-im/rpc", json=payload)
    assert response.json()["error"]["code"] == -32601
