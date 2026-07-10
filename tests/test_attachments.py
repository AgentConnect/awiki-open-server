from __future__ import annotations

import hashlib

import httpx
import pytest

from awiki_open_server.attachments.core import cleanup_expired_attachments
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import (
    generate_ed25519_private_key_pem,
)
from tests.conftest import rpc
from tests.helpers import register

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
    assert ticket["result"]["ticket_binding"]["requester_did"] == "did:wba:testserver:users:carol:e1_default"
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
async def test_attachment_commit_validates_expected_metadata_and_mime(client):
    _, token = await register(client, "att-meta")
    data = b"verified attachment"
    digest = hashlib.sha256(data).hexdigest()

    slot = await rpc(
        client,
        "/im/rpc",
        "attachment.create_slot",
        {
            "attachment_id": "att-meta-ok",
            "expected_size": len(data),
            "expected_digest": {"alg": "sha-256", "value_hex": digest},
            "content_type": "text/plain",
        },
        token=token,
    )
    slot_result = slot["result"]
    await client.put(f"/objects/upload/{slot_result['slot_id']}", headers=slot_result["upload_headers"], content=data)
    committed = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": slot_result["slot_id"], "commit_token": slot_result["commit_token"]},
        token=token,
    )
    assert committed["result"]["size"] == len(data)
    assert committed["result"]["sha256"] == digest
    assert committed["result"]["content_type"] == "text/plain"

    size_slot = await rpc(client, "/im/rpc", "attachment.create_slot", {"expected_size": len(data) + 1}, token=token)
    await client.put(f"/objects/upload/{size_slot['result']['slot_id']}", headers=size_slot["result"]["upload_headers"], content=data)
    size_mismatch = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": size_slot["result"]["slot_id"], "commit_token": size_slot["result"]["commit_token"]},
        token=token,
    )
    assert size_mismatch["error"]["message"] == "attachment_size_mismatch"
    assert size_mismatch["error"]["data"] == {"expected": len(data) + 1, "actual": len(data)}

    digest_slot = await rpc(
        client,
        "/im/rpc",
        "attachment.create_slot",
        {"expected_digest": {"alg": "sha-256", "value_hex": "0" * 64}},
        token=token,
    )
    await client.put(f"/objects/upload/{digest_slot['result']['slot_id']}", headers=digest_slot["result"]["upload_headers"], content=data)
    digest_mismatch = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": digest_slot["result"]["slot_id"], "commit_token": digest_slot["result"]["commit_token"]},
        token=token,
    )
    assert digest_mismatch["error"]["message"] == "attachment_digest_mismatch"

    mime_slot = await rpc(client, "/im/rpc", "attachment.create_slot", {"content_type": "text/plain"}, token=token)
    await client.put(f"/objects/upload/{mime_slot['result']['slot_id']}", headers=mime_slot["result"]["upload_headers"], content=data)
    mime_mismatch = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": mime_slot["result"]["slot_id"], "commit_token": mime_slot["result"]["commit_token"], "content_type": "application/json"},
        token=token,
    )
    assert mime_mismatch["error"]["message"] == "attachment_content_type_mismatch"
    assert mime_mismatch["error"]["data"] == {"expected": "text/plain", "actual": "application/json"}

    disallowed_slot = await rpc(client, "/im/rpc", "attachment.create_slot", {}, token=token)
    await client.put(f"/objects/upload/{disallowed_slot['result']['slot_id']}", headers=disallowed_slot["result"]["upload_headers"], content=data)
    disallowed = await rpc(
        client,
        "/im/rpc",
        "attachment.commit_object",
        {
            "slot_id": disallowed_slot["result"]["slot_id"],
            "commit_token": disallowed_slot["result"]["commit_token"],
            "content_type": "application/x-msdownload",
        },
        token=token,
    )
    assert disallowed["error"]["message"] == "attachment_content_type_not_allowed"


@pytest.mark.asyncio
async def test_attachment_expiry_quota_and_cleanup(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=generate_ed25519_private_key_pem(),
            allow_unsigned_peer_dev=True,
            max_attachment_bytes=4,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as limited_client:
        _, token = await register(limited_client, "att-limit")

        too_large_slot_request = await rpc(limited_client, "/im/rpc", "attachment.create_slot", {"expected_size": 5}, token=token)
        assert too_large_slot_request["error"]["message"] == "attachment_too_large"

        too_large_slot = await rpc(limited_client, "/im/rpc", "attachment.create_slot", {}, token=token)
        too_large_upload = await limited_client.put(
            f"/objects/upload/{too_large_slot['result']['slot_id']}",
            headers=too_large_slot["result"]["upload_headers"],
            content=b"12345",
        )
        assert too_large_upload.status_code == 400
        assert too_large_upload.json()["detail"] == "attachment_too_large"

        expired_slot = await rpc(limited_client, "/im/rpc", "attachment.create_slot", {}, token=token)
        with app.state.store.connect() as conn:
            conn.execute(
                "UPDATE attachment_slots SET expires_at = ? WHERE slot_id = ?",
                ("2000-01-01T00:00:00+00:00", expired_slot["result"]["slot_id"]),
            )
        expired_upload = await limited_client.put(
            f"/objects/upload/{expired_slot['result']['slot_id']}",
            headers=expired_slot["result"]["upload_headers"],
            content=b"1234",
        )
        assert expired_upload.status_code == 400
        assert expired_upload.json()["detail"] == "slot_expired"

        expired_commit_slot = await rpc(limited_client, "/im/rpc", "attachment.create_slot", {}, token=token)
        await limited_client.put(
            f"/objects/upload/{expired_commit_slot['result']['slot_id']}",
            headers=expired_commit_slot["result"]["upload_headers"],
            content=b"1234",
        )
        with app.state.store.connect() as conn:
            conn.execute(
                "UPDATE attachment_slots SET expires_at = ? WHERE slot_id = ?",
                ("2000-01-01T00:00:00+00:00", expired_commit_slot["result"]["slot_id"]),
            )
        expired_commit = await rpc(
            limited_client,
            "/im/rpc",
            "attachment.commit_object",
            {"slot_id": expired_commit_slot["result"]["slot_id"], "commit_token": expired_commit_slot["result"]["commit_token"]},
            token=token,
        )
        assert expired_commit["error"]["message"] == "slot_expired"

        slot = await rpc(limited_client, "/im/rpc", "attachment.create_slot", {"content_type": "text/plain"}, token=token)
        await limited_client.put(f"/objects/upload/{slot['result']['slot_id']}", headers=slot["result"]["upload_headers"], content=b"1234")
        committed = await rpc(
            limited_client,
            "/im/rpc",
            "attachment.commit_object",
            {"slot_id": slot["result"]["slot_id"], "commit_token": slot["result"]["commit_token"]},
            token=token,
        )
        ticket = await rpc(limited_client, "/im/rpc", "attachment.get_download_ticket", {"object_id": committed["result"]["object_id"]}, token=token)
        with app.state.store.connect() as conn:
            conn.execute("UPDATE download_tickets SET expires_at = ? WHERE ticket = ?", ("2000-01-01T00:00:00+00:00", ticket["result"]["ticket"]))
        expired_download = await limited_client.get(f"/objects/{committed['result']['object_id']}", params={"ticket": ticket["result"]["ticket"]})
        assert expired_download.status_code == 404
        assert expired_download.json()["detail"] == "object_not_found"

    cleanup = cleanup_expired_attachments(app.state.store)
    assert cleanup["expired_slots"] >= 2
    assert cleanup["expired_download_tickets"] >= 1


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
