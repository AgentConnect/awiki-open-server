from __future__ import annotations

import httpx
import pytest

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem
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

    resolved = await client.get("/dids/resolve/users/alice/e1_default/did.json")
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
async def test_did_registration_policy_rejects_non_e1_domain_conflicts_and_public_unsigned_doc(client, tmp_path):
    non_e1 = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {"handle": "policy-non-e1", "did_document": {"id": "did:wba:testserver:users:policy-non-e1", "service": []}},
    )
    assert non_e1["error"]["message"] == "did_e1_required"

    domain_mismatch = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {"handle": "policy-domain", "did_document": {"id": "did:wba:other.example:users:policy:e1_default", "service": []}},
    )
    assert domain_mismatch["error"]["message"] == "did_domain_mismatch"

    k1_input = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {"handle": "policy-k1", "did_document": {"id": "did:wba:testserver:users:policy:k1_main", "service": []}},
    )
    assert k1_input["error"]["message"] == "did_e1_required"

    first = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {"handle": "policy-ok", "did_document": {"id": "did:wba:testserver:users:policy-ok:e1_default", "service": []}},
    )
    duplicate_handle = await rpc(client, "/did-auth/rpc", "register", {"handle": "policy-ok"})
    assert duplicate_handle["error"]["message"] == "handle_already_registered"
    assert duplicate_handle["error"]["data"]["handle"] == "policy-ok@testserver"

    duplicate_did = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {"handle": "policy-other", "did_document": {"id": first["result"]["did"], "service": []}},
    )
    assert duplicate_did["error"]["message"] == "did_already_registered"

    strict_app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=False,
        )
    )
    transport = httpx.ASGITransport(app=strict_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as strict_client:
        unsigned = await rpc(
            strict_client,
            "/did-auth/rpc",
            "register",
            {"handle": "strict-unsigned", "did_document": {"id": "did:wba:testserver:users:strict-unsigned:e1_default", "service": []}},
        )
        assert unsigned["error"]["message"] == "unsigned_did_document_requires_dev_mode"

        generated = await rpc(strict_client, "/did-auth/rpc", "register", {"handle": "strict-generated"})
        assert generated["result"]["did"] == "did:wba:testserver:users:strict-generated:e1_default"


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
        "proof": {**document["proof"], "verificationMethod": "did:wba:testserver:signed-empty:e1_empty#key-1"},
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
async def test_token_lifecycle_expires_rotates_and_rejects_stale_refresh(tmp_path):
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
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as token_client:
        registered = await rpc(token_client, "/did-auth/rpc", "register", {"handle": "token-life"})
        did = registered["result"]["did"]
        token = registered["result"]["token"]
        refresh_token = registered["result"]["refresh_token"]

        access_as_refresh = await token_client.post("/user-service/auth/token-refresh", json={"refresh_token": token})
        assert access_as_refresh.status_code == 401

        with app.state.store.connect() as conn:
            conn.execute(
                "UPDATE users SET access_expires_at = ? WHERE did = ?",
                ("2000-01-01T00:00:00+00:00", did),
            )

        expired_verify = await rpc(token_client, "/did-auth/rpc", "verify", token=token)
        assert expired_verify["error"]["message"] == "invalid_bearer_token"
        token_verify = await token_client.get("/user-service/auth/token-verify", headers={"Authorization": f"Bearer {token}"})
        assert token_verify.status_code == 401
        assert token_verify.json()["detail"] == "invalid_token"

        refreshed = await token_client.post("/user-service/auth/token-refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 200
        new_token = refreshed.json()["access_token"]
        new_refresh = refreshed.json()["refresh_token"]
        assert new_token != token
        assert new_refresh != refresh_token

        old_refresh = await token_client.post("/user-service/auth/token-refresh", json={"refresh_token": refresh_token})
        assert old_refresh.status_code == 401

        verify_new = await rpc(token_client, "/did-auth/rpc", "verify", token=new_token)
        assert verify_new["result"]["did"] == did

        with app.state.store.connect() as conn:
            conn.execute(
                "UPDATE users SET refresh_expires_at = ? WHERE did = ?",
                ("2000-01-01T00:00:00+00:00", did),
            )
        expired_refresh = await token_client.post("/user-service/auth/token-refresh", json={"refresh_token": new_refresh})
        assert expired_refresh.status_code == 401
        assert expired_refresh.json()["detail"] == "invalid_token"

        legacy = await rpc(token_client, "/did-auth/rpc", "register", {"handle": "legacy-token-life"})
        legacy_token = legacy["result"]["token"]
        legacy_did = legacy["result"]["did"]
        with app.state.store.connect() as conn:
            conn.execute(
                "UPDATE users SET refresh_token = NULL, refresh_expires_at = NULL WHERE did = ?",
                (legacy_did,),
            )
        legacy_refresh = await token_client.post("/user-service/auth/token-refresh", json={"refresh_token": legacy_token})
        assert legacy_refresh.status_code == 200
        assert legacy_refresh.json()["did"] == legacy_did
        assert legacy_refresh.json()["access_token"] != legacy_token


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

    resolved = await client.get("/dids/resolve/users/revoked-user/e1_default/did.json")
    assert resolved.status_code == 404

    handle_lookup = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "revoked-user.testserver"})
    assert handle_lookup["error"]["message"] == "handle_not_found"

    handle_doc = await client.get("/.well-known/handle/revoked-user")
    assert handle_doc.status_code == 404

    public_profile = await rpc(client, "/did/profile/rpc", "get_public_profile", {"did": did})
    assert public_profile["result"]["did"] == did
    assert public_profile["result"]["did_document"] == {}


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
