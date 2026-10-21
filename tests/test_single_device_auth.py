from __future__ import annotations

import asyncio
import base64
import copy
import json
from pathlib import Path

import httpx
import pytest

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.protocol.anp_adapter import generate_service_http_signature_headers
from awiki_open_server.user_compat import core as user_core
from tests.helpers import sign_did_document, single_device_document


AUTH_PATH = "/user-service/v1/did-auth/rpc"
DID = "did:wba:testserver:users:device-auth:e1_fixture"


def setup_app(tmp_path, *, dev=False):
    settings = Settings(
        data_dir=tmp_path, public_base_url="http://testserver",
        service_did="did:wba:testserver", did_domain="testserver", allow_unsigned_peer_dev=dev,
    )
    return create_app(settings), settings


def document_keys(*, root_key=None):
    root, signing, document = single_device_document(DID, root_key=root_key)
    document["service"][0].update(serviceEndpoint="http://testserver/anp-im/rpc", serviceDid="did:wba:testserver")
    return root, signing, document


async def call(client, method, params=None, *, token=None):
    return await client.post(AUTH_PATH, json={"jsonrpc": "2.0", "id": "auth-test", "method": method, "params": params or {}},
                             headers={"Authorization": f"Bearer {token}"} if token else {})


async def register_device(client, root, document):
    signed = sign_did_document(document, root)
    response = await call(client, "register", {"handle": "device-auth", "did_document": signed})
    assert response.status_code == 200
    if "error" in response.json():
        pytest.fail("valid single-device registration failed")
    require_same_token(response.headers.get("authorization"), f"Bearer {response.json()['result']['access_token']}")
    return response.json()["result"], signed


def signature_request(document, key, keyid):
    raw = json.dumps({"jsonrpc": "2.0", "id": "renewal", "method": "get_me", "params": {}}, separators=(",", ":")).encode()
    headers = generate_service_http_signature_headers(
        did_document=document, request_url=f"http://testserver{AUTH_PATH}", request_method="POST",
        headers={"Content-Type": "application/json"}, body=raw, keyid=keyid,
        sign_callback=lambda value, _keyid: key.sign(value),
    )
    return raw, {"Content-Type": "application/json", **headers}


async def signed_me(client, document, key, keyid, *, token=None):
    raw, headers = signature_request(document, key, keyid)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(AUTH_PATH, content=raw, headers=headers)


def claims(token):
    value = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def account_state(app):
    with app.state.store.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM single_device_accounts ORDER BY owner_did")]


def require_same_token(left, right):
    if left != right:
        pytest.fail("response header/body token mismatch")


@pytest.mark.asyncio
async def test_device_registration_expiration_app_restart_and_signed_renewal(tmp_path, monkeypatch):
    app, settings = setup_app(tmp_path)
    root, device_key, document = document_keys()
    did = document["id"]
    monkeypatch.setattr(user_core, "ACCESS_TOKEN_TTL_SECONDS", 2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registration, document = await register_device(client, root, document)
        token = registration["access_token"]
        initial_claims = claims(token)
        template = (Path(__file__).parent / "fixtures/community-device-access-v1.json").read_text()
        expected_claims = json.loads(template.replace("$DID", did).replace("$ACCOUNT_ID", registration["user_id"]))["claims"]
        assert {key: value for key, value in initial_claims.items() if key not in {"iat", "nbf", "exp", "jti"}} == expected_claims
        assert initial_claims["key_id"] == f"{did}#device-primary-sign"
        assert initial_claims["user_id"] == registration["user_id"]
        assert initial_claims["scopes"] == ["device:manage", "device:read", "message:connect"]
        fresh = await call(client, "get_me", token=token)
        assert fresh.status_code == 200
        assert fresh.json()["result"]["user_id"] == registration["user_id"]
        assert "access_token" not in fresh.json()["result"]
        assert "authorization" not in fresh.headers
        before = account_state(app)
        await asyncio.sleep(2.1)
        assert (await call(client, "get_me", token=token)).status_code == 401

    restarted = create_app(settings)
    assert (tmp_path / "auth-token-key.pem").stat().st_mode & 0o777 == 0o600
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver") as client:
        monkeypatch.setattr(user_core, "ACCESS_TOKEN_TTL_SECONDS", 3600)
        renewal = await signed_me(client, document, device_key, f"{did}#device-primary-sign")
        assert renewal.status_code == 200
        if "error" in renewal.json():
            pytest.fail("valid signed device renewal failed")
        renewed = renewal.json()["result"]["access_token"]
        require_same_token(renewal.headers.get("authorization"), f"Bearer {renewed}")
        renewed_claims = claims(renewed)
        for field in ("sub", "did", "user_id", "device_id", "key_id", "auth_generation", "scopes"):
            assert renewed_claims[field] == initial_claims[field]
        assert account_state(restarted) == before
        assert (await call(client, "get_me", token=renewed)).status_code == 200
        assert (await call(client, "get_me", token=token)).status_code == 401


@pytest.mark.asyncio
async def test_root_signature_and_literal_did_cannot_issue_device_tokens(tmp_path):
    app, _ = setup_app(tmp_path, dev=True)
    root, device_key, document = document_keys()
    did = document["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, document = await register_device(client, root, document)
        before = account_state(app)
        denied = await signed_me(client, document, root, f"{did}#key-1")
        assert denied.status_code == 403
        assert denied.json()["error"]["message"] == "device_signature_required"
        assert "authorization" not in denied.headers
        assert (await call(client, "get_me", token=did)).status_code == 401
        invalid_bearer = await signed_me(client, document, device_key, f"{did}#device-primary-sign", token="invalid-fixture-token")
        assert invalid_bearer.status_code == 401
        assert "authorization" not in invalid_bearer.headers
        assert account_state(app) == before
        assert (await call(client, "get_me", token=registered["access_token"])).status_code == 200
        empty_bearer = await signed_me(client, document, device_key, f"{did}#device-primary-sign", token="")
        assert empty_bearer.status_code == 401
        assert "authorization" not in empty_bearer.headers


@pytest.mark.parametrize("variant", ["null", "missing_type", "empty", "second_device", "root_as_device", "missing_authentication", "duplicate_key", "root_key_alias", "private_material", "wrong_e1_binding"])
@pytest.mark.asyncio
async def test_invalid_manifest_never_falls_back_to_legacy_registration(tmp_path, variant):
    app, _ = setup_app(tmp_path)
    root, _, document = document_keys()
    did = document["id"]
    if variant == "null":
        document["deviceManifest"] = None
    elif variant == "missing_type":
        del document["deviceManifest"]["type"]
    elif variant == "empty":
        document["deviceManifest"]["devices"] = []
    elif variant == "second_device":
        second = copy.deepcopy(document["deviceManifest"]["devices"][0])
        second["device_id"] = "second-device"
        document["deviceManifest"]["devices"].append(second)
    elif variant == "root_as_device":
        document["deviceManifest"]["devices"][0]["signing_key_id"] = f"{did}#key-1"
    elif variant == "missing_authentication":
        document["authentication"] = [f"{did}#key-1"]
    elif variant == "duplicate_key":
        document["verificationMethod"].append(copy.deepcopy(document["verificationMethod"][1]))
    elif variant == "root_key_alias":
        document["verificationMethod"][1]["publicKeyMultibase"] = document["verificationMethod"][0]["publicKeyMultibase"]
    elif variant == "private_material":
        document["verificationMethod"].append({
            "id": f"{did}#extra", "type": "JsonWebKey2020", "controller": did,
            "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "d": "invalid-test-private-material"},
        })
    else:
        document = json.loads(json.dumps(document).replace(did, f"{did.rsplit(':', 1)[0]}:e1_wrong"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await call(client, "register", {"handle": "device-auth", "did_document": sign_did_document(document, root)})
        assert "error" in response.json()
        assert "authorization" not in response.headers
        assert account_state(app) == []
        with app.state.store.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_device_token_tamper_and_generation_revocation_are_rejected(tmp_path):
    app, _ = setup_app(tmp_path)
    root, key, document = document_keys()
    did = document["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, document = await register_device(client, root, document)
        token = registered["access_token"]
        head, payload, sig = token.split(".")
        changed = claims(token)
        changed["auth_generation"] = 2
        modified = base64.urlsafe_b64encode(json.dumps(changed).encode()).rstrip(b"=").decode()
        assert (await call(client, "get_me", token=f"{head}.{modified}.{sig}")).status_code == 401
        assert (await call(client, "get_me", token=f"{head}.{payload}.invalid")).status_code == 401
        with app.state.store.connect() as conn:
            conn.execute("UPDATE single_device_accounts SET auth_generation = 2 WHERE owner_did = ?", (did,))
        assert (await call(client, "get_me", token=token)).status_code == 401
        renewal = await signed_me(client, document, key, f"{did}#device-primary-sign")
        assert renewal.status_code == 401
        assert "authorization" not in renewal.headers


@pytest.mark.asyncio
async def test_document_update_keeps_device_and_root_binding(tmp_path):
    app, _ = setup_app(tmp_path)
    root, _, document = document_keys()
    did = document["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, original = await register_device(client, root, document)
        token = registered["access_token"]
        before = account_state(app)
        changed = copy.deepcopy(document)
        changed["alsoKnownAs"] = ["https://testserver/profile/device-auth"]
        updated = await call(client, "update_document", {"document": sign_did_document(changed, root)}, token=token)
        assert "error" not in updated.json()
        assert account_state(app) == before
        replacement_root, _, replacement = document_keys(root_key=root)
        denied = await call(client, "update_document", {"document": sign_did_document(replacement, replacement_root)}, token=token)
        assert denied.json()["error"]["message"] == "device_key_or_root_change_not_supported"
        assert account_state(app) == before
        assert (await call(client, "get_me", token=token)).status_code == 200


@pytest.mark.asyncio
async def test_service_profile_upgrade_is_signed_compare_and_swap_and_preserves_device(tmp_path):
    import hashlib
    import jcs
    app, _ = setup_app(tmp_path)
    root, _, document = document_keys()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, original = await register_device(client, root, document)
        token = registered["access_token"]
        before = account_state(app)
        digest = "sha256:" + base64.urlsafe_b64encode(hashlib.sha256(jcs.canonicalize(original)).digest()).decode().rstrip("=")
        candidate = copy.deepcopy(original)
        candidate["service"][0]["profiles"].append("anp.group.base.v2")
        candidate = sign_did_document(candidate, root)
        request = {"did_document": candidate, "expected_document_hash": digest}
        changed = await call(client, "update_document", request, token=token)
        assert changed.json()["result"]["did_document"] == candidate
        assert changed.json()["result"]["document_version"] == 2
        assert account_state(app) == before
        replay = await call(client, "update_document", request, token=token)
        assert replay.json()["result"]["did_document"] == candidate
        assert replay.json()["result"]["document_version"] == 2
        older = await call(client, "update_document", {"did_document": original, "expected_document_hash": digest}, token=token)
        assert older.json()["error"]["message"] == "did_document_changed"
        invalid = await call(client, "update_document", {"did_document": candidate, "expected_document_hash": None}, token=token)
        assert invalid.json()["error"]["message"] == "expected_document_hash_invalid"
        assert account_state(app) == before
        candidate_hash = "sha256:" + base64.urlsafe_b64encode(hashlib.sha256(jcs.canonicalize(candidate)).digest()).decode().rstrip("=")
        reaffirm = {"did_document": candidate, "expected_document_hash": candidate_hash, "expected_document_version": 2}
        published = await call(client, "update_document", reaffirm, token=token)
        assert published.json()["result"]["document_version"] == 3
        repeated = await call(client, "update_document", reaffirm, token=token)
        assert repeated.json()["result"]["document_version"] == 3
        future = await call(client, "update_document", {**reaffirm, "expected_document_version": 4}, token=token)
        assert future.json()["error"]["message"] == "did_document_changed"
        assert (await call(client, "get_me", token=token)).json()["result"]["document_version"] == 3
        assert account_state(app) == before


@pytest.mark.asyncio
async def test_device_token_key_and_signature_replay_fence_survive_app_restart(tmp_path):
    app, settings = setup_app(tmp_path)
    root, key, document = document_keys()
    did = document["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        _, document = await register_device(client, root, document)
        raw, headers = signature_request(document, key, f"{did}#device-primary-sign")
        first = await client.post(AUTH_PATH, content=raw, headers=headers)
        assert first.status_code == 200
        token = first.json()["result"]["access_token"]
    restarted = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver") as client:
        assert (await call(client, "get_me", token=token)).status_code == 200
        replay = await client.post(AUTH_PATH, content=raw, headers=headers)
        assert replay.status_code == 401
        assert replay.json()["error"]["message"] == "signature_replayed"
        assert "authorization" not in replay.headers
        assert (await call(client, "get_me", token=token)).status_code == 200


@pytest.mark.asyncio
async def test_existing_valid_device_document_requires_signed_binding_migration(tmp_path):
    app, settings = setup_app(tmp_path)
    root, key, document = document_keys()
    did = document["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, document = await register_device(client, root, document)
        expected_account = account_state(app)
        with app.state.store.connect() as conn:
            conn.execute("DELETE FROM single_device_accounts WHERE owner_did = ?", (did,))
    restarted = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver") as client:
        assert (await call(client, "get_me", token=registered["access_token"])).status_code == 401
        assert account_state(restarted) == []
        renewal = await signed_me(client, document, key, f"{did}#device-primary-sign")
        assert renewal.status_code == 200
        assert renewal.json()["result"]["user_id"] == registered["user_id"]
        assert account_state(restarted) == expected_account


def test_device_token_crypto_verifier_rejects_none_wrong_key_and_wrong_binding(tmp_path):
    from dataclasses import replace
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from awiki_open_server.protocol.anp_adapter import validate_single_device_document
    from awiki_open_server.shared.errors import Unauthorized
    from awiki_open_server.user_compat.device_auth import device_account, issue_device_token, validate_device_token

    root, _, document = document_keys()
    did = document["id"]
    account = device_account(did, validate_single_device_document(sign_did_document(document, root)))
    key = Ed25519PrivateKey.generate()
    token = issue_device_token(account, key, 3600)
    validate_device_token(token, account, key)
    with pytest.raises(Unauthorized):
        validate_device_token(token, account, Ed25519PrivateKey.generate())
    with pytest.raises(Unauthorized):
        validate_device_token(token, replace(account, device_id="other-device"), key)
    none_header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    with pytest.raises(Unauthorized):
        validate_device_token(f"{none_header}.{token.split('.')[1]}.open-server", account, key)


@pytest.mark.parametrize("bundle", ["current-base", "current-device", "legacy-draft", "legacy-device"])
@pytest.mark.asyncio
async def test_manifest_validation_keeps_original_published_profile_bytes(tmp_path, bundle):
    app, _ = setup_app(tmp_path)
    root, _, document = document_keys()
    profiles = document["deviceManifest"]["devices"][0]["profiles"]
    if bundle == "legacy-draft":
        document["deviceManifest"]["devices"][0]["profiles"] = [p[:-1] + "2" for p in profiles]
    elif bundle != "legacy-device":
        profiles[profiles.index("anp.group.base.v1")] = "anp.group.base.v2"
    if bundle in {"current-device", "legacy-device"}:
        profiles.extend(["anp.direct.e2ee.v2", "anp.group.e2ee.v2"])
    signed = sign_did_document(document, root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registered, returned_document = await register_device(client, root, document)
        response = await call(client, "get_me", token=registered["access_token"])
        assert response.status_code == 200
        # Signed JSON is retained verbatim as an object, including profile IDs.
        assert response.json()["result"]["did_document"] == signed == returned_document


@pytest.mark.asyncio
async def test_published_group_document_cannot_register_as_a_user(tmp_path):
    from awiki_open_server.protocol.anp_adapter import create_group_did_identity, require_did_document_binding

    app, _ = setup_app(tmp_path)
    document, _ = create_group_did_identity(hostname="testserver", group_id="reserved", service_endpoint="http://testserver/anp-im/rpc", service_did="did:wba:testserver")
    require_did_document_binding(document)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await call(client, "register", {"handle": "namespace-attack", "did_document": document})
        assert response.json()["error"]["message"] == "did_namespace_reserved"
        assert account_state(app) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["user", "document", "generation"])
async def test_renewal_keeps_inflight_device_token_but_revocation_rejects_both(tmp_path, revocation):
    app, _ = setup_app(tmp_path)
    root, device_key, document = document_keys()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        registration, document = await register_device(client, root, document)
        old = registration["access_token"]
        before = account_state(app)
        renewed = await signed_me(client, document, device_key, f"{document['id']}#device-primary-sign")
        new = renewed.json()["result"]["access_token"]
        assert old != new
        assert account_state(app) == before
        for token in (old, new):
            assert (await call(client, "get_me", token=token)).status_code == 200
            result = await client.post("/im/rpc", json={"jsonrpc": "2.0", "id": "cap", "method": "anp.get_capabilities", "params": {}}, headers={"Authorization": f"Bearer {token}"})
            assert result.status_code == 200
            assert "result" in result.json()
        with app.state.store.connect() as conn:
            if revocation == "user":
                conn.execute("UPDATE users SET revoked_at = '2026-01-01T00:00:00Z' WHERE did = ?", (document["id"],))
            elif revocation == "document":
                conn.execute("UPDATE did_documents SET status = 'revoked' WHERE did = ?", (document["id"],))
            else:
                conn.execute("UPDATE single_device_accounts SET auth_generation = auth_generation + 1 WHERE owner_did = ?", (document["id"],))
        for token in (old, new):
            assert (await call(client, "get_me", token=token)).status_code == 401
