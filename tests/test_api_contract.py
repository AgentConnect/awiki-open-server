from __future__ import annotations

import httpx
import pytest

from awiki_open_server.app.api_contract import (
    API_CONTRACT_HEADER,
    USER_SERVICE_CONTRACT,
    ApiContractEntry,
    resolve_api_contract_route,
)
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem


def _app(tmp_path):
    return create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
        )
    )


def test_route_resolution_separates_canonical_and_legacy() -> None:
    canonical = resolve_api_contract_route("POST", "/user-service/v1/did-auth/rpc")
    legacy = resolve_api_contract_route("POST", "/user-service/did-auth/rpc")

    assert canonical is not None
    assert canonical.entry is ApiContractEntry.CANONICAL
    assert canonical.contract == USER_SERVICE_CONTRACT
    assert legacy is not None
    assert legacy.entry is ApiContractEntry.LEGACY
    assert resolve_api_contract_route("GET", "/healthz") is None
    assert resolve_api_contract_route("POST", "/anp-im/rpc") is None


@pytest.mark.asyncio
async def test_canonical_and_legacy_routes_share_state_and_contract_header(tmp_path) -> None:
    app = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        registered = await client.post(
            "/user-service/v1/did-auth/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "register",
                "params": {"handle": "canonical-client"},
                "id": "register",
            },
            headers={"X-AWiki-Client-Version": "awiki-cli/0714/0.1.0"},
        )
        token = registered.json()["result"]["token"]
        legacy = await client.post(
            "/user-service/did-auth/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "verify_http_request",
                "params": {},
                "id": "verify",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        missing = await client.get("/user-service/v1/not-exist")

    assert registered.status_code == legacy.status_code == 200
    assert legacy.json()["result"]["did"] == registered.json()["result"]["did"]
    assert registered.headers.get_list(API_CONTRACT_HEADER) == [USER_SERVICE_CONTRACT]
    assert legacy.headers.get_list(API_CONTRACT_HEADER) == [USER_SERVICE_CONTRACT]
    assert missing.status_code == 404
    assert missing.headers.get_list(API_CONTRACT_HEADER) == [USER_SERVICE_CONTRACT]

    snapshot = app.state.api_contract_metrics.snapshot()
    assert snapshot["api_contract"] == {
        "canonical:request_error": 1,
        "canonical:success": 1,
        "legacy:success": 1,
    }
    assert snapshot["client_version"]["user_service:valid"] == 1
    assert snapshot["client_version"]["user_service:missing"] == 2


@pytest.mark.asyncio
async def test_client_version_is_observed_but_does_not_select_contract(tmp_path) -> None:
    app = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    duplicate_headers = [
        ("X-AWiki-Client-Version", "awiki-cli/0714/0.1.0"),
        ("X-AWiki-Client-Version", "awiki-cli/0714/0.1.1"),
    ]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        duplicate = await client.post(
            "/user-service/v1/did-auth/rpc",
            json={"jsonrpc": "2.0", "method": "unknown", "params": {}, "id": "1"},
            headers=duplicate_headers,
        )
        malformed = await client.post(
            "/im/rpc",
            json={"jsonrpc": "2.0", "method": "anp.get_capabilities", "params": {}, "id": "2"},
            headers={"X-AWiki-Client-Version": "not-a-version"},
        )
        public = await client.post(
            "/anp-im/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "anp.get_capabilities",
                "params": {
                    "meta": {
                        "profile": "anp.core.binding.v1",
                        "security_profile": "transport-protected",
                        "operation_id": "op-public-capabilities",
                    },
                    "body": {},
                },
                "id": "3",
            },
            headers={"X-AWiki-Client-Version": "not-a-version"},
        )

    assert duplicate.status_code == malformed.status_code == public.status_code == 200
    snapshot = app.state.api_contract_metrics.snapshot()["client_version"]
    assert snapshot["user_service:duplicate"] == 1
    assert snapshot["message_service:invalid"] == 1
    assert all(not key.startswith("public") for key in snapshot)


def test_openapi_exposes_canonical_user_service_routes_only(tmp_path) -> None:
    paths = set(_app(tmp_path).openapi()["paths"])

    required = {
        "/user-service/v1/did-auth/rpc",
        "/user-service/v1/did/profile/rpc",
        "/user-service/v1/handle/rpc",
        "/user-service/v1/did/relationships/rpc",
        "/user-service/v1/users/rpc",
        "/user-service/v1/content/rpc",
        "/user-service/v1/site/rpc",
        "/user-service/v1/group/rpc",
        "/user-service/v1/personal-agent/rpc",
        "/user-service/v1/auth/sms-codes",
        "/user-service/v1/ws/tickets",
    }
    legacy = {
        "/user-service/did-auth/rpc",
        "/did-auth/rpc",
        "/content/rpc",
        "/site/rpc",
        "/group/rpc",
        "/user-service/message-agent/rpc",
    }

    assert required <= paths
    assert not (legacy & paths)
    assert "/user-service/v1/message-agent/rpc" not in paths
