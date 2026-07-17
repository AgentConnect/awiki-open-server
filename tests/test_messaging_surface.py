from __future__ import annotations

import json

import pytest

from awiki_open_server.service_identity import (
    build_service_did_document,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
)
from awiki_open_server.shared.errors import InvalidParams
from tests.conftest import rpc
from tests.helpers import register


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


@pytest.mark.asyncio
async def test_direct_group_participant_and_public_surface(client):
    alice_did, alice_token = await register(client, "alice")
    bob_did, bob_token = await register(client, "bob")

    caps = await rpc(client, "/im/rpc", "anp.get_capabilities", token=alice_token)
    assert "anp.group.base.v1" in caps["result"]["supported_profiles"]
    assert caps["result"]["features"]["group_participant"]["management"] is True
    assert caps["result"]["features"]["group_participant"]["join_modes"] == ["open-join", "admin-add"]
    assert caps["result"]["features"]["group_participant"]["max_members"] == "100"
    assert caps["result"]["features"]["cross_domain_group"] == {
        "enabled": True,
        "mode": "did_discovery_direct_call",
    }

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
    assert marked["result"]["updated_count"] == 0

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
    assert denied["error"]["message"] == "missing_origin_proof"

    public_denied = await rpc(client, "/anp-im/rpc", "direct.get_history", {"peer_did": bob_did}, token=alice_token)
    assert public_denied["error"]["message"] == "method_not_found"

    for method, params in [
        ("sync.delta", {"after_event_seq": 0}),
        ("attachment.create_slot", {"attachment_id": "att-public-denied"}),
    ]:
        denied = await rpc(client, "/anp-im/rpc", method, params, token=alice_token)
        assert denied["error"]["message"] == "method_not_found"

    for method in ["group.add", "group.remove", "group.update_profile", "group.update_policy"]:
        response = await rpc(client, "/im/rpc", method, {"group_did": group_did}, token=alice_token)
        assert response["error"]["message"] == "missing_origin_proof"

    for method in ["group.send", "group.leave"]:
        response = await rpc(client, "/anp-im/rpc", method, {"group_did": group_did}, token=alice_token)
        assert response["error"]["message"] == "missing_origin_proof"
