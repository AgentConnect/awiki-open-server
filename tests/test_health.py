from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.messaging.groups import outbox
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
        operations = await client.get("/operations/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert user_service_health.status_code == 200
    assert user_service_health.json()["status"] == "ok"
    assert im_health.status_code == 200
    assert im_health.json()["status"] == "ok"
    assert operations.status_code == 404
    assert (tmp_path / "awiki-open-server.sqlite3").exists()


@pytest.mark.asyncio
async def test_operations_status_is_separately_protected_and_aggregate_only(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            operations_token="operations-test-secret",
        )
    )
    app.state.group_outbox_last_heartbeat = "2026-07-16T00:00:00+00:00"
    with app.state.store.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for event_seq, (delivery_id, status) in enumerate(
            (("gdlv-pending", "pending"), ("gdlv-dead", "dead")),
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO group_delivery_outbox(
                  delivery_id, group_did, group_event_seq, target_did, target_service_did,
                  method, envelope_json, status, next_attempt_at, created_at, updated_at
                    ) VALUES (?, 'did:wba:group.example:groups:test:e1_test', ?,
                          'did:wba:member.example:users:test:e1_test', 'did:wba:member.example',
                          'group.state_changed', '{}', ?, ?, ?, ?)
                """,
                (
                        delivery_id,
                        event_seq,
                        status,
                    "2000-01-01T00:00:00+00:00",
                    "2000-01-01T00:00:00+00:00",
                    "2000-01-01T00:00:00+00:00",
                ),
            )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        public_health = await client.get("/healthz")
        missing = await client.get("/operations/status")
        wrong = await client.get(
            "/operations/status",
            headers={"Authorization": "Bearer wrong-secret"},
        )
        response = await client.get(
            "/operations/status",
            headers={"Authorization": "Bearer operations-test-secret"},
        )

    assert public_health.json() == {"status": "ok", "edition": "community"}
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert response.status_code == 200
    status = response.json()
    assert "schema_version" not in status
    assert status["outbox"]["pending"] == 1
    assert status["outbox"]["dead"] == 1
    assert status["outbox"]["oldest_pending_age_seconds"] > 0
    assert status["outbox"]["worker_last_heartbeat"] == "2026-07-16T00:00:00+00:00"
    assert status["storage"]["group_key_directory"] == {
        "exists": True,
        "readable": True,
        "writable": True,
    }
    serialized = str(status).lower()
    assert "group_did" not in serialized
    assert "target_did" not in serialized
    assert "operations-test-secret" not in serialized


@pytest.mark.asyncio
async def test_outbox_worker_cycle_error_log_does_not_include_exception_message(
    monkeypatch,
    caplog,
):
    async def fail_to_thread(*_args, **_kwargs):
        raise RuntimeError("sensitive-envelope-proof-message")

    async def stop_after_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox.asyncio, "to_thread", fail_to_thread)
    monkeypatch.setattr(outbox.asyncio, "sleep", stop_after_cycle)
    app = type("App", (), {"state": type("State", (), {})()})()

    with caplog.at_level(logging.ERROR, logger=outbox.__name__):
        with pytest.raises(asyncio.CancelledError):
            await outbox.run_group_outbox(app)

    assert "result_code=RuntimeError" in caplog.text
    assert "sensitive-envelope-proof-message" not in caplog.text


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
    assert "event_seq" not in notification["params"]
    assert "checkpoint" not in notification["params"]


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
            assert "server_seq" not in direct_notification["sync"]
            assert "checkpoint" not in direct_notification["sync"]

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
            assert "server_seq" not in group_notification["sync"]
            assert "read_watermark_server_seq" not in group_notification["sync"]
