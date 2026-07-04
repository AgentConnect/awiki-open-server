from __future__ import annotations

from fastapi.testclient import TestClient
import httpx
import pytest

from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import generate_ed25519_private_key_pem
from tests.conftest import rpc


@pytest.mark.asyncio
async def test_custom_anp_public_rpc_path_matches_did_document(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="https://rwiki.cn",
            service_did="did:wba:rwiki.cn",
            did_domain="rwiki.cn",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
            anp_public_rpc_path="public/anp/rpc",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        document = (await client.get("/.well-known/did.json")).json()
        custom_caps = await rpc(client, "/public/anp/rpc", "anp.get_capabilities")
        old_caps = await client.post(
            "/anp-im/rpc",
            json={"jsonrpc": "2.0", "method": "anp.get_capabilities", "params": {}, "id": "old"},
        )

    assert document["service"][0]["serviceEndpoint"] == "https://rwiki.cn/public/anp/rpc"
    assert custom_caps["result"]["service_did"] == "did:wba:rwiki.cn"
    assert old_caps.status_code == 404


@pytest.mark.asyncio
async def test_custom_im_rpc_path_replaces_default_local_rpc(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            im_rpc_path="/local/im/rpc",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        custom = await rpc(client, "/local/im/rpc", "anp.get_capabilities")
        old = await client.post(
            "/im/rpc",
            json={"jsonrpc": "2.0", "method": "anp.get_capabilities", "params": {}, "id": "old"},
        )

    assert "anp.direct.base.v1" in custom["result"]["supported_profiles"]
    assert old.status_code == 404


def test_custom_ws_path_replaces_default_websocket_path(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
            ws_path="/local/im/ws",
        )
    )
    with TestClient(app) as client:
        registered = client.post(
            "/did-auth/rpc",
            json={"jsonrpc": "2.0", "method": "register", "params": {"handle": "ws-custom"}, "id": "1"},
        ).json()["result"]
        ticket = client.post("/ws/tickets", headers={"Authorization": f"Bearer {registered['token']}"}).json()["ticket"]
        with client.websocket_connect(f"/local/im/ws?ticket={ticket}") as websocket:
            notification = websocket.receive_json()

    assert notification["method"] == "sync"
    assert notification["params"]["owner_did"] == registered["did"]


@pytest.mark.asyncio
async def test_custom_object_paths_match_attachment_uris(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="https://rwiki.cn",
            service_did="did:wba:rwiki.cn",
            did_domain="rwiki.cn",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            object_upload_path="/blob/upload",
            object_download_path="/blob",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "blob-user"})
        token = registered["result"]["token"]
        slot = await rpc(client, "/im/rpc", "attachment.create_slot", {}, token=token)
        slot_result = slot["result"]
        assert slot_result["upload_uri"].startswith("https://rwiki.cn/blob/upload/")
        assert slot_result["object_uri"].startswith("https://rwiki.cn/blob/")

        upload = await client.put(
            f"/blob/upload/{slot_result['slot_id']}",
            content=b"configured object",
            params={"token": slot_result["upload_token"]},
        )
        assert upload.status_code == 200
        committed = await rpc(
            client,
            "/im/rpc",
            "attachment.commit_object",
            {
                "slot_id": slot_result["slot_id"],
                "commit_token": slot_result["commit_token"],
                "content_type": "text/plain",
            },
            token=token,
        )
        ticket = await rpc(
            client,
            "/im/rpc",
            "attachment.get_download_ticket",
            {"object_id": committed["result"]["object_id"]},
            token=token,
        )
        download = await client.get(f"/blob/{committed['result']['object_id']}", params={"ticket": ticket["result"]["ticket"]})

    assert committed["result"]["object_uri"].startswith("https://rwiki.cn/blob/")
    assert ticket["result"]["download_uri"].startswith("https://rwiki.cn/blob/")
    assert download.status_code == 200
    assert download.content == b"configured object"
