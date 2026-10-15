from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from tests.conftest import rpc
from tests.helpers import origin_proof, register_with_key


def test_notification_version_belongs_to_bound_member_home(monkeypatch):
    from awiki_open_server.messaging.groups import outbox
    from awiki_open_server.shared import runtime
    from awiki_open_server.shared.errors import NotSupported, Unauthorized
    member = "did:wba:peer.test:user:member"
    home = "did:wba:peer.test"
    service = {"serviceDid": home, "serviceEndpoint": "https://peer.test/anp-im/rpc", "profiles": ["anp.group.base.v1"]}
    home_service = {**service, "profiles": ["anp.group.base.v2"]}
    monkeypatch.setattr(runtime, "_discover_anp_service", lambda did, _settings: service if did == member else home_service)
    monkeypatch.setattr(runtime, "outbound_options", lambda *_args: {})
    posted = []
    monkeypatch.setattr(runtime, "_http_post_json", lambda *args, **kwargs: posted.append(args) or {})
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(service_did="did:wba:host.test", allow_unsigned_peer_dev=True)))
    row = {"target_did": member, "target_service_did": home, "envelope_json": json.dumps({"jsonrpc":"2.0", "method":"group.event", "params":{"meta":{"profile":"anp.group.base.v2"},"body":{}}})}
    outbox._deliver(app, row)
    assert len(posted) == 1
    home_service["serviceEndpoint"] = "https://other.test/anp-im/rpc"
    with pytest.raises(Unauthorized, match="outbox_target_home_endpoint_changed"):
        outbox._deliver(app, row)
    home_service["serviceEndpoint"] = service["serviceEndpoint"]
    home_service["profiles"] = ["anp.group.base.v1"]
    with pytest.raises(NotSupported, match="peer_profile_not_supported"):
        outbox._deliver(app, row)
    assert len(posted) == 1

POLICY = {"message_security_profile": "transport-protected", "bootstrap_security_profile": "transport-protected", "admission_mode": "open-join",
          "permissions": {"send": "member", "add": "admin", "remove": "admin", "update_profile": "admin", "update_policy": "owner"}, "max_members": "100"}


def envelope(method, did, key, target, operation, body, *, profile="anp.group.base.v2"):
    meta = {"profile": profile, "security_profile": "transport-protected", "sender_did": did,
            "target": {"kind": "service" if method == "group.create" else "group", "did": target},
            "operation_id": operation, "content_type": "application/json"}
    if method == "group.send":
        meta["message_id"] = f"message-{operation}"
    return {"meta": meta, "body": body, "auth": {"scheme": "anp-rfc9421-origin-proof-v1", "origin_proof": origin_proof(meta, body, key, method=method)}}


async def group_call(client, identity, method, group, operation, body, *, profile="anp.group.base.v2"):
    did, token, key, _ = identity
    if method == "group.create":
        body = {"group_profile": {"display_name": "Protocol test"}, "group_policy": copy.deepcopy(POLICY), **body}
    response = await rpc(client, "/im/rpc", method, envelope(method, did, key, group, operation, body, profile=profile), token=token)
    if profile == "anp.group.base.v2" and "result" in response:
        result = response["result"]
        assert result["accepted"] is True
        assert result["final_acceptance"] is True
        assert result["operation_id"] == operation == result["group_receipt"]["operation_id"]
        assert result["accepted_at"] == result["group_receipt"]["accepted_at"]
    return response


@pytest.mark.asyncio
async def test_group_v2_leave_replay_adds_standard_acceptance_without_resigning_history(client):
    owner = await register_with_key(client, "accept-owner")
    member = await register_with_key(client, "accept-member")
    created = await group_call(client, owner, "group.create", "did:wba:testserver", "accept-create", {"group_profile": {"display_name": "Acceptance"}})
    group = created["result"]["group_did"]
    await group_call(client, member, "group.join", group, "accept-join", {})
    left = await group_call(client, member, "group.leave", group, "accept-leave", {})
    original = left["result"]
    old = {key: value for key, value in original.items() if key not in {"accepted", "final_acceptance", "operation_id", "accepted_at"}}
    with client._transport.app.state.store.connect() as conn:
        conn.execute("UPDATE group_operations SET result_json=? WHERE group_scope=? AND operation_id='accept-leave'", (json.dumps(old), group))
        conn.commit()
    replayed = await group_call(client, member, "group.leave", group, "accept-leave", {})
    assert replayed["result"]["idempotent_replay"] is True
    assert replayed["result"]["group_receipt"] == original["group_receipt"]
    assert replayed["result"]["group_event_seq"] == original["group_event_seq"]


@pytest.mark.asyncio
async def test_group_receipt_and_replay_exclude_diagnostic_trace(client):
    owner = await register_with_key(client, "trace-group-owner")
    body = {"group_profile": {"display_name": "Trace Group"}, "group_policy": copy.deepcopy(POLICY)}
    payload = envelope("group.create", owner[0], owner[2], "did:wba:testserver", "trace-group-create", body)
    payload["meta"]["trace_id"] = "host-first-hop"
    created = await rpc(client, "/im/rpc", "group.create", payload, token=owner[1])
    result = created["result"]
    assert result["group_receipt"]["payload_digest"] == payload["auth"]["origin_proof"]["contentDigest"]
    payload["meta"]["trace_id"] = "host-retry-hop"
    replay = await rpc(client, "/im/rpc", "group.create", payload, token=owner[1])
    assert replay["result"]["idempotent_replay"] is True
    assert replay["result"]["group_receipt"] == result["group_receipt"]


@pytest.mark.asyncio
async def test_group_v2_lifecycle_uses_did_members_and_preserves_application_payload(client):
    owner = await register_with_key(client, "v2-owner")
    member = await register_with_key(client, "v2-member")
    created = await group_call(client, owner, "group.create", "did:wba:testserver", "v2-create", {"group_profile": {"display_name": "V2 Group"}})
    assert "result" in created
    group = created["result"]["group_did"]
    joined = await group_call(client, member, "group.join", group, "v2-join", {})
    assert joined["result"]["membership_status"] == "active"
    query = {"meta": {"profile": "anp.group.base.v2", "security_profile": "transport-protected", "sender_did": owner[0],
                      "target": {"kind": "group", "did": group}, "operation_id": "v2-info"}, "body": {"include_member_list": True}}
    info = await rpc(client, "/im/rpc", "group.get_info", query, token=owner[1])
    assert {item["member_did"] for item in info["result"]["member_list"]} == {owner[0], member[0]}
    assert all("member_handle" not in item for item in info["result"]["member_list"])
    sent = await group_call(client, member, "group.send", group, "v2-send", {"payload": {"device_id": "application-data", "member_handle": "not-a-selector"}})
    assert sent["result"]["accepted"] is True
    repeated = await group_call(client, member, "group.send", group, "v2-send", {"payload": {"device_id": "application-data", "member_handle": "not-a-selector"}})
    assert repeated["result"]["group_event_seq"] == sent["result"]["group_event_seq"]
    removed = await group_call(client, owner, "group.remove", group, "v2-remove", {"member_did": member[0]})
    assert removed["result"]["membership_status"] == "removed"
    denied = await group_call(client, member, "group.send", group, "v2-after-remove", {"payload": {"text": "denied"}})
    assert "error" in denied
    with client._transport.app.state.store.connect() as conn:
        row = conn.execute("SELECT * FROM hosted_groups WHERE group_did = ?", (group,)).fetchone()
        assert row["wire_profile"] == "anp.group.base.v2"
        message = conn.execute("SELECT * FROM hosted_group_messages WHERE group_did = ?", (group,)).fetchone()
        assert message["wire_profile"] == "anp.group.base.v2"
        assert message["meta_json"] is not None


@pytest.mark.parametrize("body", [
    {"creator_handle": "owner.testserver"}, {"device_id": "not-an-agent"},
    {"initial_members": [{"member_did": "did:wba:peer.test:a", "role": "owner"}]},
    {"initial_members": [{"member_did": "did:wba:peer.test:a", "device_id": "selected"}]},
])
@pytest.mark.asyncio
async def test_group_v2_rejects_identity_extensions_before_state_creation(client, body):
    owner = await register_with_key(client, "v2-invalid")
    response = await group_call(client, owner, "group.create", "did:wba:testserver", "v2-invalid-create", body)
    assert "error" in response
    with client._transport.app.state.store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM hosted_groups").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_group_profile_cannot_change_through_requests_or_replay(client):
    owner = await register_with_key(client, "v2-fence-owner")
    created = await group_call(client, owner, "group.create", "did:wba:testserver", "v1-create", {}, profile="anp.group.base.v1")
    group = created["result"]["group_did"]
    wrong = await group_call(client, owner, "group.send", group, "v2-write-old-group", {"payload": {"text": "denied"}})
    assert wrong["error"]["message"] == "group.protocol_mismatch"
    with client._transport.app.state.store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM hosted_group_messages").fetchone()[0] == 0
        conn.execute("UPDATE hosted_groups SET protocol_state = 'quiescing' WHERE group_did = ?", (group,))
    frozen = await group_call(client, owner, "group.send", group, "v1-write-frozen", {"payload": {"text": "denied"}}, profile="anp.group.base.v1")
    assert frozen["error"]["message"] == "group.protocol_upgrade_in_progress"
