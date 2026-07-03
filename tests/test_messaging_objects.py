from __future__ import annotations

import pytest
import httpx
import jcs
import json
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import base64
from datetime import datetime, timezone
import time
import urllib.parse

import awiki_open_server.services as services
from awiki_open_server.app.main import create_app
from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import content_digest
from awiki_open_server.service_identity import (
    build_service_did_document,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
    verify_peer_http_signature,
)
from awiki_open_server.shared.errors import InvalidParams
from tests.conftest import rpc


async def register(client, handle: str):
    data = await rpc(client, "/did-auth/rpc", "register", {"handle": handle})
    return data["result"]["did"], data["result"]["token"]


async def register_with_key(client, handle: str):
    did = f"did:wba:testserver:users:{handle}"
    private_key, document = did_keypair_document(did)
    data = await rpc(client, "/did-auth/rpc", "register", {"handle": handle, "did_document": document})
    return data["result"]["did"], data["result"]["token"], private_key, document


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _multikey(public_key: ed25519.Ed25519PublicKey) -> str:
    import base58

    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def did_keypair_document(did: str) -> tuple[ed25519.Ed25519PrivateKey, dict]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    key_id = f"{did}#key-1"
    return private_key, {
        "id": did,
        "verificationMethod": [
            {
                "id": key_id,
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": _multikey(private_key.public_key()),
            }
        ],
        "authentication": [key_id],
        "service": [
            {
                "id": f"{did}#anp-message",
                "type": "ANPMessageService",
                "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                "serviceDid": "did:wba:awiki.info",
                "profiles": ["anp.direct.base.v1"],
                "securityProfiles": ["transport-protected"],
            }
        ],
    }


def test_service_identity_custom_document_must_match_public_service_shape():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document("did:wba:rwiki.cn", "https://rwiki.cn/anp-im/rpc", private_key_pem)
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
        document_json=json.dumps(document),
    )
    assert identity is not None
    assert identity.did_document["service"][0]["authSchemes"] == ["bearer", "didwba"]

    wrong_endpoint = {**document, "service": [{**document["service"][0], "serviceEndpoint": "https://wrong.example/anp-im/rpc"}]}
    with pytest.raises(InvalidParams) as endpoint_error:
        service_identity_from_settings(
            service_did="did:wba:rwiki.cn",
            endpoint="https://rwiki.cn/anp-im/rpc",
            private_key_pem=private_key_pem,
            document_json=json.dumps(wrong_endpoint),
        )
    assert str(endpoint_error.value) == "service_did_document_endpoint_mismatch"

    wrong_auth = {**document, "service": [{**document["service"][0], "authSchemes": ["http-message-signatures"]}]}
    with pytest.raises(InvalidParams) as auth_error:
        service_identity_from_settings(
            service_did="did:wba:rwiki.cn",
            endpoint="https://rwiki.cn/anp-im/rpc",
            private_key_pem=private_key_pem,
            document_json=json.dumps(wrong_auth),
        )
    assert str(auth_error.value) == "service_did_document_auth_schemes_mismatch"


def origin_proof(meta: dict, body: dict, private_key: ed25519.Ed25519PrivateKey | None = None, method: str = "direct.send") -> dict:
    private_key = private_key or ed25519.Ed25519PrivateKey.generate()
    key_id = f"{meta['sender_did']}#key-1"
    digest = content_digest(jcs.canonicalize({"method": method, "meta": meta, "body": body}))
    created = int(time.time())
    signature_input = (
        'sig1=("@method" "@target-uri" "content-digest");'
        f'created={created};expires={created + 300};keyid="{key_id}"'
    )
    target = meta["target"]
    proof_base = "\n".join(
        [
            f'"@method": {method}',
            f'"@target-uri": anp://{target["kind"]}/{urllib.parse.quote(target["did"], safe="-._~")}',
            f'"content-digest": {digest}',
            f'"@signature-params": {signature_input.split("=", 1)[1].strip()}',
        ]
    ).encode()
    return {
        "contentDigest": digest,
        "signatureInput": signature_input,
        "signature": f"sig1=:{_b64(private_key.sign(proof_base))}:",
    }


def remote_direct_result(payload: dict, *, target_did: str | None = None, overrides: dict | None = None) -> dict:
    meta = payload["params"]["meta"]
    result = {
        "accepted": True,
        "delivery_state": "accepted",
        "final_acceptance": True,
        "message_id": meta["message_id"],
        "operation_id": meta["operation_id"],
        "target_did": target_did or meta["target"]["did"],
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }
    if overrides:
        result.update(overrides)
    return {"jsonrpc": "2.0", "result": result, "id": payload["id"]}


@pytest.mark.asyncio
async def test_direct_group_participant_and_public_surface(client):
    alice_did, alice_token = await register(client, "alice")
    bob_did, bob_token = await register(client, "bob")

    caps = await rpc(client, "/im/rpc", "anp.get_capabilities", token=alice_token)
    assert "anp.group.base.v1" in caps["result"]["supported_profiles"]
    assert caps["result"]["features"]["group_participant"]["management"] is False

    sent = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": bob_did, "text": "hi"}, token=alice_token)
    assert sent["result"]["recipient_did"] == bob_did
    assert sent["result"]["accepted"] is True

    history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice_did}, token=bob_token)
    assert history["result"]["messages"][0]["body"]["text"] == "hi"
    assert history["result"]["messages"][0]["content"] == "hi"
    assert history["result"]["messages"][0]["receiver_did"] == bob_did

    delta = await rpc(client, "/im/rpc", "sync.delta", {"after_event_seq": 0}, token=bob_token)
    assert delta["result"]["events"][0]["event_type"] == "direct.message.created"

    thread = await rpc(client, "/im/rpc", "sync.thread_after", {"thread_id": f"direct:{alice_did}", "after_server_seq": 0}, token=bob_token)
    assert thread["result"]["messages"][0]["message_id"] == sent["result"]["message_id"]

    read = await rpc(client, "/im/rpc", "read_state.mark_read", {"thread_id": f"direct:{alice_did}", "read_up_to_seq": sent["result"]["server_seq"]}, token=bob_token)
    assert read["result"]["read_up_to_seq"] == sent["result"]["server_seq"]

    marked = await rpc(client, "/im/rpc", "inbox.mark_read", {"message_ids": [sent["result"]["message_id"]]}, token=bob_token)
    assert marked["result"]["updated_count"] == 1

    group_did = "did:wba:testserver:groups:open"
    joined = await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    assert joined["result"]["joined"] is True

    group_msg = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "group hi"}, token=alice_token)
    assert group_msg["result"]["group_did"] == group_did
    assert group_msg["result"]["accepted"] is True
    assert group_msg["result"]["delivery_state"] == "accepted"
    assert group_msg["result"]["final_acceptance"] is True
    assert group_msg["result"]["group_event_seq"] == str(group_msg["result"]["server_seq"])
    assert group_msg["result"]["group_state_version"] == str(group_msg["result"]["server_seq"])
    assert group_msg["result"]["accepted_at"]

    messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert messages["result"]["messages"][0]["body"]["text"] == "group hi"
    assert messages["result"]["messages"][0]["content"] == "group hi"

    denied = await rpc(client, "/im/rpc", "group.create", {"display_name": "nope"}, token=alice_token)
    assert denied["error"]["message"] == "not_supported"

    public_denied = await rpc(client, "/anp-im/rpc", "direct.get_history", {"peer_did": bob_did}, token=alice_token)
    assert public_denied["error"]["message"] == "method_not_found"

    for method in ["group.add", "group.remove", "group.update_profile", "group.update_policy"]:
        response = await rpc(client, "/im/rpc", method, {"group_did": group_did}, token=alice_token)
        assert response["error"]["message"] == "not_supported"


@pytest.mark.asyncio
async def test_inbox_mark_read_updates_owner_view_and_filters_default_inbox(client):
    alice_did, alice_token = await register(client, "read-alice")
    bob_did, bob_token = await register(client, "read-bob")

    sent = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": bob_did, "text": "read me"}, token=alice_token)
    message_id = sent["result"]["message_id"]

    before = await rpc(client, "/im/rpc", "inbox.get", token=bob_token)
    assert [message["message_id"] for message in before["result"]["messages"]] == [message_id]
    assert before["result"]["messages"][0]["is_read"] is False
    assert before["result"]["messages"][0]["read_at"] is None

    alice_mark = await rpc(client, "/im/rpc", "inbox.mark_read", {"message_ids": [message_id]}, token=alice_token)
    assert alice_mark["result"]["updated_count"] == 1

    bob_still_unread = await rpc(client, "/im/rpc", "inbox.get", token=bob_token)
    assert [message["message_id"] for message in bob_still_unread["result"]["messages"]] == [message_id]
    assert bob_still_unread["result"]["messages"][0]["is_read"] is False

    marked = await rpc(client, "/im/rpc", "inbox.mark_read", {"message_ids": [message_id]}, token=bob_token)
    assert marked["result"]["updated_count"] == 1
    assert marked["result"]["message_ids"] == [message_id]
    assert marked["result"]["read_at"]

    default_after = await rpc(client, "/im/rpc", "inbox.get", token=bob_token)
    assert default_after["result"]["messages"] == []

    include_read = await rpc(client, "/im/rpc", "inbox.get", {"include_read": True}, token=bob_token)
    assert [message["message_id"] for message in include_read["result"]["messages"]] == [message_id]
    assert include_read["result"]["messages"][0]["is_read"] is True
    assert include_read["result"]["messages"][0]["read_at"] == marked["result"]["read_at"]

    history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice_did}, token=bob_token)
    assert history["result"]["messages"][0]["message_id"] == message_id
    assert history["result"]["messages"][0]["is_read"] is True
    assert history["result"]["messages"][0]["read_at"] == marked["result"]["read_at"]

    repeat = await rpc(client, "/im/rpc", "inbox.mark_read", {"message_id": message_id}, token=bob_token)
    assert repeat["result"]["updated_count"] == 0
    assert repeat["result"]["message_ids"] == [message_id]

    missing = await rpc(client, "/im/rpc", "inbox.mark_read", {"message_ids": ["msg-not-visible"]}, token=bob_token)
    assert missing["result"]["updated_count"] == 0
    assert missing["result"]["message_ids"] == []

    public_denied = await rpc(client, "/anp-im/rpc", "inbox.mark_read", {"message_ids": [message_id]}, token=bob_token)
    assert public_denied["error"]["message"] == "method_not_found"


@pytest.mark.asyncio
async def test_local_view_params_validate_owner_and_support_pagination(client):
    alice_did, alice_token = await register(client, "view-alice")
    bob_did, bob_token = await register(client, "view-bob")

    first = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": bob_did, "text": "one"}, token=alice_token)
    second = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": bob_did, "text": "two"}, token=alice_token)
    third = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": bob_did, "text": "three"}, token=alice_token)

    inbox_page = await rpc(
        client,
        "/im/rpc",
        "inbox.get",
        {
            "meta": {"sender_did": bob_did, "profile": "anp.inbox.local.v1", "security_profile": "transport-protected"},
            "body": {"user_did": bob_did, "limit": 1, "skip": 1},
        },
        token=bob_token,
    )
    assert [message["message_id"] for message in inbox_page["result"]["messages"]] == [second["result"]["message_id"]]

    history_after_first = await rpc(
        client,
        "/im/rpc",
        "direct.get_history",
        {
            "meta": {"sender_did": bob_did, "profile": "anp.direct.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob_did,
                "peer_did": alice_did,
                "since_seq": str(first["result"]["server_seq"]),
                "limit": 10,
            },
        },
        token=bob_token,
    )
    assert [message["message_id"] for message in history_after_first["result"]["messages"]] == [
        second["result"]["message_id"],
        third["result"]["message_id"],
    ]

    history_since_priority = await rpc(
        client,
        "/im/rpc",
        "direct.get_history",
        {
            "user_did": bob_did,
            "peer_did": alice_did,
            "since": "0",
            "since_seq": str(second["result"]["server_seq"]),
        },
        token=bob_token,
    )
    assert [message["message_id"] for message in history_since_priority["result"]["messages"]] == [third["result"]["message_id"]]

    history_skip = await rpc(
        client,
        "/im/rpc",
        "direct.get_history",
        {"user_did": bob_did, "peer_did": alice_did, "limit": 1, "skip": 1},
        token=bob_token,
    )
    assert [message["message_id"] for message in history_skip["result"]["messages"]] == [second["result"]["message_id"]]

    inbox_owner_mismatch = await rpc(client, "/im/rpc", "inbox.get", {"user_did": alice_did}, token=bob_token)
    assert inbox_owner_mismatch["error"]["message"] == "inbox.user_did_mismatch"

    inbox_sender_mismatch = await rpc(
        client,
        "/im/rpc",
        "inbox.get",
        {"meta": {"sender_did": alice_did}, "body": {"user_did": bob_did}},
        token=bob_token,
    )
    assert inbox_sender_mismatch["error"]["message"] == "inbox.sender_did_mismatch"

    mark_owner_mismatch = await rpc(
        client,
        "/im/rpc",
        "inbox.mark_read",
        {"user_did": alice_did, "message_ids": [third["result"]["message_id"]]},
        token=bob_token,
    )
    assert mark_owner_mismatch["error"]["message"] == "inbox.user_did_mismatch"

    invalid_since = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice_did, "since_seq": "bad"}, token=bob_token)
    assert invalid_since["error"]["message"] == "direct.history_since_seq_invalid"

    too_large = await rpc(client, "/im/rpc", "inbox.get", {"limit": 101}, token=bob_token)
    assert too_large["error"]["message"] == "limit_too_large"

    group_deprecated = await rpc(client, "/im/rpc", "direct.get_history", {"group_did": "did:wba:testserver:groups:open"}, token=bob_token)
    assert group_deprecated["error"]["message"] == "direct.history_group_path_deprecated"

    public_denied = await rpc(client, "/anp-im/rpc", "inbox.get", {"limit": 1}, token=bob_token)
    assert public_denied["error"]["message"] == "method_not_found"


@pytest.mark.asyncio
async def test_group_participant_local_views_require_membership(client):
    alice_did, alice_token = await register(client, "group-member-alice")
    bob_did, bob_token = await register(client, "group-member-bob")
    group_did = "did:wba:testserver:groups:open"

    info = await rpc(client, "/im/rpc", "group.get_info", {"group_did": group_did}, token=bob_token)
    assert info["result"]["group_did"] == group_did

    bob_members_denied = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=bob_token)
    assert bob_members_denied["error"]["message"] == "group.not_member"

    bob_messages_denied = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=bob_token)
    assert bob_messages_denied["error"]["message"] == "group.not_member"

    bob_leave_denied = await rpc(client, "/im/rpc", "group.leave", {"group_did": group_did}, token=bob_token)
    assert bob_leave_denied["error"]["message"] == "group.not_member"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    sent = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "member only"}, token=alice_token)
    assert sent["result"]["accepted"] is True

    alice_members = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=alice_token)
    assert [member["member_did"] for member in alice_members["result"]] == [alice_did]

    alice_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert [message["message_id"] for message in alice_messages["result"]["messages"]] == [sent["result"]["message_id"]]

    bob_messages_still_denied = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=bob_token)
    assert bob_messages_still_denied["error"]["message"] == "group.not_member"

    bob_thread_denied = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {"thread": {"kind": "group", "group_did": group_did}, "after_server_seq": 0},
        token=bob_token,
    )
    assert bob_thread_denied["error"]["message"] == "group.not_member"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=bob_token)
    bob_members = await rpc(client, "/im/rpc", "group.list_members", {"group_did": group_did}, token=bob_token)
    assert {member["member_did"] for member in bob_members["result"]} == {alice_did, bob_did}

    bob_thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {"thread": {"kind": "group", "group_did": group_did}, "after_server_seq": 0},
        token=bob_token,
    )
    assert [message["message_id"] for message in bob_thread["result"]["messages"]] == [sent["result"]["message_id"]]

    left = await rpc(client, "/im/rpc", "group.leave", {"group_did": group_did}, token=alice_token)
    assert left["result"]["left"] is True

    alice_after_leave_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert alice_after_leave_messages["error"]["message"] == "group.not_member"

    alice_send_after_leave = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "after leave"}, token=alice_token)
    assert alice_send_after_leave["error"]["message"] == "not_group_member"


@pytest.mark.asyncio
async def test_group_local_views_support_anp_params_and_pagination(client):
    alice_did, alice_token = await register(client, "group-page-alice")
    bob_did, bob_token = await register(client, "group-page-bob")
    group_did = "did:wba:testserver:groups:open"

    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=bob_token)

    first = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "first"}, token=alice_token)
    second = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "second"}, token=alice_token)
    third = await rpc(client, "/im/rpc", "group.send", {"group_did": group_did, "text": "third"}, token=bob_token)

    listed = await rpc(
        client,
        "/im/rpc",
        "group.list",
        {
            "meta": {"profile": "anp.group.local.v1", "sender_did": alice_did},
            "body": {"user_did": alice_did, "limit": 1},
        },
        token=alice_token,
    )
    assert [group["group_did"] for group in listed["result"]] == [group_did]

    members = await rpc(
        client,
        "/im/rpc",
        "group.list_members",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {"user_did": alice_did, "group_did": group_did, "limit": 1},
        },
        token=alice_token,
    )
    assert [member["member_did"] for member in members["result"]] == [alice_did]

    first_page = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {
                "user_did": alice_did,
                "group_did": group_did,
                "since_seq": str(first["result"]["server_seq"]),
                "limit": 1,
            },
        },
        token=alice_token,
    )
    assert [message["message_id"] for message in first_page["result"]["messages"]] == [second["result"]["message_id"]]
    assert first_page["result"]["next_since_seq"] == str(second["result"]["server_seq"])
    assert first_page["result"]["total"] == 2
    assert first_page["result"]["has_more"] is True

    page = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {
                "user_did": alice_did,
                "group_did": group_did,
                "since_seq": str(first["result"]["server_seq"]),
                "skip": 1,
                "limit": 1,
            },
        },
        token=alice_token,
    )
    assert [message["message_id"] for message in page["result"]["messages"]] == [third["result"]["message_id"]]
    assert page["result"]["next_since_seq"] == str(third["result"]["server_seq"])
    assert page["result"]["total"] == 2
    assert page["result"]["has_more"] is False

    mismatch = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": bob_did,
                "target": {"kind": "group", "did": group_did},
            },
            "body": {"user_did": alice_did, "group_did": group_did},
        },
        token=alice_token,
    )
    assert mismatch["error"]["message"] == "group.local.sender_did_mismatch"

    target_mismatch = await rpc(
        client,
        "/im/rpc",
        "group.list_messages",
        {
            "meta": {
                "profile": "anp.group.local.v1",
                "sender_did": alice_did,
                "target": {"kind": "group", "did": "did:wba:testserver:groups:other"},
            },
            "body": {"user_did": alice_did, "group_did": group_did},
        },
        token=alice_token,
    )
    assert target_mismatch["error"]["message"] == "group.local_target_did_mismatch"

    invalid_since = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did, "since_seq": "bad"}, token=alice_token)
    assert invalid_since["error"]["message"] == "group.messages_since_seq_invalid"

    too_large = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did, "limit": 101}, token=alice_token)
    assert too_large["error"]["message"] == "limit_too_large"


@pytest.mark.asyncio
async def test_anp_envelope_on_public_rpc(client):
    alice_did, alice_token, alice_key, _ = await register_with_key(client, "anp-alice")
    bob_did, _ = await register(client, "anp-bob")

    caps = await rpc(
        client,
        "/anp-im/rpc",
        "anp.get_capabilities",
        {
            "meta": {
                "anp_version": "1.0",
                "profile": "anp.core.binding.v1",
                "security_profile": "transport-protected",
                "sender_did": alice_did,
                "operation_id": "op-cap",
                "created_at": "2026-07-02T00:00:00Z",
            },
            "auth": {},
            "body": {},
        },
        token=alice_token,
    )
    assert caps["result"]["features"]["cross_domain_direct"]["enabled"] is True
    assert caps["result"]["direct_e2ee"]["enabled"] is False

    meta = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice_did,
        "target": {"kind": "agent", "did": bob_did},
        "operation_id": "op-direct",
        "message_id": "msg-direct",
        "created_at": "2026-07-02T00:00:00Z",
        "content_type": "text/plain",
    }
    body = {"text": "hello via anp envelope"}
    sent = await rpc(
        client,
        "/anp-im/rpc",
        "direct.send",
        {
            "meta": meta,
            "auth": {"scheme": "community-dev-bearer", "origin_proof": origin_proof(meta, body, alice_key)},
            "body": body,
        },
        token=alice_token,
    )
    assert sent["result"]["message_id"] == "msg-direct"
    assert sent["result"]["recipient_did"] == bob_did


@pytest.mark.asyncio
async def test_local_direct_to_remote_did_discovers_anp_service_and_posts(client, monkeypatch):
    alice_did, alice_token, alice_key, _ = await register_with_key(client, "remote-alice")
    remote_did = "did:wba:awiki.info:users:bob"
    captured: dict = {}

    def fake_get_json(url: str):
        captured["did_url"] = url
        return {
            "id": remote_did,
            "service": [
                {
                    "id": f"{remote_did}#anp-message",
                    "type": "ANPMessageService",
                    "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                    "serviceDid": "did:wba:awiki.info",
                }
            ],
        }

    def fake_post_json(url: str, payload: dict, headers: dict | None = None, body_bytes: bytes | None = None):
        captured["post_url"] = url
        captured["payload"] = payload
        captured["headers"] = headers or {}
        return remote_direct_result(payload)

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    monkeypatch.setattr(services, "_http_post_json", fake_post_json)

    meta = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice_did,
        "target": {"kind": "agent", "did": remote_did},
        "operation_id": "op-remote-out",
        "message_id": "msg-remote-out",
        "created_at": "2026-07-03T00:00:00Z",
        "content_type": "text/plain",
    }
    body = {"text": "hello awiki"}
    proof = origin_proof(meta, body, alice_key)
    sent = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {
            "meta": meta,
            "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": proof},
            "body": body,
            "client": {"response_mode": "wait-final"},
        },
        token=alice_token,
    )
    assert sent["result"]["sender_did"] == alice_did
    assert sent["result"]["recipient_did"] == remote_did
    assert sent["result"]["delivery_state"] == "accepted"
    assert sent["result"]["final_acceptance"] is True
    assert captured["did_url"] == "https://awiki.info/users/bob/did.json"
    assert captured["post_url"] == "https://awiki.info/anp-im/rpc"
    assert captured["payload"]["method"] == "direct.send"
    assert captured["payload"]["params"]["meta"]["sender_did"] == alice_did
    assert captured["payload"]["params"]["meta"]["target"]["did"] == remote_did
    assert captured["payload"]["params"]["body"]["text"] == "hello awiki"
    assert captured["payload"]["params"]["auth"]["origin_proof"] == proof
    assert captured["headers"]["x-anp-source-service-did"] == "did:wba:testserver"

    history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": remote_did}, token=alice_token)
    assert history["result"]["messages"][0]["body"]["text"] == "hello awiki"


@pytest.mark.asyncio
async def test_remote_direct_requires_origin_proof(client, monkeypatch):
    alice_did, alice_token, _, _ = await register_with_key(client, "remote-no-proof")
    remote_did = "did:wba:awiki.info:users:bob"

    def fake_get_json(url: str):
        return {
            "id": remote_did,
            "service": [
                {
                    "id": f"{remote_did}#anp-message",
                    "type": "ANPMessageService",
                    "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                    "serviceDid": "did:wba:awiki.info",
                }
            ],
        }

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    rejected = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {
            "meta": {
                "sender_did": alice_did,
                "target": {"kind": "agent", "did": remote_did},
                "operation_id": "op-no-proof",
                "message_id": "msg-no-proof",
                "content_type": "text/plain",
            },
            "auth": {"scheme": "anp-rfc9421-origin-proof-v1"},
            "body": {"text": "no proof"},
        },
        token=alice_token,
    )
    assert rejected["error"]["message"] == "missing_origin_proof"


@pytest.mark.asyncio
async def test_remote_direct_rejects_invalid_origin_proof_signature(client, monkeypatch):
    alice_did, alice_token, _, _ = await register_with_key(client, "remote-bad-proof")
    wrong_key = ed25519.Ed25519PrivateKey.generate()
    remote_did = "did:wba:awiki.info:users:bob"

    def fake_get_json(url: str):
        return {
            "id": remote_did,
            "service": [
                {
                    "id": f"{remote_did}#anp-message",
                    "type": "ANPMessageService",
                    "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                    "serviceDid": "did:wba:awiki.info",
                }
            ],
        }

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    meta = {
        "sender_did": alice_did,
        "target": {"kind": "agent", "did": remote_did},
        "operation_id": "op-bad-proof",
        "message_id": "msg-bad-proof",
        "content_type": "text/plain",
    }
    body = {"text": "bad proof"}
    rejected = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {
            "meta": meta,
            "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body, wrong_key)},
            "body": body,
        },
        token=alice_token,
    )
    assert rejected["error"]["message"] == "invalid_origin_proof_signature"


@pytest.mark.asyncio
async def test_remote_direct_rejects_message_service_incompatible_result(client, monkeypatch):
    alice_did, alice_token, alice_key, _ = await register_with_key(client, "remote-bad-result")
    remote_did = "did:wba:awiki.info:users:bob"

    def fake_get_json(url: str):
        return {
            "id": remote_did,
            "service": [
                {
                    "id": f"{remote_did}#anp-message",
                    "type": "ANPMessageService",
                    "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                    "serviceDid": "did:wba:awiki.info",
                }
            ],
        }

    def fake_post_json(url: str, payload: dict, headers: dict | None = None, body_bytes: bytes | None = None):
        return remote_direct_result(payload, overrides={"target_did": "did:wba:awiki.info:users:other"})

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    monkeypatch.setattr(services, "_http_post_json", fake_post_json)
    meta = {
        "sender_did": alice_did,
        "target": {"kind": "agent", "did": remote_did},
        "operation_id": "op-bad-result",
        "message_id": "msg-bad-result",
        "content_type": "text/plain",
    }
    body = {"text": "bad result"}
    rejected = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {
            "meta": meta,
            "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body, alice_key)},
            "body": body,
        },
        token=alice_token,
    )
    assert rejected["error"]["message"] == "remote_direct_target_did_mismatch"


@pytest.mark.asyncio
async def test_remote_direct_with_service_identity_adds_verifiable_http_signature(tmp_path, monkeypatch):
    private_key = generate_ed25519_private_key_pem()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=private_key,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as signed_client:
        alice_did, alice_token, alice_key, _ = await register_with_key(signed_client, "signed-remote")
        remote_did = "did:wba:awiki.info:users:bob"
        captured: dict = {}

        def fake_get_json(url: str):
            return {
                "id": remote_did,
                "service": [
                    {
                        "id": f"{remote_did}#anp-message",
                        "type": "ANPMessageService",
                        "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                        "serviceDid": "did:wba:awiki.info",
                    }
                ],
            }

        def fake_post_json(url: str, payload: dict, headers: dict | None = None, body_bytes: bytes | None = None):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers or {}
            captured["body_bytes"] = body_bytes or b""
            return remote_direct_result(payload)

        monkeypatch.setattr(services, "_http_get_json", fake_get_json)
        monkeypatch.setattr(services, "_http_post_json", fake_post_json)

        meta = {
            "sender_did": alice_did,
            "target": {"kind": "agent", "did": remote_did},
            "operation_id": "op-signed",
            "message_id": "msg-signed",
            "content_type": "text/plain",
        }
        body = {"text": "signed hello"}
        response = await rpc(
            signed_client,
            "/im/rpc",
            "direct.send",
            {
                "meta": meta,
                "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body, alice_key)},
                "body": body,
            },
            token=alice_token,
        )
        assert response["result"]["delivery_state"] == "accepted"
        assert captured["headers"]["x-anp-source-service-did"] == "did:wba:testserver"
        assert "Signature-Input" in captured["headers"]
        assert "Signature" in captured["headers"]
        assert "Content-Digest" in captured["headers"]
        key_id = verify_peer_http_signature(
            service_did_document=app.state.service_identity.did_document,
            method="POST",
            url=captured["url"],
            headers={**captured["headers"], "Content-Type": "application/json"},
            body=captured["body_bytes"],
        )
        assert key_id == "did:wba:testserver#key-1"


@pytest.mark.asyncio
async def test_public_anp_direct_requires_local_recipient(client, monkeypatch):
    alice_did, alice_token = await register(client, "public-local")
    remote_did = "did:wba:awiki.info:users:remote"
    remote_key, remote_doc = did_keypair_document(remote_did)

    def fake_get_json(url: str):
        assert url == "https://awiki.info/users/remote/did.json"
        return remote_doc

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)

    reject_meta = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": remote_did,
        "target": {"kind": "agent", "did": "did:wba:other.example:users:not-here"},
        "operation_id": "op-remote-reject",
        "message_id": "msg-remote-reject",
        "created_at": "2026-07-03T00:00:00Z",
        "content_type": "text/plain",
    }
    reject_body = {"text": "should not relay"}
    rejected = await rpc(
        client,
        "/anp-im/rpc",
        "direct.send",
        {
            "meta": reject_meta,
            "auth": {"scheme": "community-dev-bearer", "origin_proof": origin_proof(reject_meta, reject_body, remote_key)},
            "body": reject_body,
        },
    )
    assert rejected["error"]["message"] == "recipient_not_local"

    accept_meta = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": remote_did,
        "target": {"kind": "agent", "did": alice_did},
        "operation_id": "op-remote-in",
        "message_id": "msg-remote-in",
        "created_at": "2026-07-03T00:00:00Z",
        "content_type": "text/plain",
    }
    accept_body = {"text": "hello open server"}
    accepted = await rpc(
        client,
        "/anp-im/rpc",
        "direct.send",
        {
            "meta": accept_meta,
            "auth": {"scheme": "community-dev-bearer", "origin_proof": origin_proof(accept_meta, accept_body, remote_key)},
            "body": accept_body,
        },
    )
    assert accepted["result"]["message_id"] == "msg-remote-in"
    inbox = await rpc(client, "/im/rpc", "inbox.get", token=alice_token)
    assert inbox["result"]["messages"][0]["body"]["text"] == "hello open server"


@pytest.mark.asyncio
async def test_public_anp_direct_accepts_signed_peer_request(tmp_path, monkeypatch):
    local_private_key = generate_ed25519_private_key_pem()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=local_private_key,
            allow_unsigned_peer_dev=False,
        )
    )
    remote_private_key = generate_ed25519_private_key_pem()
    remote_doc = build_service_did_document("did:wba:awiki.info", "https://awiki.info/anp-im/rpc", remote_private_key)
    remote_user_did = "did:wba:awiki.info:users:remote"
    remote_user_key, remote_user_doc = did_keypair_document(remote_user_did)
    remote_identity = service_identity_from_settings(
        service_did="did:wba:awiki.info",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=remote_private_key,
        document_json=None,
    )

    def fake_get_json(url: str):
        if url == "https://awiki.info/users/remote/did.json":
            return remote_user_doc
        assert url == "https://awiki.info/.well-known/did.json"
        return remote_doc

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as signed_client:
        alice_did, alice_token = await register(signed_client, "signed-inbound")
        meta = {
            "anp_version": "1.0",
            "profile": "anp.direct.base.v1",
            "security_profile": "transport-protected",
            "sender_did": remote_user_did,
            "target": {"kind": "agent", "did": alice_did},
            "operation_id": "op-peer-in",
            "message_id": "msg-peer-in",
            "created_at": "2026-07-03T00:00:00Z",
            "content_type": "text/plain",
        }
        body_payload = {"text": "signed inbound"}
        payload = {
            "jsonrpc": "2.0",
            "method": "direct.send",
            "params": {
                "meta": meta,
                "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body_payload, remote_user_key)},
                "body": body_payload,
                "client": {"response_mode": "wait-final"},
            },
            "id": "peer",
        }
        body = __import__("json").dumps(payload).encode()
        base_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:awiki.info"}
        signature_headers = remote_identity.sign_headers("http://testserver/anp-im/rpc", "POST", base_headers, body)
        response = await signed_client.post("/anp-im/rpc", content=body, headers={**base_headers, **signature_headers})
        data = response.json()
        assert data["result"]["message_id"] == "msg-peer-in"
        inbox = await rpc(signed_client, "/im/rpc", "inbox.get", token=alice_token)
        assert inbox["result"]["messages"][0]["body"]["text"] == "signed inbound"


@pytest.mark.asyncio
async def test_public_anp_direct_verifies_signature_against_public_base_url(tmp_path, monkeypatch):
    local_private_key = generate_ed25519_private_key_pem()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="https://rwiki.cn",
            service_did="did:wba:rwiki.cn",
            did_domain="rwiki.cn",
            service_private_key_pem=local_private_key,
            allow_unsigned_peer_dev=False,
        )
    )
    remote_private_key = generate_ed25519_private_key_pem()
    remote_doc = build_service_did_document("did:wba:awiki.info", "https://awiki.info/anp-im/rpc", remote_private_key)
    remote_user_did = "did:wba:awiki.info:users:remote"
    remote_user_key, remote_user_doc = did_keypair_document(remote_user_did)
    remote_identity = service_identity_from_settings(
        service_did="did:wba:awiki.info",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=remote_private_key,
        document_json=None,
    )

    def fake_get_json(url: str):
        if url == "https://awiki.info/users/remote/did.json":
            return remote_user_doc
        assert url == "https://awiki.info/.well-known/did.json"
        return remote_doc

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal-testserver") as signed_client:
        local = await rpc(signed_client, "/did-auth/rpc", "register", {"handle": "signed-public-url"})
        meta = {
            "sender_did": remote_user_did,
            "target": {"kind": "agent", "did": local["result"]["did"]},
            "operation_id": "op-public-url",
            "message_id": "msg-public-url",
            "content_type": "text/plain",
        }
        body_payload = {"text": "signed against public URL"}
        payload = {
            "jsonrpc": "2.0",
            "method": "direct.send",
            "params": {
                "meta": meta,
                "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body_payload, remote_user_key)},
                "body": body_payload,
            },
            "id": "peer-public-url",
        }
        body = __import__("json").dumps(payload).encode()
        base_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:awiki.info"}
        signature_headers = remote_identity.sign_headers("https://rwiki.cn/anp-im/rpc", "POST", base_headers, body)
        response = await signed_client.post("/anp-im/rpc", content=body, headers={**base_headers, **signature_headers})
        data = response.json()
        assert data["result"]["message_id"] == "msg-public-url"


@pytest.mark.asyncio
async def test_public_anp_group_join_requires_origin_and_peer_signature(tmp_path, monkeypatch):
    local_private_key = generate_ed25519_private_key_pem()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
            service_private_key_pem=local_private_key,
            allow_unsigned_peer_dev=False,
        )
    )
    remote_private_key = generate_ed25519_private_key_pem()
    remote_doc = build_service_did_document("did:wba:awiki.info", "https://awiki.info/anp-im/rpc", remote_private_key)
    remote_user_did = "did:wba:awiki.info:users:group-joiner"
    remote_user_key, remote_user_doc = did_keypair_document(remote_user_did)
    remote_identity = service_identity_from_settings(
        service_did="did:wba:awiki.info",
        endpoint="https://awiki.info/anp-im/rpc",
        private_key_pem=remote_private_key,
        document_json=None,
    )

    def fake_get_json(url: str):
        if url == "https://awiki.info/users/group-joiner/did.json":
            return remote_user_doc
        assert url == "https://awiki.info/.well-known/did.json"
        return remote_doc

    monkeypatch.setattr(services, "_http_get_json", fake_get_json)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as signed_client:
        group_did = "did:wba:testserver:groups:open"
        meta = {
            "anp_version": "1.0",
            "profile": "anp.group.base.v1",
            "security_profile": "transport-protected",
            "sender_did": remote_user_did,
            "target": {"kind": "group", "did": group_did},
            "operation_id": "op-group-join",
            "created_at": "2026-07-03T00:00:00Z",
            "content_type": "application/json",
        }
        body_payload = {"group_did": group_did}
        unsigned_payload = {
            "jsonrpc": "2.0",
            "method": "group.join",
            "params": {"meta": meta, "body": body_payload},
            "id": "group-join-unsigned",
        }
        unsigned_response = await signed_client.post("/anp-im/rpc", json=unsigned_payload)
        assert unsigned_response.json()["error"]["message"] == "missing_origin_proof"

        signed_payload = {
            "jsonrpc": "2.0",
            "method": "group.join",
            "params": {
                "meta": meta,
                "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body_payload, remote_user_key, method="group.join")},
                "body": body_payload,
            },
            "id": "group-join-signed",
        }
        raw_body = __import__("json").dumps(signed_payload).encode()
        base_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:awiki.info"}
        signature_headers = remote_identity.sign_headers("http://testserver/anp-im/rpc", "POST", base_headers, raw_body)
        response = await signed_client.post("/anp-im/rpc", content=raw_body, headers={**base_headers, **signature_headers})
        data = response.json()
        assert data["result"]["joined"] is True
        assert data["result"]["group_did"] == group_did
        assert data["result"]["member_did"] == remote_user_did


@pytest.mark.asyncio
async def test_anp_envelope_meta_required_fields_and_target_validation(client):
    alice, alice_token = await register(client, "meta-alice")
    bob, bob_token = await register(client, "meta-bob")
    charlie, _ = await register(client, "meta-charlie")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)

    flat = await rpc(client, "/im/rpc", "direct.send", {"to": bob, "text": "flat still works"}, token=alice_token)
    assert flat["result"]["accepted"] is True

    direct_meta = {
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "agent", "did": bob},
        "operation_id": "op-meta-direct",
        "message_id": "msg-meta-direct",
        "content_type": "text/plain",
    }
    direct_body = {"text": "valid direct envelope"}
    valid_direct = await rpc(client, "/im/rpc", "direct.send", {"meta": direct_meta, "body": direct_body}, token=alice_token)
    assert valid_direct["result"]["message_id"] == "msg-meta-direct"

    missing_message_id_meta = dict(direct_meta)
    missing_message_id_meta.pop("message_id")
    missing_message_id = await rpc(client, "/im/rpc", "direct.send", {"meta": missing_message_id_meta, "body": {"text": "missing msg"}}, token=alice_token)
    assert missing_message_id["error"]["message"] == "anp_meta_message_id_required"

    missing_content_type_meta = dict(direct_meta)
    missing_content_type_meta.pop("content_type")
    missing_content_type = await rpc(client, "/im/rpc", "direct.send", {"meta": missing_content_type_meta, "body": {"text": "missing content type"}}, token=alice_token)
    assert missing_content_type["error"]["message"] == "anp_meta_content_type_required"

    wrong_direct_kind_meta = {**direct_meta, "operation_id": "op-meta-direct-kind", "message_id": "msg-meta-direct-kind", "target": {"kind": "group", "did": bob}}
    wrong_direct_kind = await rpc(client, "/im/rpc", "direct.send", {"meta": wrong_direct_kind_meta, "body": {"text": "wrong kind"}}, token=alice_token)
    assert wrong_direct_kind["error"]["message"] == "anp_meta_target_kind_mismatch"

    wrong_direct_target_meta = {**direct_meta, "operation_id": "op-meta-direct-target", "message_id": "msg-meta-direct-target", "target": {"kind": "agent", "did": charlie}}
    wrong_direct_target = await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {"meta": wrong_direct_target_meta, "body": {"text": "wrong target"}, "recipient_did": bob},
        token=alice_token,
    )
    assert wrong_direct_target["error"]["message"] == "anp_meta_target_did_mismatch"

    bob_history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice}, token=bob_token)
    assert [message["message_id"] for message in bob_history["result"]["messages"]] == [
        flat["result"]["message_id"],
        "msg-meta-direct",
    ]

    group_meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "group", "did": group_did},
        "operation_id": "op-meta-group",
        "message_id": "msg-meta-group",
        "content_type": "text/plain",
    }
    group_body = {"text": "valid group envelope"}
    valid_group = await rpc(client, "/im/rpc", "group.send", {"meta": group_meta, "body": group_body}, token=alice_token)
    assert valid_group["result"]["message_id"] == "msg-meta-group"

    missing_operation_meta = dict(group_meta)
    missing_operation_meta.pop("operation_id")
    missing_operation = await rpc(client, "/im/rpc", "group.send", {"meta": missing_operation_meta, "body": {"text": "missing op"}}, token=alice_token)
    assert missing_operation["error"]["message"] == "anp_meta_operation_id_required"

    missing_group_content_type_meta = dict(group_meta)
    missing_group_content_type_meta.pop("content_type")
    missing_group_content_type = await rpc(client, "/im/rpc", "group.send", {"meta": missing_group_content_type_meta, "body": {"text": "missing group content type"}}, token=alice_token)
    assert missing_group_content_type["error"]["message"] == "anp_meta_content_type_required"

    wrong_group_target_meta = {**group_meta, "operation_id": "op-meta-group-target", "message_id": "msg-meta-group-target", "target": {"kind": "group", "did": "did:wba:testserver:groups:other"}}
    wrong_group_target = await rpc(
        client,
        "/im/rpc",
        "group.send",
        {"meta": wrong_group_target_meta, "body": {"text": "wrong group target"}, "group_did": group_did},
        token=alice_token,
    )
    assert wrong_group_target["error"]["message"] == "anp_meta_target_did_mismatch"

    group_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert [message["message_id"] for message in group_messages["result"]["messages"]] == ["msg-meta-group"]


@pytest.mark.asyncio
async def test_application_json_payload_shape_and_daemon_heartbeat_no_store(client):
    alice, alice_token = await register(client, "json-alice")
    bob, bob_token = await register(client, "json-bob")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)

    direct_meta = {
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "agent", "did": bob},
        "operation_id": "op-json-direct",
        "message_id": "msg-json-direct",
        "content_type": "application/json",
    }
    direct_body = {"payload": {"schema": "example.command.v1", "command": "ping"}}
    direct = await rpc(client, "/im/rpc", "direct.send", {"meta": direct_meta, "body": direct_body}, token=alice_token)
    assert direct["result"]["content_type"] == "application/json"
    assert direct["result"]["body"]["payload"]["command"] == "ping"

    history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice}, token=bob_token)
    assert history["result"]["messages"][0]["type"] == "json"
    assert history["result"]["messages"][0]["content_type"] == "application/json"
    assert history["result"]["messages"][0]["body"] == direct_body
    assert history["result"]["messages"][0]["content"]["schema"] == "example.command.v1"

    invalid_direct_meta = {**direct_meta, "operation_id": "op-json-direct-invalid", "message_id": "msg-json-direct-invalid"}
    invalid_direct = await rpc(client, "/im/rpc", "direct.send", {"meta": invalid_direct_meta, "body": {"text": "wrong shape"}}, token=alice_token)
    assert invalid_direct["error"]["message"] == "message_body_payload_object_required"

    group_meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "group", "did": group_did},
        "operation_id": "op-json-group",
        "message_id": "msg-json-group",
        "content_type": "application/json",
    }
    group_body = {"payload": {"schema": "example.group.event.v1", "state": "ready"}}
    group = await rpc(client, "/im/rpc", "group.send", {"meta": group_meta, "body": group_body}, token=alice_token)
    assert group["result"]["content_type"] == "application/json"
    assert group["result"]["body"] == group_body

    group_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert group_messages["result"]["messages"][0]["type"] == "json"
    assert group_messages["result"]["messages"][0]["content_type"] == "application/json"
    assert group_messages["result"]["messages"][0]["body"] == group_body
    assert group_messages["result"]["messages"][0]["content"]["schema"] == "example.group.event.v1"

    invalid_group_meta = {**group_meta, "operation_id": "op-json-group-invalid", "message_id": "msg-json-group-invalid"}
    invalid_group = await rpc(client, "/im/rpc", "group.send", {"meta": invalid_group_meta, "body": {"payload": "not-object"}}, token=alice_token)
    assert invalid_group["error"]["message"] == "message_body_payload_object_required"

    heartbeat_meta = {
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "agent", "did": bob},
        "operation_id": "op-heartbeat",
        "message_id": "msg-heartbeat",
        "content_type": "application/json",
    }
    heartbeat_body = {
        "payload": {
            "schema": "awiki.agent.status.v1",
            "status_scope": "daemon",
            "state": "ready",
            "message": "daemon heartbeat",
        }
    }
    heartbeat = await rpc(client, "/im/rpc", "direct.send", {"meta": heartbeat_meta, "body": heartbeat_body}, token=alice_token)
    assert heartbeat["result"]["accepted"] is True
    assert heartbeat["result"]["delivery_state"] == "ephemeral"
    assert "server_seq" not in heartbeat["result"]

    after_heartbeat_history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice}, token=bob_token)
    assert [message["message_id"] for message in after_heartbeat_history["result"]["messages"]] == ["msg-json-direct"]
    inbox = await rpc(client, "/im/rpc", "inbox.get", token=bob_token)
    assert [message["message_id"] for message in inbox["result"]["messages"]] == ["msg-json-direct"]
    delta = await rpc(client, "/im/rpc", "sync.delta", {"after_event_seq": 1}, token=bob_token)
    assert delta["result"]["events"] == []

    status_meta = {**heartbeat_meta, "operation_id": "op-status-run", "message_id": "msg-status-run"}
    status_body = {
        "payload": {
            "schema": "awiki.agent.status.v1",
            "status_scope": "run",
            "state": "ready",
            "message": "runtime started",
        }
    }
    status = await rpc(client, "/im/rpc", "direct.send", {"meta": status_meta, "body": status_body}, token=alice_token)
    assert status["result"]["delivery_state"] == "accepted"
    assert status["result"]["server_seq"] > 0
    final_history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice}, token=bob_token)
    assert [message["message_id"] for message in final_history["result"]["messages"]] == ["msg-json-direct", "msg-status-run"]


@pytest.mark.asyncio
async def test_message_local_views_project_payload_attachment_and_binary_content(client):
    alice, alice_token = await register(client, "projection-alice")
    bob, bob_token = await register(client, "projection-bob")
    group_did = "did:wba:testserver:groups:open"
    await rpc(client, "/im/rpc", "group.join", {"group_did": group_did}, token=alice_token)

    manifest_payload = {
        "attachments": [
            {
                "attachment_id": "att-projection",
                "object_uri": "http://testserver/objects/obj-projection",
                "filename": "projection.bin",
            }
        ],
        "primary_attachment_id": "att-projection",
    }
    direct_manifest_meta = {
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "agent", "did": bob},
        "operation_id": "op-projection-direct-manifest",
        "message_id": "msg-projection-direct-manifest",
        "content_type": "application/anp-attachment-manifest+json",
    }
    await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {"meta": direct_manifest_meta, "body": {"payload": manifest_payload}},
        token=alice_token,
    )

    direct_binary_meta = {
        **direct_manifest_meta,
        "operation_id": "op-projection-direct-binary",
        "message_id": "msg-projection-direct-binary",
        "content_type": "application/octet-stream",
    }
    await rpc(
        client,
        "/im/rpc",
        "direct.send",
        {"meta": direct_binary_meta, "body": {"payload_b64u": "aGVsbG8"}},
        token=alice_token,
    )

    history = await rpc(client, "/im/rpc", "direct.get_history", {"peer_did": alice}, token=bob_token)
    assert [message["type"] for message in history["result"]["messages"]] == ["attachment_manifest", "binary"]
    assert history["result"]["messages"][0]["content_type"] == "application/anp-attachment-manifest+json"
    assert history["result"]["messages"][0]["content"] == manifest_payload
    assert history["result"]["messages"][0]["body"] == {"payload": manifest_payload}
    assert history["result"]["messages"][1]["content_type"] == "application/octet-stream"
    assert history["result"]["messages"][1]["content"] == "aGVsbG8"
    assert history["result"]["messages"][1]["body"] == {"payload_b64u": "aGVsbG8"}

    inbox = await rpc(client, "/im/rpc", "inbox.get", token=bob_token)
    assert [message["type"] for message in inbox["result"]["messages"]] == ["binary", "attachment_manifest"]
    assert inbox["result"]["messages"][0]["content"] == "aGVsbG8"
    assert inbox["result"]["messages"][1]["content"] == manifest_payload

    thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "after_server_seq": "0",
                "limit": 100,
            },
        },
        token=bob_token,
    )
    assert [message["type"] for message in thread["result"]["messages"]] == ["attachment_manifest", "binary"]
    assert thread["result"]["messages"][0]["content"] == manifest_payload
    assert thread["result"]["messages"][1]["content"] == "aGVsbG8"

    group_manifest_meta = {
        "profile": "anp.group.base.v1",
        "security_profile": "transport-protected",
        "sender_did": alice,
        "target": {"kind": "group", "did": group_did},
        "operation_id": "op-projection-group-manifest",
        "message_id": "msg-projection-group-manifest",
        "content_type": "application/anp-attachment-manifest+json",
    }
    await rpc(
        client,
        "/im/rpc",
        "group.send",
        {"meta": group_manifest_meta, "body": {"payload": manifest_payload}},
        token=alice_token,
    )

    group_binary_meta = {
        **group_manifest_meta,
        "operation_id": "op-projection-group-binary",
        "message_id": "msg-projection-group-binary",
        "content_type": "application/octet-stream",
    }
    await rpc(
        client,
        "/im/rpc",
        "group.send",
        {"meta": group_binary_meta, "body": {"payload_b64u": "AAECAw"}},
        token=alice_token,
    )

    group_messages = await rpc(client, "/im/rpc", "group.list_messages", {"group_did": group_did}, token=alice_token)
    assert [message["type"] for message in group_messages["result"]["messages"]] == ["attachment_manifest", "binary"]
    assert group_messages["result"]["messages"][0]["content_type"] == "application/anp-attachment-manifest+json"
    assert group_messages["result"]["messages"][0]["content"] == manifest_payload
    assert group_messages["result"]["messages"][1]["content_type"] == "application/octet-stream"
    assert group_messages["result"]["messages"][1]["content"] == "AAECAw"

    group_thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": alice,
                "thread": {"kind": "group", "group_did": group_did},
                "after_server_seq": "0",
                "limit": 100,
            },
        },
        token=alice_token,
    )
    assert [message["type"] for message in group_thread["result"]["messages"]] == ["attachment_manifest", "binary"]
    assert group_thread["result"]["messages"][0]["content"] == manifest_payload
    assert group_thread["result"]["messages"][1]["content"] == "AAECAw"


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


@pytest.mark.asyncio
async def test_sync_delta_thread_after_and_read_state_standard_shapes(client):
    alice, alice_token = await register(client, "sync-alice")
    bob, bob_token = await register(client, "sync-bob")

    sent = await rpc(client, "/im/rpc", "direct.send", {"to": bob, "text": "sync hello"}, token=alice_token)
    message_id = sent["result"]["message_id"]

    delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {"user_did": bob, "since_event_seq": "0", "limit": 100},
        },
        token=bob_token,
    )
    result = delta["result"]
    assert result["owner_subject_id"] == bob
    assert result["has_more"] is False
    assert result["snapshot_required"] is False
    assert result["warnings"] == []
    assert result["events"][0]["event_seq"] == "1"
    assert result["events"][0]["owner_subject_id"] == bob
    assert result["events"][0]["aggregate_kind"] == "direct_message"

    thread = await rpc(
        client,
        "/im/rpc",
        "sync.thread_after",
        {
            "meta": {"profile": "anp.sync.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "after_server_seq": "0",
                "limit": 100,
            },
        },
        token=bob_token,
    )
    assert thread["result"]["thread"]["peer_did"] == alice
    assert thread["result"]["messages"][0]["message_id"] == message_id
    assert thread["result"]["next_after_server_seq"] == str(thread["result"]["next_server_seq"])

    read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "meta": {"profile": "anp.read_state.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "read_up_to_server_seq": str(thread["result"]["next_server_seq"]),
                "read_up_to_message_id": message_id,
            },
        },
        token=bob_token,
    )
    assert read["result"]["remote_acknowledged"] is True
    assert read["result"]["pending_remote_ack"] is False
    assert read["result"]["read_watermark_server_seq"] == str(thread["result"]["next_server_seq"])
    assert read["result"]["thread"]["kind"] == "direct"

    read_by_id = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "meta": {"profile": "anp.read_state.local.v1", "security_profile": "transport-protected"},
            "body": {
                "user_did": bob,
                "thread": {"kind": "direct", "peer_did": alice},
                "read_up_to_message_id": message_id,
            },
        },
        token=bob_token,
    )
    assert read_by_id["result"]["read_watermark_server_seq"] == str(thread["result"]["next_server_seq"])
    assert read_by_id["result"]["updated_count"] == 0

    mismatch = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {
            "thread": {"kind": "direct", "peer_did": alice},
            "read_up_to_server_seq": str(int(thread["result"]["next_server_seq"]) + 1),
            "read_up_to_message_id": message_id,
        },
        token=bob_token,
    )
    assert mismatch["error"]["message"] == "read_state.watermark_mismatch"

    after_read_delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        {"body": {"user_did": bob, "since_event_seq": "1", "limit": 100}},
        token=bob_token,
    )
    assert after_read_delta["result"]["events"] == []

    bad_read = await rpc(
        client,
        "/im/rpc",
        "read_state.mark_read",
        {"thread": {"kind": "direct", "peer_did": alice}, "event_seq": "1"},
        token=bob_token,
    )
    assert bad_read["error"]["message"] == "read_state.server_seq_invalid"
