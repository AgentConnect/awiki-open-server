from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem


@pytest.mark.asyncio
async def test_healthz(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")
        health = await client.get("/health")
        user_service_health = await client.get("/user-service/health")
        im_health = await client.get("/im/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert user_service_health.status_code == 200
    assert user_service_health.json()["status"] == "ok"
    assert im_health.status_code == 200
    assert im_health.json()["status"] == "ok"
    assert (tmp_path / "awiki-open-server.sqlite3").exists()


def test_im_websocket_accepts_ws_ticket(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
        )
    )
    with TestClient(app) as client:
        registered = client.post(
            "/did-auth/rpc",
            json={"jsonrpc": "2.0", "method": "register", "params": {"handle": "ws-user"}, "id": "1"},
        ).json()["result"]
        ticket = client.post("/ws/tickets", headers={"Authorization": f"Bearer {registered['token']}"}).json()["ticket"]
        with client.websocket_connect(f"/im/ws?ticket={ticket}") as websocket:
            notification = websocket.receive_json()

    assert notification["method"] == "sync"
    assert notification["params"]["owner_did"] == registered["did"]


def test_im_websocket_accepts_bearer_authorization(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
        )
    )
    with TestClient(app) as client:
        registered = client.post(
            "/did-auth/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "register",
                "params": {"handle": "ws-bearer"},
                "id": "1",
            },
        ).json()["result"]
        with client.websocket_connect(
            "/im/ws",
            headers={"Authorization": f"Bearer {registered['token']}"},
        ) as websocket:
            notification = websocket.receive_json()

    assert notification["method"] == "sync"
    assert notification["params"]["owner_did"] == registered["did"]


def test_im_websocket_receives_direct_and_group_notifications(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
        )
    )
    with TestClient(app) as client:
        alice = client.post(
            "/did-auth/rpc",
            json={"jsonrpc": "2.0", "method": "register", "params": {"handle": "ws-alice"}, "id": "1"},
        ).json()["result"]
        bob = client.post(
            "/did-auth/rpc",
            json={"jsonrpc": "2.0", "method": "register", "params": {"handle": "ws-bob"}, "id": "2"},
        ).json()["result"]
        bob_ticket = client.post("/ws/tickets", headers={"Authorization": f"Bearer {bob['token']}"}).json()["ticket"]

        with client.websocket_connect(f"/im/ws?ticket={bob_ticket}") as websocket:
            initial = websocket.receive_json()
            assert initial["method"] == "sync"

            sent = client.post(
                "/im/rpc",
                headers={"Authorization": f"Bearer {alice['token']}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "direct.send",
                    "params": {"recipient_did": bob["did"], "text": "hello over ws"},
                    "id": "3",
                },
            ).json()["result"]
            direct_notification = websocket.receive_json()
            assert direct_notification["method"] == "direct.incoming"
            assert direct_notification["params"]["message"]["message_id"] == sent["message_id"]
            assert direct_notification["params"]["message"]["body"]["text"] == "hello over ws"
            assert direct_notification["sync"]["event_type"] == "direct.message.created"

            group_did = "did:wba:testserver:groups:open"
            client.post(
                "/im/rpc",
                headers={"Authorization": f"Bearer {bob['token']}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "group.join",
                    "params": {"group_did": group_did},
                    "id": "4",
                },
            )
            state_notification = websocket.receive_json()
            assert state_notification["method"] == "group.state_changed"
            assert state_notification["params"]["change"] == "member_joined"
            assert state_notification["params"]["group_did"] == group_did

            group_msg = client.post(
                "/im/rpc",
                headers={"Authorization": f"Bearer {bob['token']}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "group.send",
                    "params": {"group_did": group_did, "text": "group over ws"},
                    "id": "5",
                },
            ).json()["result"]
            group_notification = websocket.receive_json()
            assert group_notification["method"] == "group.incoming"
            assert group_notification["params"]["message"]["message_id"] == group_msg["message_id"]
            assert group_notification["params"]["message"]["body"]["text"] == "group over ws"
            assert group_notification["sync"]["event_type"] == "group.message.created"
