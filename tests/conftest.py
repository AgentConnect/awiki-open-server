from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem


@pytest_asyncio.fixture
async def client(tmp_path):
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
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest_asyncio.fixture
async def contact_verification_compat_client(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
            enable_contact_verification_compat=True,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


async def rpc(client: httpx.AsyncClient, path: str, method: str, params: dict | None = None, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(path, json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": "1"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    return data
