from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from tests.helpers import sign_did_document, single_device_document


def rpc(client, method, params, token=None, path="/im/rpc"):
    response = client.post(path, json={"jsonrpc":"2.0", "id":"ws-fixture", "method":method, "params":params}, headers={"Authorization":f"Bearer {token}"} if token else {})
    assert response.status_code == 200
    return response.json()


def prepare(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, public_base_url="http://testserver", service_did="did:wba:testserver", did_domain="testserver", allow_unsigned_peer_dev=True))
    client = TestClient(app)
    root, _, doc = single_device_document("did:wba:testserver:users:ws:e1_fixture")
    did = doc["id"]
    doc["service"][0].update(serviceEndpoint="http://testserver/anp-im/rpc", serviceDid="did:wba:testserver")
    registered = rpc(client, "register", {"handle":"ws", "did_document":sign_did_document(doc, root)}, path="/user-service/v1/did-auth/rpc")
    return app, client, did, registered["result"]["access_token"]


def bind(client, did, token):
    rpc(client, "sync.bootstrap", {"meta":{"profile":"anp.sync.local.v2", "security_profile":"transport-protected", "sender_did":did, "operation_id":"ws-bootstrap"},
        "body":{"client_instance_id":"ws-only", "capabilities":{"sync_profile":"anp.sync.local.v2", "event_schema_max":1}}}, token)


def test_v3_hint_only_requires_binding_and_fences_revocation(tmp_path):
    app, client, did, token = prepare(tmp_path)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/im/ws", headers={"Authorization":f"Bearer {token}"}, subprotocols=["awiki.sync.event.v3"]):
            pytest.fail("unbound v3 connection accepted")
    bind(client, did, token)
    with client.websocket_connect("/im/ws", headers={"Authorization":f"Bearer {token}"}, subprotocols=["awiki.sync.event.v3"]) as ws:
        assert ws.accepted_subprotocol == "awiki.sync.event.v3"
        assert ws.receive_json()["sync"]["schema_version"] == 2
        app.state.realtime_hub.publish(did, {"method":"direct.message.created", "params":{"text":"must not inline"}, "sync":{"event_seq":"7"}})
        hint = ws.receive_json()
        assert hint["method"] == "sync.changed"
        assert hint["sync"]["account_scan_seq_hint"] == "7"
        assert "must not inline" not in json.dumps(hint)
        with app.state.store.connect() as conn:
            conn.execute("UPDATE users SET revoked_at='2026-09-17T00:00:00Z' WHERE did=?", (did,))
        app.state.realtime_hub.publish(did, {"sync":{"event_seq":"8"}})
        with pytest.raises(WebSocketDisconnect) as disconnected:
            ws.receive_json()
        assert disconnected.value.code == 4401


def test_v3_does_not_accept_query_credentials_or_unsupported_p6(tmp_path):
    _, client, did, token = prepare(tmp_path)
    bind(client, did, token)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/im/ws?token={token}", subprotocols=["awiki.sync.event.v3"]):
            pytest.fail("v3 accepted URL credentials")
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect("/im/ws", headers={"Authorization":f"Bearer {token}"}, subprotocols=["awiki.sync.event.v3.p6-delivery-context.v1"]):
            pytest.fail("unsupported P6 protocol accepted")
    assert disconnected.value.code == 4406


def test_old_p6_negotiation_cannot_reenable_ws_protocol(tmp_path):
    app, client, did, token = prepare(tmp_path)
    rpc(client, "sync.bootstrap", {
        "meta": {"profile": "anp.sync.local.v2", "security_profile": "transport-protected", "sender_did": did, "operation_id": "ws-compat-bootstrap"},
        "body": {"client_instance_id": "ws-only", "capabilities": {
            "sync_profile": "anp.sync.local.v2", "event_schema_max": 1,
            "requested_sync_capabilities": [],
            "requested_snapshot_capabilities": {"schema_max": 3, "deliveries": ["paged_v1"]},
        }},
    }, token)
    previous = json.dumps(["lanes.p5_device.v1", "lanes.p6_group.v1", "p6.delivery_context.v1"])
    with app.state.store.connect() as conn:
        conn.execute("UPDATE sync_capability_negotiations SET requested_json=?, negotiated_json=?", (previous, previous))
    client = TestClient(create_app(app.state.settings))
    protocol = "awiki.sync.event.v3.p6-delivery-context.v1"
    headers = {"Authorization": f"Bearer {token}", "X-AWiki-P6-Client-Instance-ID": "ws-only"}
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect("/im/ws", headers=dict(headers), subprotocols=[protocol]):
            pytest.fail("old negotiation reenabled unsupported P6 protocol")
    assert disconnected.value.code == 4406
    with client.websocket_connect("/im/ws", headers=dict(headers), subprotocols=[protocol, "awiki.sync.event.v3"]) as ws:
        assert ws.accepted_subprotocol == "awiki.sync.event.v3"
        assert ws.receive_json()["method"] == "sync.changed"
