from __future__ import annotations

import httpx
import pytest

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem
from tests.conftest import rpc
from tests.helpers import did_keypair_document, register


@pytest.mark.asyncio
async def test_local_handle_resolution_endpoint_publishes_wns_document(client):
    did, _ = await register(client, "alice")

    response = await client.get("/.well-known/handle/alice")

    assert response.status_code == 200
    document = response.json()
    assert document["handle"] == "alice.testserver"
    assert document["did"] == did
    assert document["status"] == "active"
    assert document["profile"]["subject_did"] == did
    assert document["profile"]["handle"] == "alice.testserver"


@pytest.mark.asyncio
async def test_remote_handle_lookup_uses_standard_wns_and_resolves_did_document(monkeypatch, client):
    remote_did = "did:wba:remote.test:users:bob"
    _, remote_doc = did_keypair_document(remote_did)
    remote_doc["id"] = remote_did
    remote_doc["service"][0]["serviceEndpoint"] = "https://remote.test/anp-im/rpc"
    remote_doc["service"][0]["serviceDid"] = "did:wba:remote.test"
    fetched: list[str] = []

    def fake_get(url: str, max_bytes: int, *, settings=None):
        fetched.append(url)
        if url == "https://remote.test/.well-known/handle/bob":
            return {
                "handle": "bob.remote.test",
                "did": remote_did,
                "status": "active",
                "profile": {
                    "type": "DIDSubjectProfile",
                    "subject_did": remote_did,
                    "subject_type": "person",
                    "handle": "bob.remote.test",
                    "display_name": "Remote Bob",
                    "description": "remote profile",
                },
            }
        if url == "https://remote.test/users/bob/did.json":
            return remote_doc
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("awiki_open_server.user_compat.wns._http_get_json_limited", fake_get)

    lookup = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "bob.remote.test"})
    assert lookup["result"]["did"] == remote_did
    assert lookup["result"]["full_handle"] == "bob.remote.test"
    assert lookup["result"]["resolver_source"] == "remote_wns"
    assert lookup["result"]["verification_level"] == "forward_only"
    assert lookup["result"]["profile"]["display_name"] == "Remote Bob"
    assert lookup["result"]["service_endpoints"][0]["serviceEndpoint"] == "https://remote.test/anp-im/rpc"
    assert fetched == [
        "https://remote.test/.well-known/handle/bob",
        "https://remote.test/users/bob/did.json",
    ]

    resolved = await rpc(client, "/user-service/did/profile/rpc", "resolve", {"did": remote_did})
    assert resolved["result"]["document"]["id"] == remote_did
    assert resolved["result"]["resolver_source"] == "remote_did"


@pytest.mark.asyncio
async def test_remote_handle_lookup_reports_bidirectional_exact_when_declared(monkeypatch, client):
    remote_did = "did:wba:remote.test:users:bob"
    _, remote_doc = did_keypair_document(remote_did)
    remote_doc["id"] = remote_did
    remote_doc["service"][0]["serviceEndpoint"] = "https://remote.test/anp-im/rpc"
    remote_doc["service"].append(
        {
            "id": f"{remote_did}#handle",
            "type": "ANPHandleService",
            "serviceEndpoint": "https://remote.test/.well-known/handle/bob",
        }
    )

    def fake_get(url: str, max_bytes: int, *, settings=None):
        if url == "https://remote.test/.well-known/handle/bob":
            return {"handle": "bob.remote.test", "did": remote_did, "status": "active"}
        if url == "https://remote.test/users/bob/did.json":
            return remote_doc
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("awiki_open_server.user_compat.wns._http_get_json_limited", fake_get)

    lookup = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "bob.remote.test"})

    assert lookup["result"]["verification_level"] == "bidirectional_exact"
    assert lookup["result"]["warnings"] == []


@pytest.mark.asyncio
async def test_remote_handle_lookup_rejects_domain_mismatch(monkeypatch, client):
    def fake_get(url: str, max_bytes: int, *, settings=None):
        return {
            "handle": "bob.remote.test",
            "did": "did:wba:evil.test:users:bob",
            "status": "active",
        }

    monkeypatch.setattr("awiki_open_server.user_compat.wns._http_get_json_limited", fake_get)

    result = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "bob.remote.test"})

    assert result["error"]["message"] == "handle_did_domain_mismatch"


@pytest.mark.asyncio
async def test_remote_resolution_blocks_private_network_without_dev_mapping(client):
    result = await rpc(client, "/user-service/handle/rpc", "lookup", {"handle": "bob.127.0.0.1"})

    assert result["error"]["message"] == "private_network_resolution_not_allowed"


@pytest.mark.asyncio
async def test_remote_resolution_allows_dev_resolver_mapping(tmp_path):
    target_app = create_app(
        Settings(
            data_dir=tmp_path / "target",
            public_base_url="http://target.test",
            service_did="did:wba:target.test",
            did_domain="target.test",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
        )
    )
    source_app = create_app(
        Settings(
            data_dir=tmp_path / "source",
            public_base_url="http://source.test",
            service_did="did:wba:source.test",
            did_domain="source.test",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
            wns_resolver_base_urls={"target.test": "http://127.0.0.1:9002"},
            did_resolver_base_urls={"target.test": "http://127.0.0.1:9002"},
        )
    )
    target_transport = httpx.ASGITransport(app=target_app)
    source_transport = httpx.ASGITransport(app=source_app)

    async with httpx.AsyncClient(transport=target_transport, base_url="http://127.0.0.1:9002") as target_client:
        did, _ = await register(target_client, "bob")

    from awiki_open_server.user_compat import wns

    def fake_get(url: str, max_bytes: int, *, settings=None):
        import anyio

        async def get() -> dict:
            async with httpx.AsyncClient(transport=target_transport, base_url="http://127.0.0.1:9002") as target_client:
                response = await target_client.get(url.removeprefix("http://127.0.0.1:9002"))
                assert response.status_code == 200
                return response.json()

        return anyio.run(get)

    original_get = wns._http_get_json_limited
    wns._http_get_json_limited = fake_get
    try:
        async with httpx.AsyncClient(transport=source_transport, base_url="http://source.test") as source_client:
            result = await rpc(source_client, "/user-service/handle/rpc", "lookup", {"handle": "bob.target.test"})
    finally:
        wns._http_get_json_limited = original_get

    assert result["result"]["did"] == did
    assert result["result"]["resolver_source"] == "remote_wns"
