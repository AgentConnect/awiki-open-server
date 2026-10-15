from __future__ import annotations

import pytest

from tests.conftest import rpc


HANDLE_PATH = "/user-service/v1/handle/rpc"


@pytest.mark.asyncio
async def test_registration_check_normalizes_local_handles_without_creating_accounts(client):
    result = await rpc(client, HANDLE_PATH, "registration_check", {
        "handle": " @Alice ", "domain": " TESTSERVER. ", "check_invite": True,
        "invite_code": "not-logged", "phone": "not-logged", "email": "not-logged",
    })
    assert result["result"] == {
        "handle": "alice", "domain": "testserver", "full_handle": "alice.testserver",
        "decision": "register", "invite_required": False, "invite_kind": None,
        "invite_status": "not_required", "reason": None,
    }
    absent = await rpc(client, HANDLE_PATH, "lookup", {"handle": "alice.testserver"})
    assert "error" in absent


@pytest.mark.parametrize("handle,domain,reason", [
    ("alice", "other.example", "domain_not_supported"),
    ("a--b", "testserver", "handle_invalid"),
    ("a/b", "testserver", "handle_invalid"),
    ("a" * 64, "testserver", "handle_invalid"),
])
@pytest.mark.asyncio
async def test_registration_check_rejects_wrong_domain_or_invalid_name(client, handle, domain, reason):
    result = await rpc(client, HANDLE_PATH, "registration_check", {"handle": handle, "domain": domain})
    assert result["result"]["decision"] == "unavailable"
    assert result["result"]["reason"] == reason


@pytest.mark.parametrize("params", [
    {"handle": "alice"},
    {"handle": "alice", "domain": "testserver", "unknown": "secret"},
    {"handle": "alice", "domain": "testserver", "check_invite": "true"},
])
@pytest.mark.asyncio
async def test_registration_check_rejects_invalid_fields_without_echoing_material(client, params):
    result = await rpc(client, HANDLE_PATH, "registration_check", params)
    assert result["error"]["code"] == -32602
    assert result["error"]["message"] == "registration_check_invalid_params"


@pytest.mark.asyncio
async def test_registration_check_retains_existing_and_revoked_name_ownership(client):
    registered = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "alice"})
    params = {"handle": "alice", "domain": "testserver"}
    active = await rpc(client, HANDLE_PATH, "registration_check", params)
    assert active["result"]["decision"] == "existing"
    await rpc(client, "/user-service/did-auth/rpc", "revoke", token=registered["result"]["token"])
    inactive = await rpc(client, HANDLE_PATH, "registration_check", params)
    assert inactive["result"]["decision"] == "unavailable"
    assert inactive["result"]["reason"] == "handle_unavailable"


@pytest.mark.asyncio
async def test_registration_commit_normalizes_and_rechecks_advisory_name(client):
    params = {"handle": " @Alice ", "domain": "testserver"}
    assert (await rpc(client, HANDLE_PATH, "registration_check", params))["result"]["decision"] == "register"
    registered = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "ALICE@testserver"})
    assert registered["result"]["handle"] == "alice"
    assert registered["result"]["full_handle"] == "alice.testserver"
    duplicate = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "alice.testserver"})
    assert duplicate["error"]["message"] == "handle_already_registered"
    assert (await rpc(client, HANDLE_PATH, "registration_check", params))["result"]["decision"] == "existing"


@pytest.mark.parametrize("handle,reason", [
    ("alice.other.example", "domain_not_supported"),
    ("alice@other.example", "domain_not_supported"),
    ("a--b", "handle_invalid"),
])
@pytest.mark.asyncio
async def test_registration_commit_rejects_invalid_or_foreign_names(client, handle, reason):
    denied = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": handle})
    assert denied["error"]["message"] == reason


@pytest.mark.asyncio
async def test_registration_preserves_legacy_mixed_case_name_ownership(client):
    registered = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "alice"})
    with client._transport.app.state.store.connect() as conn:
        conn.execute("UPDATE users SET handle=? WHERE did=?", ("Alice@TESTSERVER", registered["result"]["did"]))
    checked = await rpc(client, HANDLE_PATH, "registration_check", {"handle": "alice", "domain": "testserver"})
    assert checked["result"]["decision"] == "existing"
    duplicate = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "alice"})
    assert duplicate["error"]["message"] == "handle_already_registered"


@pytest.mark.asyncio
async def test_registration_check_limits_trusted_peer_even_with_spoofed_forwarding_headers(client):
    for index in range(21):
        response = await client.post(HANDLE_PATH, headers={"X-Forwarded-For": f"192.0.2.{index}"}, json={
            "jsonrpc": "2.0", "id": "rate", "method": "registration_check",
            "params": {"handle": "alice", "domain": "testserver"},
        })
        payload = response.json()
        if index < 20:
            assert payload["result"]["decision"] == "register"
        else:
            assert payload["error"]["code"] == -32005
            assert payload["error"]["data"]["code"] == "registration_check_rate_limited"
            assert 1 <= payload["error"]["data"]["retry_after_seconds"] <= 60


def test_registration_check_limit_expires_and_keeps_only_peer_hashes(monkeypatch):
    from awiki_open_server.user_compat import registration
    now = [100.0]
    monkeypatch.setattr(registration.time, "monotonic", lambda: now[0])
    limiter = registration.RegistrationCheckLimiter()
    for _ in range(20):
        limiter.check("private-peer")
    with pytest.raises(registration.RegistrationCheckRateLimited):
        limiter.check("private-peer")
    assert "private-peer" not in repr(limiter._clients)
    now[0] += 61
    limiter.check("private-peer")


@pytest.mark.asyncio
async def test_server_info_advertises_local_open_registration_and_actual_boundaries(client):
    response = await client.get("/user-service/v1/server-info?client_platform=app")
    assert response.status_code == 200
    info = response.json()
    assert info["schema_version"] == 1
    assert info["service"]["kind"] == "awiki-open-server"
    assert info["deployment"]["did_domain"] == "testserver"
    assert info["identity"]["handle_registration"] == {
        "enabled": True, "default_method": "phone", "availability": "open",
        "methods": [{"id": "phone", "enabled": True, "verification": {"required": False, "type": "none"}}],
    }
    assert info["identity"]["handle_recovery"] == {"enabled": False, "methods": []}
    assert info["identity"]["did_methods"] == [{"id": "wba", "create": True}, {"id": "web", "create": False}]
    assert all(not value["enabled"] for value in info["services"].values())
    assert all(not value["enabled"] for value in info["agents"].values())
    other = await client.get("/user-service/v1/server-info?registration_domain=other.example")
    assert other.json()["identity"]["handle_registration"]["enabled"] is False
