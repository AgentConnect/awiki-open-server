from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

import awiki_open_server.messaging.core as messaging_services
import awiki_open_server.shared.runtime as runtime
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import (
    build_service_did_document,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
    verify_peer_http_signature,
)
from awiki_open_server.shared.errors import InvalidParams
from tests.conftest import rpc
from tests.helpers import did_keypair_document, origin_proof, register, register_with_key, remote_direct_result

@pytest.mark.asyncio
async def test_attachment_roundtrip(client):
    _, token = await register(client, "carol")
    _, other_token = await register(client, "eve")

    slot = await rpc(client, "/im/rpc", "attachment.create_slot", {}, token=token)
    slot_result = slot["result"]
    assert slot_result["attachment_id"].startswith("att_")
    assert slot_result["upload_uri"].endswith(f"/objects/upload/{slot_result['slot_id']}")
    assert slot_result["upload_headers"]["X-ANP-Upload-Token"] == slot_result["upload_token"]
    assert slot_result["object_uri"].endswith(f"/objects/{slot_result['object_id']}")

    upload = await client.put(
        f"/objects/upload/{slot_result['slot_id']}",
        params={"token": slot_result["upload_token"]},
        content=b"hello file",
    )
    assert upload.status_code == 200

    committed = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": slot_result["slot_id"], "commit_token": slot_result["commit_token"], "content_type": "text/plain"},
        token=token,
    )
    object_id = committed["result"]["object_id"]
    assert committed["result"]["committed"] is True
    assert committed["result"]["object_uri"].endswith(f"/objects/{object_id}")
    assert committed["result"]["committed_at"]
    assert committed["result"]["digest"]["alg"] == "sha-256"

    ticket = await rpc(client, "/im/rpc", "attachment.get_download_ticket", {"object_id": object_id}, token=token)
    assert ticket["result"]["download_uri"] == ticket["result"]["download_url"]
    assert ticket["result"]["download_headers"]["Authorization"] == f"Bearer {ticket['result']['ticket']}"
    assert ticket["result"]["download_ticket_b64u"] == ticket["result"]["ticket"]
    assert ticket["result"]["ticket_binding"]["requester_did"] == "did:wba:testserver:users:carol"
    download = await client.get(f"/objects/{object_id}", params={"ticket": ticket["result"]["ticket"]})
    assert download.status_code == 200
    assert download.content == b"hello file"
    bearer_download = await client.get(f"/objects/{object_id}", headers={"Authorization": f"Bearer {ticket['result']['download_ticket_b64u']}"})
    assert bearer_download.status_code == 200
    assert bearer_download.content == b"hello file"
    uri_ticket = await rpc(client, "/im/rpc", "attachment.get_download_ticket", {"object_uri": committed["result"]["object_uri"]}, token=token)
    assert uri_ticket["result"]["object_id"] == object_id
    assert uri_ticket["result"]["ticket_binding"]["object_uri"] == committed["result"]["object_uri"]

    denied = await rpc(client, "/im/rpc", "attachment.get_download_ticket", {"object_id": object_id}, token=other_token)
    assert denied["error"]["message"] == "object_ticket_not_allowed"

    public_denied = await rpc(client, "/anp-im/rpc", "attachment.get_download_ticket", {"object_id": object_id})
    assert public_denied["error"]["message"] == "missing_requester_did"


@pytest.mark.asyncio
async def test_attachment_download_ticket_accepts_anp_body_shape(client):
    sender_did, sender_token = await register(client, "att-sender")
    recipient_did, recipient_token = await register(client, "att-recipient")
    outsider_did, outsider_token = await register(client, "att-outsider")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=sender_token)
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=recipient_token)

    slot = await rpc(client, "/im/rpc", "attachment.create_slot", {"attachment_id": "att-direct"}, token=sender_token)
    slot_result = slot["result"]
    await client.put(
        f"/objects/upload/{slot_result['slot_id']}",
        headers=slot_result["upload_headers"],
        content=b"anp attachment",
    )
    committed = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {
            "attachment_id": "att-direct",
            "slot_id": slot_result["slot_id"],
            "commit_token": slot_result["commit_token"],
            "content_type": "text/plain",
        },
        token=sender_token,
    )
    object_uri = committed["result"]["object_uri"]

    direct_meta = {
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "target": {"kind": "agent", "did": recipient_did},
        "operation_id": "op-att-direct",
        "message_id": "msg-att-direct",
        "content_type": "application/anp-attachment-manifest+json",
    }
    direct_body = {
        "payload": {
            "attachments": [
                {
                    "attachment_id": "att-direct",
                    "filename": "direct.txt",
                    "mime_type": "text/plain",
                    "size": "14",
                    "digest": {"alg": "sha-256", "value_hex": committed["result"]["sha256"]},
                    "access_info": {"object_uri": object_uri},
                    "encryption_info": {"mode": "none"},
                }
            ],
            "primary_attachment_id": "att-direct",
        }
    }
    sent = await rpc(client, "/im/rpc", "direct.send", {"meta": direct_meta, "body": direct_body}, token=sender_token)
    assert sent["result"]["message_id"] == "msg-att-direct"

    ticket_meta = {
        "profile": "anp.attachment.v1",
        "security_profile": "transport-protected",
        "sender_did": recipient_did,
        "target": {"kind": "service", "did": "did:wba:testserver"},
        "operation_id": "op-ticket-direct",
    }
    ticket_body = {
        "attachment_id": "att-direct",
        "object_uri": object_uri,
        "sender_did": sender_did,
        "requester_did": recipient_did,
        "message_security_profile": "transport-protected",
        "message_id": "msg-att-direct",
        "message_target_did": recipient_did,
        "one_time": True,
    }
    direct_ticket = await rpc(client, "/im/rpc", "attachment.get_download_ticket", {"meta": ticket_meta, "body": ticket_body}, token=recipient_token)
    assert direct_ticket["result"]["download_ticket_b64u"] == direct_ticket["result"]["ticket"]
    assert direct_ticket["result"]["ticket_binding"] == {
        "attachment_id": "att-direct",
        "object_uri": object_uri,
        "sender_did": sender_did,
        "requester_did": recipient_did,
        "message_id": "msg-att-direct",
        "message_security_profile": "transport-protected",
        "message_target_did": recipient_did,
    }
    download = await client.get(
        f"/objects/{committed['result']['object_id']}",
        headers={"Authorization": f"Bearer {direct_ticket['result']['download_ticket_b64u']}"},
    )
    assert download.status_code == 200
    assert download.content == b"anp attachment"

    mismatch = await rpc(
        client,
        "/im/rpc",
        "attachment.get_download_ticket",
        {"meta": ticket_meta, "body": {**ticket_body, "object_uri": "http://testserver/objects/wrong"}},
        token=recipient_token,
    )
    assert mismatch["error"]["message"] == "object_not_found"

    target_mismatch = await rpc(
        client,
        "/im/rpc",
        "attachment.get_download_ticket",
        {"meta": ticket_meta, "body": {**ticket_body, "message_target_did": outsider_did}},
        token=recipient_token,
    )
    assert target_mismatch["error"]["message"] == "attachment_requester_target_mismatch"

    group_meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "target": {"kind": "group", "did": group_did},
        "operation_id": "op-att-group",
        "message_id": "msg-att-group",
        "content_type": "application/anp-attachment-manifest+json",
    }
    group_sent = await rpc(client, "/im/rpc", "group.send", {"meta": group_meta, "body": direct_body}, token=sender_token)
    assert group_sent["result"]["message_id"] == "msg-att-group"

    group_ticket_body = {
        "attachment_id": "att-direct",
        "object_uri": object_uri,
        "sender_did": sender_did,
        "requester_did": recipient_did,
        "message_security_profile": "transport-protected",
        "message_id": "msg-att-group",
        "group_did": group_did,
    }
    group_ticket = await rpc(
        client,
        "/im/rpc",
        "attachment.get_download_ticket",
        {"meta": ticket_meta, "body": group_ticket_body},
        token=recipient_token,
    )
    assert group_ticket["result"]["ticket_binding"]["group_did"] == group_did

    non_member = await rpc(
        client,
        "/im/rpc",
        "attachment.get_download_ticket",
        {"meta": ticket_meta, "body": {**group_ticket_body, "requester_did": outsider_did}},
        token=outsider_token,
    )
    assert non_member["error"]["message"] == "anp.attachment.unauthorized_requester"


@pytest.mark.asyncio
async def test_attachment_upload_accepts_declared_header_token(client):
    _, token = await register(client, "header-uploader")

    slot = await rpc(client, "/im/rpc", "attachment.create_slot", {}, token=token)
    slot_result = slot["result"]
    upload = await client.put(
        f"/objects/upload/{slot_result['slot_id']}",
        headers=slot_result["upload_headers"],
        content=b"header token file",
    )
    assert upload.status_code == 200

    committed = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": slot_result["slot_id"], "commit_token": slot_result["commit_token"], "content_type": "text/plain"},
        token=token,
    )
    assert committed["result"]["size"] == len(b"header token file")


@pytest.mark.asyncio
async def test_attachment_abort(client):
    _, token = await register(client, "dave")
    slot = await rpc(client, "/im/rpc", "attachment.create_slot", {}, token=token)
    aborted = await rpc(client, "/im/rpc", "attachment.abort_object", {"slot_id": slot["result"]["slot_id"]}, token=token)
    assert aborted["result"]["aborted"] is True
    assert aborted["result"]["aborted_at"]

