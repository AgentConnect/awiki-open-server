from __future__ import annotations

import json
import httpx
import pytest

from awiki_open_server.app.main import create_app
from awiki_open_server.messaging.sync_contract import SNAPSHOT_GROUP_FIELDS, group_snapshot
from tests.conftest import rpc
from tests.helpers import register, sign_did_document, single_device_document
from tests.test_sync_v2_single_device import _register_single_device, _v2_params


EXTENDED = {
    "sync_profile": "anp.sync.local.v2",
    "event_schema_max": 1,
    "requested_sync_capabilities": [],
    "requested_snapshot_capabilities": {"schema_max": 3, "deliveries": ["paged_v1"]},
}


async def extended_bootstrap(client, owner, token, instance="install-primary"):
    return await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(owner, "bootstrap-extended", {"client_instance_id": instance, "capabilities": EXTENDED}),
        token=token,
    )


def _core_page_sum_holds(manifest: dict) -> None:
    budget = manifest["recovery_budget"]
    history = manifest["history_policy"]
    page_sum = budget["required_state_pages"] + history["returned_pages"]
    if manifest["total_items"] == 0:
        assert page_sum == 0
        assert manifest["total_pages"] == 1
        return
    assert page_sum == manifest["total_pages"]


async def drain_snapshot(client, owner, token, descriptor, op_prefix="snap"):
    first = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(owner, f"{op_prefix}-1", {"recovery_id": descriptor["recovery_id"], "token": descriptor["token"]}),
        token=token,
    )
    result = first["result"]
    pages = [result["page"]]
    index = 2
    while result["page"].get("has_more"):
        result = (
            await rpc(
                client,
                "/im/rpc",
                "sync.snapshot",
                _v2_params(
                    owner,
                    f"{op_prefix}-{index}",
                    {
                        "recovery_id": descriptor["recovery_id"],
                        "token": descriptor["token"],
                        "page_ref": result["page"]["next_page_ref"],
                    },
                ),
                token=token,
            )
        )["result"]
        pages.append(result["page"])
        index += 1
    return first["result"]["manifest"], pages


@pytest.mark.asyncio
async def test_extended_empty_lane_bootstrap_advertises_schema3_snapshot(client):
    owner, token, account_id, _ = await _register_single_device(client, "std-sync-owner")
    result = (await extended_bootstrap(client, owner, token))["result"]
    assert result["mode"] == "tail_only"
    assert result["account_id"] == account_id
    assert result["sync_capabilities"] == []
    assert result["snapshot_capability"] == {"schema": 3, "delivery": "paged_v1"}
    assert "lanes" not in result
    assert "p6_delivery" not in result


@pytest.mark.asyncio
async def test_standard_client_subscriptions_leave_plaintext_sync_usable(client):
    owner, token, _, _ = await _register_single_device(client, "lane-owner")
    response = await rpc(
        client,
        "/im/rpc",
        "sync.bootstrap",
        _v2_params(
            owner,
            "bootstrap-lanes",
            {
                "client_instance_id": "install-lanes",
                "capabilities": {
                    **EXTENDED,
                    "requested_sync_capabilities": [
                        "lanes.p5_device.v1",
                        "lanes.p6_group.v1",
                        "p6.delivery_context.v1",
                    ],
                    "p6_delivery": "p6.delivery_context.v1",
                },
            },
        ),
        token=token,
    )
    result = response["result"]
    assert result["mode"] == "tail_only"
    assert result["p6_delivery"] == {
        "profile": "p6.delivery_context.v1", "client_instance_id": "install-lanes", "activated": True,
    }
    with client._transport.app.state.store.connect() as conn:
        saved = conn.execute("SELECT negotiated_json FROM sync_capability_negotiations WHERE client_instance_id='install-lanes'").fetchone()
    assert json.loads(saved[0]) == result["sync_capabilities"]
    delta_body = {
        "cursor": result["cursor"], "limit": 100, "reason": "session_start",
        "lanes": result["lanes"],
        "p6_delivery": {"profile": "p6.delivery_context.v1", "client_instance_id": "install-lanes"},
    }
    peer, peer_token = await register(client, "compat-plain-peer")
    sent = await rpc(client, "/im/rpc", "direct.send", {"recipient_did": owner, "text": "ordinary plaintext"}, token=peer_token)
    delta = await rpc(client, "/im/rpc", "sync.delta", _v2_params(owner, "compat-plain-delta", delta_body), token=token)
    events = delta["result"]["events"]
    assert any(event.get("payload", {}).get("client_message_id") == sent["result"]["message_id"] for event in events)
    assert all(section["events"] == [] and section["next_cursor"]["scan_seq"] == "0" for section in delta["result"]["lanes"].values())
    restarted = create_app(client._transport.app.state.settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver") as after_restart:
        replay = await rpc(after_restart, "/im/rpc", "sync.delta", _v2_params(owner, "compat-after-restart", delta_body), token=token)
        assert replay["result"]["lanes"] == delta["result"]["lanes"]
        assert replay["result"]["events"] == events
    delta_body["p6_delivery"]["client_instance_id"] = "different-installation"
    denied = await rpc(client, "/im/rpc", "sync.delta", _v2_params(owner, "wrong-compat-instance", delta_body), token=token)
    assert denied["error"]["message"] == "sync.invalid_request"


@pytest.mark.asyncio
async def test_plaintext_sync_rejects_unnegotiated_subscription_cursor(client):
    owner, token, _, _ = await _register_single_device(client, "unnegotiated-compat")
    bootstrap = (await extended_bootstrap(client, owner, token))["result"]
    response = await rpc(client, "/im/rpc", "sync.delta", _v2_params(owner, "unnegotiated-delta", {
        "cursor": bootstrap["cursor"], "limit": 100, "reason": "session_start",
        "lanes": {"p5_device": {"cursor": {"stream_epoch": "1", "scan_seq": "0"}, "committed_seq": "0"}},
    }), token=token)
    assert response["error"]["message"] == "sync.invalid_request"


@pytest.mark.asyncio
async def test_schema3_snapshot_pages_four_domains_and_rejects_bad_token(client):
    owner, token, _, _ = await _register_single_device(client, "snap-owner")
    peer, peer_token = await register(client, "snap-peer")
    await extended_bootstrap(client, owner, token)
    for index in range(3):
        await rpc(client, "/im/rpc", "direct.send", {"recipient_did": owner, "text": f"plain-{index}"}, token=peer_token)
    with client._transport.app.state.store.connect() as conn:
        for index in range(120):
            conn.execute(
                "INSERT INTO thread_read_states(owner_did, thread_id, read_up_to_seq, updated_at, state_version) VALUES (?, ?, 1, datetime('now'), 1)",
                (owner, f"direct:did:wba:testserver:users:peer-{index}"),
            )
        conn.execute("DELETE FROM sync_events WHERE owner_did=? AND event_seq=1", (owner,))
    recovered = await extended_bootstrap(client, owner, token)
    descriptor = recovered["result"]["recovery"]
    assert recovered["result"]["mode"] == "compact_recovery_required"
    assert descriptor["snapshot_schema"] == 3
    manifest, pages = await drain_snapshot(client, owner, token, descriptor)
    assert set(manifest["sections"]) == {
        "read_states",
        "groups",
        "recent_plain_messages",
        "unexpired_system_notifications",
    }
    assert manifest["sections"]["read_states"]["item_count"] == 120
    assert manifest["sections"]["recent_plain_messages"]["item_count"] >= 1
    assert pages[0]["section"] == "read_states"
    assert pages[0]["has_more"] is True
    assert {page["section"] for page in pages} >= {"read_states", "recent_plain_messages"}
    _core_page_sum_holds(manifest)
    first = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(owner, "snap-1", {"recovery_id": descriptor["recovery_id"], "token": descriptor["token"]}),
        token=token,
    )
    page = first["result"]["page"]
    assert first["result"]["mode"] == "compact_recovery"
    assert first["result"]["manifest"]["sections"]["read_states"]["item_count"] == 120
    assert page["section"] == "read_states"
    assert page["has_more"] is True
    second = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(
            owner,
            "snap-2",
            {
                "recovery_id": descriptor["recovery_id"],
                "token": descriptor["token"],
                "page_ref": page["next_page_ref"],
            },
        ),
        token=token,
    )
    assert second["result"]["manifest_digest"] == first["result"]["manifest"]["manifest_digest"]
    replay = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(
            owner,
            "snap-2-replay",
            {
                "recovery_id": descriptor["recovery_id"],
                "token": descriptor["token"],
                "page_ref": page["next_page_ref"],
            },
        ),
        token=token,
    )
    assert replay["result"]["page"] == second["result"]["page"]
    forbidden = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(owner, "snap-bad", {"recovery_id": descriptor["recovery_id"], "token": "not-the-token"}),
        token=token,
    )
    assert forbidden["error"]["message"] == "sync.recovery_token_invalid"
    outsider, outsider_token, _, _ = await _register_single_device(client, "snap-outsider")
    stolen = await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(
            outsider,
            "snap-stolen",
            {"recovery_id": descriptor["recovery_id"], "token": descriptor["token"]},
        ),
        token=outsider_token,
    )
    assert stolen["error"]["message"] == "sync.recovery_token_invalid"


def _force_log_gap(
    client,
    owner: str,
    *,
    clear_read_states: bool = False,
    drop_direct_messages: bool = False,
) -> None:
    with client._transport.app.state.store.connect() as conn:
        if clear_read_states:
            conn.execute("DELETE FROM thread_read_states WHERE owner_did=?", (owner,))
        if drop_direct_messages:
            conn.execute(
                "DELETE FROM direct_messages WHERE recipient_did=? OR sender_did=?",
                (owner, owner),
            )
        conn.execute("DELETE FROM sync_events WHERE owner_did=? AND event_seq=1", (owner,))


async def _seed_gap_messages(client, owner, token, prefix: str) -> None:
    peer, peer_token = await register(client, f"{prefix}-peer")
    for index in range(3):
        await rpc(
            client,
            "/im/rpc",
            "direct.send",
            {"recipient_did": owner, "text": f"{prefix}-{index}"},
            token=peer_token,
        )


@pytest.mark.asyncio
async def test_schema3_empty_history_all_empty_and_messages_only_page_sum(client):
    owner, token, _, _ = await _register_single_device(client, "page-sum-owner")
    await extended_bootstrap(client, owner, token)
    await _seed_gap_messages(client, owner, token, "empty-hist")
    with client._transport.app.state.store.connect() as conn:
        for index in range(120):
            conn.execute(
                "INSERT INTO thread_read_states(owner_did, thread_id, read_up_to_seq, updated_at, state_version) VALUES (?, ?, 1, datetime('now'), 1)",
                (owner, f"direct:did:wba:testserver:users:empty-hist-{index}"),
            )
    _force_log_gap(client, owner, drop_direct_messages=True)
    recovered = await extended_bootstrap(client, owner, token)
    descriptor = recovered["result"]["recovery"]
    manifest, pages = await drain_snapshot(client, owner, token, descriptor, op_prefix="empty-hist")
    assert manifest["history_policy"]["returned_items"] == 0
    assert manifest["history_policy"]["returned_pages"] == 0
    assert all(page["section"] != "recent_plain_messages" for page in pages)
    _core_page_sum_holds(manifest)

    empty_owner, empty_token, _, _ = await _register_single_device(client, "page-sum-empty")
    await extended_bootstrap(client, empty_owner, empty_token)
    await _seed_gap_messages(client, empty_owner, empty_token, "all-empty")
    _force_log_gap(client, empty_owner, clear_read_states=True, drop_direct_messages=True)
    empty_recovered = await extended_bootstrap(client, empty_owner, empty_token)
    empty_descriptor = empty_recovered["result"]["recovery"]
    empty_manifest, empty_pages = await drain_snapshot(
        client, empty_owner, empty_token, empty_descriptor, op_prefix="all-empty"
    )
    assert empty_manifest["total_items"] == 0
    assert empty_manifest["recovery_budget"]["required_state_pages"] == 0
    assert empty_manifest["history_policy"]["returned_pages"] == 0
    assert empty_manifest["total_pages"] == 1
    assert len(empty_pages) == 1
    assert empty_pages[0]["section"] == "read_states"
    assert empty_pages[0]["returned_items"] == 0
    _core_page_sum_holds(empty_manifest)

    msg_owner, msg_token, _, _ = await _register_single_device(client, "page-sum-msg")
    await extended_bootstrap(client, msg_owner, msg_token)
    await _seed_gap_messages(client, msg_owner, msg_token, "msg-only")
    _force_log_gap(client, msg_owner, clear_read_states=True)
    msg_recovered = await extended_bootstrap(client, msg_owner, msg_token)
    msg_descriptor = msg_recovered["result"]["recovery"]
    msg_manifest, msg_pages = await drain_snapshot(client, msg_owner, msg_token, msg_descriptor, op_prefix="msg-only")
    assert msg_manifest["recovery_budget"]["required_state_pages"] == 0
    assert msg_manifest["history_policy"]["returned_pages"] >= 1
    assert [page["section"] for page in msg_pages] == ["recent_plain_messages"] * len(msg_pages)
    _core_page_sum_holds(msg_manifest)


@pytest.mark.asyncio
async def test_legacy_group_snapshot_item_has_frozen_fields(client):
    owner, token, _, _ = await _register_single_device(client, "legacy-group-owner")
    group_did = "did:wba:testserver:groups:legacy-one"
    with client._transport.app.state.store.connect() as conn:
        conn.execute(
            "INSERT INTO groups(group_did, display_name, description, join_mode, created_at) VALUES (?, ?, ?, ?, ?)",
            (group_did, "legacy", "old", "open", "2026-09-18T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO group_members(group_did, member_did, role, joined_at) VALUES (?, ?, ?, ?)",
            (group_did, owner, "owner", "2026-09-18T00:00:00Z"),
        )
        item = group_snapshot(
            conn, owner, group_did, host_service_did=client._transport.app.state.settings.service_did
        )
    assert item is not None
    assert tuple(item) == SNAPSHOT_GROUP_FIELDS
    assert item["host_service_did"] == "did:wba:testserver"
    assert item["creator_did"] is None
    assert item["member_count"] == "1"
    assert item["member_role"] == "owner"
    assert item["membership_status"] == "active"


@pytest.mark.asyncio
async def test_post_snapshot_delta_receives_new_plain_message(client):
    owner, token, _, _ = await _register_single_device(client, "delta-after-owner")
    peer, peer_token = await register(client, "delta-after-peer")
    await extended_bootstrap(client, owner, token)
    await rpc(client, "/im/rpc", "direct.send", {"recipient_did": owner, "text": "before-gap"}, token=peer_token)
    await rpc(client, "/im/rpc", "direct.send", {"recipient_did": owner, "text": "gap-target"}, token=peer_token)
    with client._transport.app.state.store.connect() as conn:
        conn.execute("DELETE FROM sync_events WHERE owner_did=? AND event_seq=1", (owner,))
        highest = conn.execute("SELECT MAX(event_seq) FROM sync_events WHERE owner_did=?", (owner,)).fetchone()[0]
    recovered = await extended_bootstrap(client, owner, token)
    descriptor = recovered["result"]["recovery"]
    await rpc(
        client,
        "/im/rpc",
        "sync.snapshot",
        _v2_params(owner, "snap-complete", {"recovery_id": descriptor["recovery_id"], "token": descriptor["token"]}),
        token=token,
    )
    await rpc(client, "/im/rpc", "direct.send", {"recipient_did": owner, "text": "after-anchor"}, token=peer_token)
    delta = await rpc(
        client,
        "/im/rpc",
        "sync.delta",
        _v2_params(
            owner,
            "delta-after",
            {
                "cursor": {"stream_epoch": descriptor["stream_epoch"], "scan_seq": str(highest)},
                "limit": 100,
                "reason": "after_mutation",
            },
        ),
        token=token,
    )
    assert delta["result"]["mode"] == "delta"
    assert any(event["payload"].get("client_message_id") for event in delta["result"]["events"])


@pytest.mark.asyncio
async def test_local_registration_otp_is_one_time_and_required_with_phone(client, tmp_path):
    send = await rpc(
        client,
        "/user-service/v1/handle/rpc",
        "send_otp",
        {
            "phone": "+8613800138001",
            "purpose": "awiki.identity.register.v1",
            "handle": "otp-user",
            "domain": "testserver",
            "full_handle": "otp-user.testserver",
        },
    )
    assert send["result"]["delivery"] == "local_operator"
    assert "dev_otp" not in send["result"]
    otp_dir = client._transport.app.state.settings.data_dir / "local-registration-otp"
    otp = next(otp_dir.iterdir()).read_text().strip()
    did = "did:wba:testserver:users:otp-user:e1_device"
    root, _, document = single_device_document(did)
    did = document["id"]
    document["service"][0].update(serviceEndpoint="http://testserver/anp-im/rpc", serviceDid="did:wba:testserver")
    missing = await client.post(
        "/user-service/v1/did-auth/rpc",
        json={"jsonrpc": "2.0", "id": "1", "method": "register", "params": {"handle": "otp-user", "did_document": sign_did_document(document, root), "phone": "+8613800138001", "otp_code": "000000"}},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["message"] == "invalid_otp"
    created = await rpc(
        client,
        "/user-service/v1/did-auth/rpc",
        "register",
        {"handle": "otp-user", "did_document": sign_did_document(document, root), "phone": "+8613800138001", "otp_code": otp},
    )
    assert created["result"]["state"] == "registered"
    assert set(created["result"]) == {
        "state",
        "did",
        "user_id",
        "message",
        "access_token",
        "handle",
        "domain",
        "full_handle",
        "binding_generation",
    }
    assert created["result"]["message"] == "Registration successful"
    assert created["result"]["binding_generation"] == "1"
    reused = await client.post(
        "/user-service/v1/did-auth/rpc",
        json={"jsonrpc": "2.0", "id": "1", "method": "register", "params": {"handle": "otp-user-2", "did_document": sign_did_document(document, root), "phone": "+8613800138001", "otp_code": otp}},
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["message"] == "invalid_otp"
