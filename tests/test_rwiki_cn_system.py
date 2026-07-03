from __future__ import annotations

import os
import time

import httpx
import pytest
import pytest_asyncio

from tests.test_messaging_objects import did_keypair_document


RUN_PUBLIC_SYSTEM_TESTS = os.environ.get("AWIKI_RUN_PUBLIC_SYSTEM_TESTS", "").lower() in {"1", "true", "yes"}
PUBLIC_BASE_URL = os.environ.get("AWIKI_PUBLIC_SYSTEM_BASE_URL", "https://rwiki.cn").rstrip("/")
PUBLIC_DID_DOMAIN = os.environ.get("AWIKI_PUBLIC_SYSTEM_DID_DOMAIN", "rwiki.cn")
PUBLIC_SERVICE_DID = os.environ.get("AWIKI_PUBLIC_SYSTEM_SERVICE_DID", f"did:wba:{PUBLIC_DID_DOMAIN}")

pytestmark = pytest.mark.skipif(
    not RUN_PUBLIC_SYSTEM_TESTS,
    reason="set AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 to run rwiki.cn public system tests",
)


@pytest_asyncio.fixture
async def public_client():
    async with httpx.AsyncClient(base_url=PUBLIC_BASE_URL, timeout=20.0) as client:
        yield client


async def rpc(
    client: httpx.AsyncClient,
    path: str,
    method: str,
    params: dict | None = None,
    token: str | None = None,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(
        path,
        json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": "system-test"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    return data


@pytest.mark.asyncio
async def test_rwiki_cn_public_service_surface(public_client):
    did_response = await public_client.get("/.well-known/did.json")
    assert did_response.status_code == 200
    document = did_response.json()
    assert document["id"] == PUBLIC_SERVICE_DID

    services = [
        service
        for service in document.get("service", [])
        if isinstance(service, dict) and service.get("type") == "ANPMessageService"
    ]
    assert len(services) == 1
    service = services[0]
    assert service["serviceEndpoint"] == f"{PUBLIC_BASE_URL}/anp-im/rpc"
    assert service["serviceDid"] == PUBLIC_SERVICE_DID
    assert service["authSchemes"] == ["bearer", "didwba"]
    assert "anp.direct.base.v1" in service["profiles"]
    assert "anp.group.base.v1" in service["profiles"]
    assert "anp.attachment.v1" in service["profiles"]
    assert document.get("verificationMethod")
    assert document.get("authentication")
    assert document.get("proof")

    health = await public_client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    caps = await rpc(
        public_client,
        "/anp-im/rpc",
        "anp.get_capabilities",
        {
            "meta": {
                "anp_version": "1.0",
                "profile": "anp.core.binding.v1",
                "security_profile": "transport-protected",
                "sender_did": PUBLIC_SERVICE_DID,
                "operation_id": f"op-public-system-{int(time.time())}",
                "content_type": "application/json",
            },
            "body": {},
        },
    )
    result = caps["result"]
    assert result["service_did"] == PUBLIC_SERVICE_DID
    assert result["features"]["cross_domain_direct"]["enabled"] is True
    assert result["features"]["group_participant"]["management"] is False
    assert "federation" in result["disabled_features"]
    assert result["direct_e2ee"]["enabled"] is False


@pytest.mark.asyncio
async def test_rwiki_cn_mvp_identity_direct_and_disabled_contact_verification(public_client):
    suffix = str(int(time.time() * 1000))
    alice_handle = f"sysalice{suffix}"
    bob_handle = f"sysbob{suffix}"
    alice_did = f"did:wba:{PUBLIC_DID_DOMAIN}:{alice_handle}:e1_{suffix}"
    bob_did = f"did:wba:{PUBLIC_DID_DOMAIN}:{bob_handle}:e1_{suffix}"
    alice_key, alice_doc = did_keypair_document(alice_did)
    bob_key, bob_doc = did_keypair_document(bob_did)
    del alice_key, bob_key

    for did_document in (alice_doc, bob_doc):
        did_document["service"][0]["serviceEndpoint"] = f"{PUBLIC_BASE_URL}/anp-im/rpc"
        did_document["service"][0]["serviceDid"] = PUBLIC_SERVICE_DID

    alice_reg = await rpc(
        public_client,
        "/user-service/did-auth/rpc",
        "register",
        {"handle": alice_handle, "did_document": alice_doc},
    )
    bob_reg = await rpc(
        public_client,
        "/user-service/did-auth/rpc",
        "register",
        {"handle": bob_handle, "did_document": bob_doc},
    )
    assert alice_reg["result"]["did"] == alice_did
    assert bob_reg["result"]["did"] == bob_did
    for registered in (alice_reg, bob_reg):
        services = [
            service
            for service in registered["result"]["document"].get("service", [])
            if isinstance(service, dict) and service.get("type") == "ANPMessageService"
        ]
        assert len(services) == 1
        assert services[0]["serviceEndpoint"] == f"{PUBLIC_BASE_URL}/anp-im/rpc"
        assert services[0]["serviceDid"] == PUBLIC_SERVICE_DID
        assert services[0]["authSchemes"] == ["bearer", "didwba"]
        assert "anp.direct.base.v1" in services[0]["profiles"]

    resolved = await public_client.get(f"/{alice_handle}/e1_{suffix}/did.json")
    assert resolved.status_code == 200
    assert resolved.json()["id"] == alice_did

    sms = await public_client.post("/user-service/auth/sms-codes", json={"phone": "+8610012345678"})
    assert sms.status_code == 400
    assert sms.json()["detail"]["error"] == "contact_verification_not_enabled"

    email = await public_client.post("/user-service/auth/email-send", json={"email": "system@example.com"})
    assert email.status_code == 400
    assert email.json()["detail"]["error"] == "contact_verification_not_enabled"

    sent = await rpc(
        public_client,
        "/im/rpc",
        "direct.send",
        {"recipient_did": bob_did, "text": f"rwiki.cn system direct {suffix}"},
        token=alice_reg["result"]["token"],
    )
    assert sent["result"]["accepted"] is True
    assert sent["result"]["recipient_did"] == bob_did

    inbox = await rpc(public_client, "/im/rpc", "inbox.get", token=bob_reg["result"]["token"])
    assert inbox["result"]["messages"][0]["message_id"] == sent["result"]["message_id"]
    assert inbox["result"]["messages"][0]["body"]["text"] == f"rwiki.cn system direct {suffix}"

    history = await rpc(
        public_client,
        "/im/rpc",
        "direct.get_history",
        {"peer_did": alice_did},
        token=bob_reg["result"]["token"],
    )
    assert history["result"]["messages"][0]["message_id"] == sent["result"]["message_id"]

    group_did = f"did:wba:{PUBLIC_DID_DOMAIN}:groups:open"
    joined = await rpc(public_client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_reg["result"]["token"])
    assert joined["result"]["joined"] is True

    group_create = await rpc(public_client, "/im/rpc", "group.create", {"display_name": "nope"}, token=alice_reg["result"]["token"])
    assert group_create["error"]["message"] == "not_supported"
