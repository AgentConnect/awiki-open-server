from __future__ import annotations

import pytest

from tests.conftest import rpc


def test_user_compat_package_exports_handler_maps():
    import awiki_open_server.services as services
    import awiki_open_server.user_compat as user_compat

    maps = [
        "IDENTITY_HANDLERS",
        "DID_VERIFY_HANDLERS",
        "PROFILE_HANDLERS",
        "ME_HANDLERS",
        "HANDLE_HANDLERS",
        "USERS_HANDLERS",
        "AGENT_REGISTRATION_HANDLERS",
        "MESSAGE_AGENT_HANDLERS",
        "AGENT_INVENTORY_HANDLERS",
    ]
    for name in maps:
        assert set(getattr(user_compat, name)) == set(getattr(services, name))


@pytest.mark.asyncio
async def test_handle_lookup_resolves_verified_cross_domain_did_for_cli_projection(client, monkeypatch):
    from awiki_open_server.user_compat import core

    remote_did = "did:wba:remote.example:user:alice:e1_remote"
    remote_document = {"id": remote_did, "proof": {"type": "DataIntegrityProof"}}
    monkeypatch.setattr(core.runtime, "_fetch_did_document", lambda did, settings: remote_document)
    monkeypatch.setattr(core, "verify_did_document_data_integrity_proof", lambda document, expected_did: None)

    lookup = await rpc(
        client,
        "/user-service/v1/handle/rpc",
        "lookup",
        {"did": remote_did},
    )

    assert lookup["result"] == {
        "did": remote_did,
        "user_id": "user-f2f4eab482cf5794775e4016",
        "handle": "alice",
        "domain": "remote.example",
        "full_handle": "alice.remote.example",
        "status": "active",
        "profile": {
            "did": remote_did,
            "handle": "alice@remote.example",
            "display_name": "alice",
        },
    }


@pytest.mark.asyncio
async def test_user_compat_did_auth_profile_and_handle_shape(client):
    registered = await rpc(
        client,
        "/user-service/did-auth/rpc",
        "register",
        {"handle": "compat-alice", "display_name": "Compat Alice"},
    )
    token = registered["result"]["token"]
    did = registered["result"]["did"]

    verified = await rpc(client, "/user-service/did-auth/rpc", "verify_http_request", token=token)
    assert verified["result"] == {"ok": True, "did": did, "scheme": "bearer-dev"}

    profile = await rpc(client, "/user-service/did/profile/rpc", "get_me", token=token)
    assert profile["result"]["did"] == did
    assert profile["result"]["display_name"] == "Compat Alice"

    handle = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "compat-alice.testserver"})
    assert handle["result"]["did"] == did
    assert handle["result"]["full_handle"] == "compat-alice.testserver"

    user = await rpc(client, "/user-service/users/rpc", "get_by_did", {"did": did})
    assert user["result"]["did"] == did
    assert user["result"]["handle"] == "compat-alice"


@pytest.mark.asyncio
async def test_user_compat_contact_verification_default_gate(client):
    sms_code = await client.post("/user-service/auth/sms-codes", json={"phone": "13800138000"})
    assert sms_code.status_code == 400
    assert sms_code.json()["detail"]["error"] == "contact_verification_not_enabled"

    email = await client.post("/user-service/auth/email-send", json={"email": "alice@example.com"})
    assert email.status_code == 400
    assert email.json()["detail"]["error"] == "contact_verification_not_enabled"


@pytest.mark.asyncio
async def test_user_compat_token_and_ws_ticket_routes(contact_verification_compat_client):
    client = contact_verification_compat_client
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "compat-ticket"})
    token = registered["result"]["token"]
    refresh_token = registered["result"]["refresh_token"]
    did = registered["result"]["did"]

    verified = await client.get("/user-service/auth/token-verify", headers={"Authorization": f"Bearer {token}"})
    assert verified.status_code == 200
    assert verified.json()["did"] == did
    assert verified.headers["X-DID"] == did

    refreshed = await client.post("/user-service/auth/token-refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != token
    assert refreshed.json()["refresh_token"] != refresh_token
    token = refreshed.json()["access_token"]

    ticket = await client.post("/user-service/ws/tickets", headers={"Authorization": f"Bearer {token}"})
    assert ticket.status_code == 200
    assert ticket.json()["ticket"] == token

    ticket_verified = await client.get("/user-service/ws/tickets/verify", params={"ticket": ticket.json()["ticket"]})
    assert ticket_verified.status_code == 200
    assert ticket_verified.headers["X-User-Id"] == did
