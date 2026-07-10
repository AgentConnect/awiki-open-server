from __future__ import annotations

import pytest

from tests.conftest import rpc

@pytest.mark.asyncio
async def test_contact_verification_routes_disabled_by_default(client):
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "contact-disabled"})
    token = registered["result"]["token"]

    sms_code = await client.post("/user-service/auth/sms-codes", json={"phone": "13800138000"})
    assert sms_code.status_code == 400
    assert sms_code.json()["detail"]["error"] == "contact_verification_not_enabled"

    dev_login = await client.post("/user-service/auth/sms", json={"phone": "13800138001", "otp_code": "123456"})
    assert dev_login.status_code == 400
    assert dev_login.json()["detail"]["error"] == "contact_verification_not_enabled"

    email = await client.post("/user-service/auth/email-send", json={"email": "alice@example.com"})
    assert email.status_code == 400
    assert email.json()["detail"]["error"] == "contact_verification_not_enabled"

    status = await client.get("/user-service/auth/email-status")
    assert status.status_code == 400
    assert status.json()["detail"]["error"] == "contact_verification_not_enabled"

    bind_send = await client.post(
        "/user-service/auth/phone-bind-send",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone": "+8613800138000"},
    )
    assert bind_send.status_code == 400
    assert bind_send.json()["detail"]["error"] == "contact_verification_not_enabled"


@pytest.mark.asyncio
async def test_legacy_auth_and_ws_ticket_compat_routes(contact_verification_compat_client):
    client = contact_verification_compat_client
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "legacy-auth"})
    token = registered["result"]["token"]
    refresh_token = registered["result"]["refresh_token"]
    did = registered["result"]["did"]

    sms_code = await client.post("/user-service/auth/sms-codes", json={"phone": "13800138000"})
    assert sms_code.status_code == 200
    assert sms_code.json()["dev_otp"] == "123456"

    email = await client.post("/user-service/auth/email-send", json={"email": "alice@example.com"})
    assert email.status_code == 200
    assert email.json()["sent"] is True

    status = await client.get("/user-service/auth/email-status")
    assert status.status_code == 200
    assert status.json()["verified"] is True

    dev_login = await client.post("/user-service/auth/sms", json={"phone": "13800138001", "otp_code": "123456"})
    assert dev_login.status_code == 200
    assert dev_login.json()["access_token"].startswith("tok_")
    assert dev_login.json()["did"] == "did:wba:testserver:users:13800138001:e1_default"

    dev_login_again = await client.post("/auth/sms", json={"phone": "13800138001", "otp": "123456"})
    assert dev_login_again.status_code == 200
    assert dev_login_again.json()["access_token"] == dev_login.json()["access_token"]

    verified = await client.get("/user-service/auth/token-verify", headers={"Authorization": f"Bearer {token}"})
    assert verified.status_code == 200
    assert verified.json()["did"] == did
    assert verified.headers["X-User-Id"] == did

    auth_verify = await client.get("/user-service/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert auth_verify.status_code == 200
    assert auth_verify.headers["X-User-Id"] == did

    session_verify = await client.get("/sessions/verify", headers={"Authorization": f"Bearer {token}"})
    assert session_verify.status_code == 200
    assert session_verify.headers["X-User-Id"] == did

    refreshed = await client.post("/user-service/auth/token-refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != token
    assert refreshed.json()["refresh_token"] != refresh_token
    token = refreshed.json()["access_token"]

    ticket = await client.post("/user-service/ws/tickets", headers={"Authorization": f"Bearer {token}"})
    assert ticket.status_code == 200
    assert ticket.json()["did"] == did

    ticket_verified = await client.get("/user-service/ws/tickets/verify", params={"ticket": ticket.json()["ticket"]})
    assert ticket_verified.status_code == 200
    assert ticket_verified.json()["did"] == did
    assert ticket_verified.headers["X-User-Id"] == did

    header_ticket_verified = await client.get(
        "/user-service/auth/ws-ticket/verify",
        headers={"X-WS-Ticket": ticket.json()["ticket"]},
    )
    assert header_ticket_verified.status_code == 200
    assert header_ticket_verified.headers["X-User-Id"] == did


@pytest.mark.asyncio
async def test_did_verify_rpc_compat_routes(client):
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "did-verify-user"})
    token = registered["result"]["token"]
    did = registered["result"]["did"]

    sent = await rpc(client, "/did-verify/rpc", "send_code", {"did": did})
    assert sent["result"]["ok"] is True
    assert sent["result"]["did"] == did
    assert sent["result"]["provider"] == "dev"
    assert sent["result"]["dev_code"] == "666666"

    logged_in = await rpc(client, "/did-verify/rpc", "login", {"did": did, "code": "666666"})
    assert logged_in["result"]["access_token"] != token
    assert logged_in["result"]["refresh_token"] != registered["result"]["refresh_token"]
    assert logged_in["result"]["token_type"] == "Bearer"
    assert logged_in["result"]["did"] == did
    assert logged_in["result"]["user_id"] == did

    refreshed = await rpc(client, "/user-service/did-verify/rpc", "refresh", {"refresh_token": logged_in["result"]["refresh_token"]})
    assert refreshed["result"]["access_token"] != logged_in["result"]["access_token"]
    assert refreshed["result"]["refresh_token"] != logged_in["result"]["refresh_token"]
    assert refreshed["result"]["refreshed"] is True

    wrong_code = await rpc(client, "/did-verify/rpc", "login", {"did": did, "code": "123456"})
    assert wrong_code["error"]["message"] == "invalid_code"

    missing_did = await rpc(
        client,
        "/user-service/did-verify/rpc",
        "login",
        {"did": "did:wba:testserver:users:missing:e1_default", "code": "666666"},
    )
    assert missing_did["error"]["message"] == "did_not_found"

    bad_refresh = await rpc(client, "/did-verify/rpc", "refresh", {"refresh_token": "not-a-token"})
    assert bad_refresh["error"]["message"] == "invalid_refresh_token"
