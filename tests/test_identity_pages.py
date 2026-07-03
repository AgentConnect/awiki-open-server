from __future__ import annotations

import pytest

from tests.conftest import rpc


@pytest.mark.asyncio
async def test_register_profile_and_page(client):
    reg = await rpc(client, "/did-auth/rpc", "register", {"handle": "alice", "display_name": "Alice"})
    result = reg["result"]
    token = result["token"]
    assert result["did"].startswith("did:wba:testserver")
    assert result["document"]["service"][0]["type"] == "ANPMessageService"
    assert result["document"]["service"][0]["serviceEndpoint"] == "http://testserver/anp-im/rpc"

    me = await rpc(client, "/did/profile/rpc", "get_me", token=token)
    assert me["result"]["display_name"] == "Alice"

    updated = await rpc(client, "/did/profile/rpc", "update_me", {"description": "hello"}, token=token)
    assert updated["result"]["description"] == "hello"

    page = await rpc(client, "/content/rpc", "create", {"slug": "intro", "title": "Intro", "body": "# Hello"}, token=token)
    assert page["result"]["slug"] == "intro"

    pages = await rpc(client, "/content/rpc", "list", token=token)
    assert pages["result"]["count"] == 1
    assert pages["result"]["pages"][0]["slug"] == "intro"

    public = await client.get("/content/intro.md")
    assert public.status_code == 200
    assert "# Hello" in public.text

    renamed = await rpc(client, "/content/rpc", "rename", {"old_slug": "intro", "new_slug": "about"}, token=token)
    assert renamed["result"]["slug"] == "about"

    resolved = await client.get("/dids/resolve/users/alice/did.json")
    assert resolved.status_code == 200
    assert resolved.json()["id"] == result["did"]

    doc = result["document"]
    doc["alsoKnownAs"] = ["alice-renamed@testserver"]
    updated_doc = await rpc(client, "/did-auth/rpc", "update_document", {"document": doc}, token=token)
    assert updated_doc["result"]["document"]["alsoKnownAs"] == ["alice-renamed@testserver"]

    verified = await rpc(client, "/did-auth/rpc", "verify_http_request", token=token)
    assert verified["result"]["did"] == result["did"]


@pytest.mark.asyncio
async def test_user_service_identity_compat_path_accepts_cli_did_document(client):
    did = "did:wba:testserver:cli-alice:e1_cli"
    document = {"id": did, "service": []}
    reg = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "cli-alice", "did_document": document})
    result = reg["result"]

    assert result["did"] == did
    assert result["handle"] == "cli-alice"
    assert result["domain"] == "testserver"
    assert result["full_handle"] == "cli-alice.testserver"
    assert result["access_token"] == result["token"]

    me = await rpc(client, "/user-service/did/profile/rpc", "get_me", token=result["access_token"])
    assert me["result"]["did"] == did

    by_handle = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "cli-alice.testserver"})
    assert by_handle["result"]["did"] == did
    assert by_handle["result"]["full_handle"] == "cli-alice.testserver"

    by_did = await rpc(client, "/user-service/handle/rpc", "lookup", {"did": did})
    assert by_did["result"]["handle"] == "cli-alice"

    otp = await rpc(client, "/handle/rpc", "send_otp", {"phone": "13800138000"})
    assert otp["error"]["message"] == "contact_verification_not_enabled"

    doc_update = await rpc(client, "/user-service/did-auth/rpc", "update_document", {"did_document": document}, token=result["token"])
    assert doc_update["result"]["did_document"]["id"] == did
    assert doc_update["result"]["did_document"]["service"][0]["type"] == "ANPMessageService"

    public_profile = await rpc(client, "/did/profile/rpc", "get_public_profile", {"did": did})
    assert public_profile["result"]["user_id"] == did
    assert public_profile["result"]["service_endpoints"][0]["type"] == "ANPMessageService"

    resolved = await client.get("/cli-alice/e1_cli/did.json")
    assert resolved.status_code == 200
    assert resolved.json()["id"] == did

    handle_doc = await client.get("/.well-known/handle/cli-alice")
    assert handle_doc.status_code == 200
    assert handle_doc.json()["handle"] == "cli-alice.testserver"
    assert handle_doc.json()["did"] == did
    assert handle_doc.json()["profile"]["type"] == "DIDSubjectProfile"

    by_did_doc = await client.get("/.well-known/handle/by-did", params={"did": did})
    assert by_did_doc.status_code == 200
    assert by_did_doc.json()["confirmed"] is True

    my_handle = await rpc(client, "/user-service/handle/rpc", "get_my_handle", token=result["access_token"])
    assert my_handle["result"]["full_handle"] == "cli-alice.testserver"

    my_handles = await rpc(client, "/user-service/handle/rpc", "get_my_handles", token=result["access_token"])
    assert my_handles["result"]["handles"][0]["did"] == did

    quota = await rpc(client, "/user-service/handle/rpc", "get_quota", token=result["access_token"])
    assert quota["result"]["community_edition"] is True


@pytest.mark.asyncio
async def test_signed_cli_did_document_service_is_not_rewritten(client):
    did = "did:wba:testserver:signed-cli:e1_cli"
    service = {
        "id": f"{did}#message",
        "type": "ANPMessageService",
        "profiles": ["anp.core.binding.v1", "anp.direct.base.v1", "anp.attachment.v1"],
        "serviceEndpoint": "http://testserver/anp-im/rpc",
        "serviceDid": "did:wba:testserver",
        "securityProfiles": ["transport-protected"],
    }
    document = {
        "id": did,
        "service": [service],
        "proof": {
            "type": "DataIntegrityProof",
            "created": "2026-07-03T00:00:00Z",
            "verificationMethod": f"{did}#key-1",
            "proofPurpose": "assertionMethod",
            "cryptosuite": "eddsa-jcs-2022",
            "proofValue": "test-proof-value",
        },
    }

    reg = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "signed-cli", "did_document": document})

    assert reg["result"]["document"]["service"] == [service]
    resolved = await client.get("/signed-cli/e1_cli/did.json")
    assert resolved.status_code == 200
    assert resolved.json()["service"] == [service]

    signed_without_service = {
        "id": "did:wba:testserver:signed-empty:e1_empty",
        "proof": document["proof"],
    }
    rejected = await rpc(
        client,
        "/user-service/did-auth/rpc",
        "register",
        {"handle": "signed-empty", "did_document": signed_without_service},
    )
    assert rejected["error"]["message"] == "signed_did_document_requires_anp_message_service"


@pytest.mark.asyncio
async def test_signed_cli_did_document_service_must_match_open_server(client):
    did = "did:wba:testserver:signed-mismatch:e1_cli"
    service = {
        "id": f"{did}#message",
        "type": "ANPMessageService",
        "profiles": ["anp.core.binding.v1", "anp.direct.base.v1"],
        "serviceEndpoint": "http://testserver/anp-im/rpc",
        "serviceDid": "did:wba:testserver",
        "securityProfiles": ["transport-protected"],
    }
    proof = {
        "type": "DataIntegrityProof",
        "created": "2026-07-03T00:00:00Z",
        "verificationMethod": f"{did}#key-1",
        "proofPurpose": "assertionMethod",
        "cryptosuite": "eddsa-jcs-2022",
        "proofValue": "test-proof-value",
    }

    wrong_endpoint = await rpc(
        client,
        "/user-service/did-auth/rpc",
        "register",
        {
            "handle": "signed-wrong-endpoint",
            "did_document": {
                "id": did,
                "service": [{**service, "serviceEndpoint": "https://wrong.example/anp-im/rpc"}],
                "proof": proof,
            },
        },
    )
    assert wrong_endpoint["error"]["message"] == "signed_did_document_service_endpoint_mismatch"

    wrong_service_did = await rpc(
        client,
        "/user-service/did-auth/rpc",
        "register",
        {
            "handle": "signed-wrong-service-did",
            "did_document": {
                "id": did,
                "service": [{**service, "serviceDid": "did:wba:wrong.example"}],
                "proof": proof,
            },
        },
    )
    assert wrong_service_did["error"]["message"] == "signed_did_document_service_did_mismatch"

    multiple_services = await rpc(
        client,
        "/user-service/did-auth/rpc",
        "register",
        {
            "handle": "signed-many-services",
            "did_document": {
                "id": did,
                "service": [service, {**service, "id": f"{did}#message-2"}],
                "proof": proof,
            },
        },
    )
    assert multiple_services["error"]["message"] == "signed_did_document_requires_single_anp_message_service"


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
    assert dev_login.json()["did"] == "did:wba:testserver:users:13800138001"

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

    refreshed = await client.post("/user-service/auth/token-refresh", json={"refresh_token": token})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] == token

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
    assert logged_in["result"]["access_token"] == token
    assert logged_in["result"]["refresh_token"] == token
    assert logged_in["result"]["token_type"] == "Bearer"
    assert logged_in["result"]["did"] == did
    assert logged_in["result"]["user_id"] == did

    refreshed = await rpc(client, "/user-service/did-verify/rpc", "refresh", {"refresh_token": token})
    assert refreshed["result"]["access_token"] == token
    assert refreshed["result"]["refresh_token"] == token
    assert refreshed["result"]["refreshed"] is True

    wrong_code = await rpc(client, "/did-verify/rpc", "login", {"did": did, "code": "123456"})
    assert wrong_code["error"]["message"] == "invalid_code"

    missing_did = await rpc(
        client,
        "/user-service/did-verify/rpc",
        "login",
        {"did": "did:wba:testserver:users:missing", "code": "666666"},
    )
    assert missing_did["error"]["message"] == "did_not_found"

    bad_refresh = await rpc(client, "/did-verify/rpc", "refresh", {"refresh_token": "not-a-token"})
    assert bad_refresh["error"]["message"] == "invalid_refresh_token"


@pytest.mark.asyncio
async def test_did_auth_revoke_marks_did_inactive_and_blocks_auth_paths(client):
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "revoked-user"})
    token = registered["result"]["token"]
    did = registered["result"]["did"]
    document = registered["result"]["document"]

    verified = await rpc(client, "/did-auth/rpc", "verify", token=token)
    assert verified["result"]["active"] is True
    assert verified["result"]["did"] == did

    did_token_me = await rpc(client, "/did/profile/rpc", "get_me", token=did)
    assert did_token_me["result"]["did"] == did

    revoke_result = await rpc(client, "/user-service/did-auth/rpc", "revoke", token=token)
    assert revoke_result["result"]["ok"] is True
    assert revoke_result["result"]["revoked"] is True
    assert revoke_result["result"]["status"] == "revoked"
    assert revoke_result["result"]["did"] == did
    assert revoke_result["result"]["revoked_at"]

    verify_after = await rpc(client, "/did-auth/rpc", "verify", token=token)
    assert verify_after["error"]["message"] == "invalid_bearer_token"

    did_token_after = await rpc(client, "/did/profile/rpc", "get_me", token=did)
    assert did_token_after["error"]["message"] == "invalid_bearer_token"

    get_me_after = await rpc(client, "/did-auth/rpc", "get_me", token=token)
    assert get_me_after["error"]["message"] == "invalid_bearer_token"

    document["alsoKnownAs"] = ["revoked-user@testserver"]
    update_after = await rpc(client, "/did-auth/rpc", "update_document", {"document": document}, token=token)
    assert update_after["error"]["message"] == "invalid_bearer_token"

    token_verify = await client.get("/user-service/auth/token-verify", headers={"Authorization": f"Bearer {token}"})
    assert token_verify.status_code == 401
    assert token_verify.json()["detail"] == "invalid_token"

    token_refresh = await client.post("/user-service/auth/token-refresh", json={"refresh_token": token})
    assert token_refresh.status_code == 401
    assert token_refresh.json()["detail"] == "invalid_token"

    ticket = await client.post("/user-service/ws/tickets", headers={"Authorization": f"Bearer {token}"})
    assert ticket.status_code == 401
    assert ticket.json()["detail"] == "invalid_token"

    did_verify_login = await rpc(client, "/did-verify/rpc", "login", {"did": did, "code": "666666"})
    assert did_verify_login["error"]["message"] == "did_not_found"

    did_verify_refresh = await rpc(client, "/user-service/did-verify/rpc", "refresh", {"refresh_token": token})
    assert did_verify_refresh["error"]["message"] == "invalid_refresh_token"

    resolved = await client.get("/dids/resolve/users/revoked-user/did.json")
    assert resolved.status_code == 404

    handle_lookup = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "revoked-user.testserver"})
    assert handle_lookup["error"]["message"] == "handle_not_found"

    handle_doc = await client.get("/.well-known/handle/revoked-user")
    assert handle_doc.status_code == 404

    public_profile = await rpc(client, "/did/profile/rpc", "get_public_profile", {"did": did})
    assert public_profile["result"]["did"] == did
    assert public_profile["result"]["did_document"] == {}


@pytest.mark.asyncio
async def test_legacy_me_profile_and_message_health_compat_routes(client):
    registered = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {
            "handle": "legacy-profile",
            "display_name": "Legacy Profile",
            "profile_md": "# Legacy Profile\n\nInitial profile.",
        },
    )
    token = registered["result"]["token"]
    did = registered["result"]["did"]

    im_health = await client.get("/im/healthz")
    assert im_health.status_code == 200
    assert im_health.json()["status"] == "ok"

    missing_auth = await client.get("/me")
    assert missing_auth.status_code == 401

    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user_id"] == did
    assert me.json()["nick_name"] == "Legacy Profile"
    assert me.json()["handle"] == "legacy-profile.testserver"

    updated = await client.patch(
        "/user-service/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "nick_name": "Legacy Updated",
            "avatar_url": "https://example.test/avatar.png",
            "bio": "Updated bio",
            "profile_md": "# Updated\n\nMarkdown body.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["nick_name"] == "Legacy Updated"
    assert updated.json()["avatar_url"] == "https://example.test/avatar.png"
    assert updated.json()["bio"] == "Updated bio"

    rpc_me = await rpc(client, "/me/rpc", "get_me", token=token)
    assert rpc_me["result"]["user_id"] == did
    assert rpc_me["result"]["profile_md"].startswith("# Updated")

    rpc_public = await rpc(client, "/me/rpc", "get_public_profile", {"user_id": did})
    assert rpc_public["result"]["user_id"] == did
    assert rpc_public["result"]["nick_name"] == "Legacy Updated"
    assert "phone" not in rpc_public["result"]

    public_rest = await client.get(f"/users/{did}/profile")
    assert public_rest.status_code == 200
    assert public_rest.json()["user_id"] == did
    assert public_rest.json()["profile_md"].startswith("# Updated")

    public_rest_compat = await client.get(f"/user-service/users/{did}/profile")
    assert public_rest_compat.status_code == 200
    assert public_rest_compat.json()["nick_name"] == "Legacy Updated"

    markdown = await client.get(f"/profiles/{did}")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "# Legacy Updated" in markdown.text
    assert "# Updated" in markdown.text
    assert f"DID: `{did}`" in markdown.text

    markdown_compat = await client.get(f"/user-service/profiles/{did}")
    assert markdown_compat.status_code == 200
    assert "legacy-profile.testserver" in markdown_compat.text

    missing_markdown = await client.get("/profiles/did:wba:testserver:users:missing")
    assert missing_markdown.status_code == 404

    deleted = await rpc(client, "/me/rpc", "delete_me", token=token)
    assert deleted["error"]["message"] == "not_supported"


@pytest.mark.asyncio
async def test_agent_registration_and_message_agent_minimal_compat(client):
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "agent-owner"})
    owner_token = registered["result"]["token"]
    owner_did = registered["result"]["did"]

    issued = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "issue_token",
        {"agent_kind": "daemon", "ttl_seconds": 600},
        token=owner_token,
    )
    token = issued["result"]["token"]
    assert issued["result"]["owner_did"] == owner_did
    assert issued["result"]["one_time"] is True

    verified = await rpc(client, "/user-service/agent-registration/rpc", "verify_token", {"token": token})
    assert verified["result"]["active"] is True
    assert verified["result"]["status"] == "active"

    exchanged = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "exchange_token",
        {"token": token, "agent_did": f"{owner_did}:agents:daemon"},
    )
    assert exchanged["result"]["exchanged"] is True
    assert exchanged["result"]["agent_did"].endswith(":agents:daemon")

    used = await rpc(client, "/user-service/agent-registration/rpc", "verify_token", {"token": token})
    assert used["result"]["active"] is False
    assert used["result"]["status"] == "used"

    second = await rpc(client, "/user-service/agent-registration/rpc", "issue_token", token=owner_token)
    revoked = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "revoke_token",
        {"token": second["result"]["token"]},
    )
    assert revoked["result"]["status"] == "revoked"

    ensured = await rpc(
        client,
        "/user-service/message-agent/rpc",
        "ensure_binding",
        {
            "human_did": owner_did,
            "daemon_did": f"{owner_did}:agents:daemon",
            "runtime_agent_did": f"{owner_did}:agents:runtime",
        },
        token=owner_token,
    )
    binding_id = ensured["result"]["binding_id"]
    assert ensured["result"]["status"] == "active"

    active = await rpc(client, "/user-service/message-agent/rpc", "get_active_binding", token=owner_token)
    assert active["result"]["binding_id"] == binding_id

    listed = await rpc(client, "/user-service/message-agent/rpc", "list_bindings", token=owner_token)
    assert listed["result"]["count"] == 1

    seen = await rpc(client, "/user-service/message-agent/rpc", "mark_seen", {"binding_id": binding_id})
    assert seen["result"]["seen"] is True
    assert seen["result"]["binding"]["last_seen_at"]

    disabled = await rpc(client, "/user-service/message-agent/rpc", "disable_binding", {"binding_id": binding_id})
    assert disabled["result"]["status"] == "disabled"

    active_missing = await rpc(client, "/user-service/message-agent/rpc", "get_active_binding", token=owner_token)
    assert active_missing["error"]["message"] == "active_binding_not_found"

    revoked_binding = await rpc(client, "/user-service/message-agent/rpc", "revoke_binding", {"binding_id": binding_id})
    assert revoked_binding["result"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_users_rpc_compat_routes(client):
    alice = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {
            "handle": "users-alice",
            "display_name": "Users Alice",
            "description": "Alice bio",
            "avatar_uri": "https://example.test/alice.png",
            "profile_md": "# Users Alice",
        },
    )
    bob = await rpc(client, "/did-auth/rpc", "register", {"handle": "users-bob", "display_name": "Users Bob"})
    alice_token = alice["result"]["token"]
    alice_did = alice["result"]["did"]
    bob_did = bob["result"]["did"]

    me = await rpc(client, "/users/rpc", "get_me", token=alice_token)
    assert me["result"]["did"] == alice_did
    assert me["result"]["user_name"] == "users-alice"
    assert me["result"]["nick_name"] == "Users Alice"
    assert me["result"]["display_name"] == "Users Alice"
    assert me["result"]["avatar_uri"] == "https://example.test/alice.png"
    assert me["result"]["bio"] == "Alice bio"
    assert me["result"]["description"] == "Alice bio"
    assert me["result"]["subject_type"] == "human"
    assert me["result"]["tags"] == []
    assert me["result"]["profile_md"] == "# Users Alice"
    assert me["result"]["profile_uri"].endswith(f"/profiles/{alice_did}")
    assert me["result"]["created_at"]
    assert me["result"]["handle"] == "users-alice"
    assert me["result"]["handle_domain"] == "testserver"

    by_did = await rpc(client, "/user-service/users/rpc", "get_by_did", {"did": bob_did}, token=alice_token)
    assert by_did["result"]["did"] == bob_did
    assert by_did["result"]["handle"] == "users-bob"

    by_dids = await rpc(
        client,
        "/users/rpc",
        "get_by_dids",
        {"dids": [alice_did, "did:wba:testserver:users:missing", bob_did]},
        token=alice_token,
    )
    assert [item["did"] for item in by_dids["result"]["users"]] == [alice_did, bob_did]

    by_handle = await rpc(
        client,
        "/user-service/users/rpc",
        "get_by_handle",
        {"handle": "users-alice.testserver"},
        token=alice_token,
    )
    assert by_handle["result"]["did"] == alice_did

    by_local_handle = await rpc(
        client,
        "/users/rpc",
        "get_by_handle",
        {"handle": "users-bob", "domain": "testserver"},
        token=alice_token,
    )
    assert by_local_handle["result"]["did"] == bob_did

    missing = await rpc(client, "/users/rpc", "get_by_did", {"did": "did:wba:testserver:users:nope"}, token=alice_token)
    assert missing["error"]["message"] == "profile_not_found"


@pytest.mark.asyncio
async def test_agent_inventory_minimal_compat_routes(client):
    owner = await rpc(client, "/did-auth/rpc", "register", {"handle": "inventory-owner", "display_name": "Inventory Owner"})
    sender = await rpc(client, "/did-auth/rpc", "register", {"handle": "inventory-sender", "display_name": "Inventory Sender"})
    owner_token = owner["result"]["token"]
    owner_did = owner["result"]["did"]
    sender_did = sender["result"]["did"]
    daemon_did = f"{owner_did}:agents:daemon"
    runtime_did = f"{owner_did}:agents:runtime"

    await rpc(
        client,
        "/user-service/message-agent/rpc",
        "ensure_binding",
        {
            "human_did": owner_did,
            "daemon_did": daemon_did,
            "runtime_agent_did": runtime_did,
        },
        token=owner_token,
    )

    status = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_latest_status",
        {
            "daemon_agent_did": daemon_did,
            "statuses": [
                {
                    "agent_did": runtime_did,
                    "agent_kind": "runtime",
                    "status": "online",
                    "version": "0.1.0",
                    "needs_upgrade": False,
                    "needs_config": False,
                    "diagnostics_summary": {"ok": True},
                }
            ],
        },
    )
    assert status["result"]["updated"][0]["agent_did"] == runtime_did
    assert status["result"]["updated"][0]["controller_did"] == owner_did

    scope = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "sync_controller_scope",
        {"daemon_agent_did": daemon_did},
    )
    assert scope["result"]["controller_user_id"] == owner_did
    assert scope["result"]["controller_did"] == owner_did
    assert scope["result"]["controller_full_handle"] == "inventory-owner.testserver"
    assert scope["result"]["updated_count"] >= 1

    verified = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "verify_controller_sender",
        {"daemon_agent_did": daemon_did, "sender_did": owner_did},
    )
    assert verified["result"]["sender_did"] == owner_did
    assert verified["result"]["controller_did"] == owner_did

    allowed = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "authorize_agent_invocation",
        {"daemon_agent_did": daemon_did, "agent_did": runtime_did, "sender_did": sender_did},
    )
    assert allowed["result"]["allowed"] is True
    assert allowed["result"]["reason"] == "allowed"
    assert allowed["result"]["agent_did"] == runtime_did
    assert allowed["result"]["sender_did"] == sender_did
    assert allowed["result"]["sender_user_id"] == sender_did
    assert allowed["result"]["sender_full_handle"] == "inventory-sender.testserver"
    assert allowed["result"]["active_mode"] == "known_local_user"

    listed = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", token=owner_token)
    assert listed["result"]["count"] == 1
    assert listed["result"]["agents"][0]["agent_did"] == runtime_did
    assert listed["result"]["agents"][0]["latest_status"]["version"] == "0.1.0"

    renamed = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_display_name",
        {"agent_did": runtime_did, "display_name": "Runtime Agent"},
        token=owner_token,
    )
    assert renamed["result"]["agent"]["display_name"] == "Runtime Agent"

    policy = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_invocation_policy",
        {"agent_did": runtime_did, "active_mode": "controller_only", "whitelist_handles": ["inventory-owner.testserver"]},
        token=owner_token,
    )
    assert policy["result"]["active_mode"] == "controller_only"
    assert policy["result"]["whitelist_handles"] == ["inventory-owner.testserver"]

    fetched_policy = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "get_invocation_policy",
        {"agent_did": runtime_did},
        token=owner_token,
    )
    assert fetched_policy["result"]["active_mode"] == "controller_only"

    archived = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "archive_agent",
        {"daemon_agent_did": daemon_did, "agent_did": runtime_did},
    )
    assert archived["result"]["archived"][0]["agent_did"] == runtime_did
    assert archived["result"]["archived"][0]["status"] == "archived"

    active_list = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", token=owner_token)
    assert active_list["result"]["count"] == 0

    inactive_list = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", {"include_inactive": True}, token=owner_token)
    assert inactive_list["result"]["count"] == 1


@pytest.mark.asyncio
async def test_did_relationship_phone_bind_and_site_rpc_compat(contact_verification_compat_client):
    client = contact_verification_compat_client
    alice = await rpc(client, "/did-auth/rpc", "register", {"handle": "rel-alice"})
    bob = await rpc(client, "/did-auth/rpc", "register", {"handle": "rel-bob"})
    alice_token = alice["result"]["token"]
    bob_token = bob["result"]["token"]
    alice_did = alice["result"]["did"]
    bob_did = bob["result"]["did"]

    bind_send = await client.post(
        "/user-service/auth/phone-bind-send",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000"},
    )
    assert bind_send.status_code == 200
    assert bind_send.json()["message"] == "Code sent."
    assert bind_send.json()["dev_otp"] == "123456"

    bind_verify = await client.post(
        "/user-service/auth/phone-bind-verify",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000", "code": "123456"},
    )
    assert bind_verify.status_code == 200
    assert bind_verify.json()["success"] is True
    assert bind_verify.json()["did"] == alice_did

    bad_bind = await client.post(
        "/auth/phone-bind-verify",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000", "code": "000000"},
    )
    assert bad_bind.status_code == 401

    followed = await rpc(
        client,
        "/user-service/did/relationships/rpc",
        "follow",
        {"target_did": bob_did},
        token=alice_token,
    )
    assert followed["result"]["is_friend"] is False

    status = await rpc(
        client,
        "/user-service/did/relationships/rpc",
        "get_status",
        {"target_did": bob_did},
        token=alice_token,
    )
    assert status["result"]["is_following"] is True
    assert status["result"]["is_follower"] is False
    assert status["result"]["is_friend"] is False

    following = await rpc(client, "/did/relationships/rpc", "get_following", {"limit": 10, "offset": 0}, token=alice_token)
    assert following["result"]["items"][0]["from_did"] == alice_did
    assert following["result"]["items"][0]["to_did"] == bob_did
    assert following["result"]["items"][0]["from_user_id"] == alice_did

    followers = await rpc(client, "/user-service/did/relationships/rpc", "get_followers", token=bob_token)
    assert followers["result"]["items"][0]["from_did"] == alice_did
    assert followers["result"]["items"][0]["to_did"] == bob_did

    reciprocal = await rpc(client, "/did/relationships/rpc", "follow", {"target_did": alice_did}, token=bob_token)
    assert reciprocal["result"]["is_friend"] is True

    friend_status = await rpc(client, "/did/relationships/rpc", "get_status", {"target_did": bob_did}, token=alice_token)
    assert friend_status["result"]["is_friend"] is True
    assert friend_status["result"]["is_blocked"] is False

    self_follow = await rpc(client, "/did/relationships/rpc", "follow", {"target_did": alice_did}, token=alice_token)
    assert self_follow["error"]["message"] == "cannot_follow_self"

    external_follow = await rpc(
        client,
        "/did/relationships/rpc",
        "follow",
        {"target_did": "did:wba:awiki.info:users:remote"},
        token=alice_token,
    )
    assert external_follow["error"]["message"] == "target_did_domain_mismatch"

    unfollow = await rpc(client, "/did/relationships/rpc", "unfollow", {"target_did": bob_did}, token=alice_token)
    assert unfollow["result"]["ok"] is True

    root = await rpc(client, "/site/rpc", "get_root", {"domain": "testserver"}, token=alice_token)
    assert root["result"]["kind"] == "root"
    assert root["result"]["domain"] == "testserver"
    assert "Welcome to testserver" in root["result"]["body"]

    updated_root = await rpc(client, "/site/rpc", "set_root", {"domain": "testserver", "body": "# Test Site"}, token=alice_token)
    assert updated_root["result"]["body"] == "# Test Site"

    public_root = await client.get("/")
    assert public_root.status_code == 200
    assert public_root.headers["content-type"].startswith("text/markdown")
    assert public_root.text == "# Test Site"

    created_page = await rpc(
        client,
        "/site/rpc",
        "create_page",
        {"domain": "testserver", "slug": "About-Us", "body": "# About"},
        token=alice_token,
    )
    assert created_page["result"]["slug"] == "about-us"
    assert created_page["result"]["url"] == "https://testserver/pages/about-us.md"

    listed_pages = await rpc(client, "/site/rpc", "list_pages", {"domain": "testserver"}, token=alice_token)
    assert listed_pages["result"]["count"] == 1
    assert listed_pages["result"]["pages"][0]["slug"] == "about-us"
    assert "body" not in listed_pages["result"]["pages"][0]

    public_page = await client.get("/pages/about-us.md")
    assert public_page.status_code == 200
    assert public_page.text == "# About"

    renamed_page = await rpc(
        client,
        "/site/rpc",
        "rename_page",
        {"domain": "testserver", "old_slug": "about-us", "new_slug": "team"},
        token=alice_token,
    )
    assert renamed_page["result"]["slug"] == "team"

    updated_page = await rpc(
        client,
        "/site/rpc",
        "update_page",
        {"domain": "testserver", "slug": "team", "body": "# Team"},
        token=alice_token,
    )
    assert updated_page["result"]["body"] == "# Team"

    fetched_page = await rpc(client, "/site/rpc", "get_page", {"domain": "testserver", "slug": "team"}, token=alice_token)
    assert fetched_page["result"]["body"] == "# Team"

    deleted_page = await rpc(client, "/site/rpc", "delete_page", {"domain": "testserver", "slug": "team"}, token=alice_token)
    assert deleted_page["result"]["ok"] is True

    missing_page = await client.get("/pages/team.md")
    assert missing_page.status_code == 404

    foreign_site = await rpc(client, "/site/rpc", "get_root", {"domain": "awiki.info"}, token=alice_token)
    assert foreign_site["error"]["message"] == "site_domain_not_managed_by_this_server"


@pytest.mark.asyncio
async def test_cli_did_document_message_service_is_rehomed_to_open_server(client):
    did = "did:wba:testserver:cli-service:e1_cli"
    uploaded = {
        "id": did,
        "service": [
            {
                "id": "#message",
                "type": "ANPMessageService",
                "serviceEndpoint": "https://wrong.example/anp-im/rpc",
                "serviceDid": "did:wba:wrong.example",
                "profiles": ["anp.direct.base.v1"],
                "securityProfiles": ["transport-protected"],
            }
        ],
    }
    registered = await rpc(client, "/user-service/did-auth/rpc", "register", {"handle": "cli-service", "did_document": uploaded})
    service = registered["result"]["document"]["service"][0]
    assert service["serviceEndpoint"] == "http://testserver/anp-im/rpc"
    assert service["serviceDid"] == "did:wba:testserver"
    assert "anp.group.base.v1" in service["profiles"]

    uploaded["service"][0]["serviceEndpoint"] = "https://still-wrong.example/anp-im/rpc"
    updated = await rpc(client, "/user-service/did-auth/rpc", "update_document", {"did_document": uploaded}, token=registered["result"]["token"])
    service = updated["result"]["did_document"]["service"][0]
    assert service["serviceEndpoint"] == "http://testserver/anp-im/rpc"
    assert service["serviceDid"] == "did:wba:testserver"


@pytest.mark.asyncio
async def test_unsupported_identity_methods(client):
    reg = await rpc(client, "/did-auth/rpc", "register", {"handle": "bob"})
    response = await rpc(client, "/did-auth/rpc", "recover_handle", token=reg["result"]["token"])
    assert response["error"]["message"] == "not_supported"
