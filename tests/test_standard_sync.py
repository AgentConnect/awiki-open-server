from __future__ import annotations

import pytest

from awiki_open_server.messaging import standard_sync, sync_contract
from awiki_open_server.shared.errors import SyncProtocolError


def test_empty_extended_bootstrap_is_accepted():
    caps = standard_sync.parse_bootstrap_capabilities(
        {
            "client_instance_id": "install-1",
            "capabilities": {
                "sync_profile": "anp.sync.local.v2",
                "event_schema_max": 1,
                "requested_sync_capabilities": [],
                "requested_snapshot_capabilities": {"schema_max": 3, "deliveries": ["paged_v1"]},
            },
        }
    )
    assert caps.extended is True
    assert caps.snapshot_paging is True
    assert caps.requested == ()


@pytest.mark.parametrize("requested", [
    ["lanes.p5_device.v1"],
    ["lanes.p6_group.v1", "p6.delivery_context.v1"],
    ["lanes.p5_device.v1", "lanes.p6_group.v1", "p6.delivery_context.v1"],
])
def test_requested_p5_p6_are_rejected_without_subset(requested):
    with pytest.raises(SyncProtocolError) as raised:
        standard_sync.parse_bootstrap_capabilities(
            {
                "client_instance_id": "install-1",
                "capabilities": {
                    "sync_profile": "anp.sync.local.v2",
                    "event_schema_max": 1,
                    "requested_sync_capabilities": requested,
                    "requested_snapshot_capabilities": {"schema_max": 3, "deliveries": ["paged_v1"]},
                    **({"p6_delivery": "p6.delivery_context.v1"} if "lanes.p6_group.v1" in requested else {}),
                },
            }
        )
    assert raised.value.anp_code == "sync.lanes_not_supported"
    assert raised.value.data["details"]["requested"] == requested
    assert raised.value.data["details"]["supported"] == []


def _plain_message(seq: str) -> dict:
    return {"event": {"event_seq": seq, "event_type": "message.created"}, "message": {"id": f"msg-{seq}"}}


def _assert_core_page_sum(budget: dict, history: dict, *, total_pages: int, total_items: int) -> None:
    """Core parser: page_sum == total_pages, except all-empty (0+0, total_pages=1)."""
    page_sum = budget["required_state_pages"] + history["returned_pages"]
    if total_items == 0:
        assert page_sum == 0
        assert total_pages == 1
        return
    assert page_sum == total_pages


def _manifest_pages(package, budget, history):
    pages = standard_sync.paginate_sections(package)
    manifest = standard_sync.build_manifest(
        frozen_at="2026-09-18T00:00:00Z",
        snapshot_cursor={"stream_epoch": "1", "scan_seq": "10"},
        package=package,
        pages=pages,
        budget=budget,
        history=history,
        message_cutoff="2026-09-16T00:00:00Z",
    )
    return manifest, pages


def test_snapshot_pages_four_domains_and_empty_package():
    read_states = [{"thread_key": f"conv_{index}", "thread_kind": "direct", "read_up_to_thread_seq": "1", "state_version": "1"} for index in range(120)]
    groups = [{"group_did": "did:wba:example:groups:one", "group_state_version": "1", "group_event_seq": "1"}]
    package, budget, history = standard_sync.select_snapshot_package(
        read_states=read_states, groups=groups, notifications=[], messages=[]
    )
    manifest, pages = _manifest_pages(package, budget, history)
    decorated = standard_sync.decorate_pages(pages)
    assert budget["required_state_items"] == 121
    assert budget["required_state_pages"] == 3
    assert history["returned_items"] == 0
    assert history["returned_pages"] == 0
    assert decorated[0]["section"] == "read_states"
    assert decorated[0]["returned_items"] == 100
    assert decorated[1]["section"] == "read_states"
    assert decorated[1]["returned_items"] == 20
    assert decorated[2]["section"] == "groups"
    assert set(manifest["sections"]) == {
        "read_states",
        "groups",
        "recent_plain_messages",
        "unexpired_system_notifications",
    }
    assert manifest["sections"]["recent_plain_messages"]["item_count"] == 0
    assert manifest["sections"]["unexpired_system_notifications"]["item_count"] == 0
    _assert_core_page_sum(budget, history, total_pages=manifest["total_pages"], total_items=manifest["total_items"])

    empty, empty_budget, empty_history = standard_sync.select_snapshot_package(
        read_states=[], groups=[], notifications=[], messages=[]
    )
    empty_manifest, empty_pages = _manifest_pages(empty, empty_budget, empty_history)
    assert empty_budget["required_state_pages"] == 0
    assert empty_history["returned_pages"] == 0
    assert empty_pages == [{"section": "read_states", "items": [], "returned_encoded_bytes": 0}]
    assert empty_manifest["total_pages"] == 1
    assert empty_manifest["total_items"] == 0
    _assert_core_page_sum(
        empty_budget, empty_history, total_pages=empty_manifest["total_pages"], total_items=empty_manifest["total_items"]
    )


def test_snapshot_page_sum_messages_only_and_empty_history():
    messages = [_plain_message(str(index)) for index in range(3, 0, -1)]
    package, budget, history = standard_sync.select_snapshot_package(
        read_states=[], groups=[], notifications=[], messages=messages
    )
    manifest, pages = _manifest_pages(package, budget, history)
    assert budget["required_state_items"] == 0
    assert budget["required_state_pages"] == 0
    assert history["returned_items"] == 3
    assert history["returned_pages"] == 1
    assert [page["section"] for page in pages] == ["recent_plain_messages"]
    _assert_core_page_sum(budget, history, total_pages=manifest["total_pages"], total_items=manifest["total_items"])

    read_states = [{"thread_key": "conv_only", "thread_kind": "direct", "read_up_to_thread_seq": "1", "state_version": "1"}]
    empty_history_package, empty_history_budget, empty_history = standard_sync.select_snapshot_package(
        read_states=read_states, groups=[], notifications=[], messages=[]
    )
    empty_history_manifest, empty_history_pages = _manifest_pages(
        empty_history_package, empty_history_budget, empty_history
    )
    assert empty_history_budget["required_state_pages"] == 1
    assert empty_history["returned_pages"] == 0
    assert [page["section"] for page in empty_history_pages] == ["read_states"]
    _assert_core_page_sum(
        empty_history_budget,
        empty_history,
        total_pages=empty_history_manifest["total_pages"],
        total_items=empty_history_manifest["total_items"],
    )


def test_snapshot_history_truncates_on_max_pages(monkeypatch):
    monkeypatch.setattr(standard_sync, "MAX_PAGES", 2)
    read_states = [{"thread_key": "conv_only", "thread_kind": "direct", "read_up_to_thread_seq": "1", "state_version": "1"}]
    messages = [_plain_message(str(index)) for index in range(150, 0, -1)]
    package, budget, history = standard_sync.select_snapshot_package(
        read_states=read_states, groups=[], notifications=[], messages=messages
    )
    manifest, pages = _manifest_pages(package, budget, history)
    assert budget["required_state_pages"] == 1
    assert history["truncation_reason"] == "max_pages"
    assert history["older_history_excluded"] is True
    assert history["complete_within_policy"] is True
    assert history["returned_pages"] == 1
    assert history["returned_items"] == standard_sync.MAX_PAGE_ITEMS
    assert manifest["total_pages"] == 2
    _assert_core_page_sum(budget, history, total_pages=manifest["total_pages"], total_items=manifest["total_items"])
    assert [page["section"] for page in pages] == ["read_states", "recent_plain_messages"]


def test_required_state_over_max_pages_fails_closed(monkeypatch):
    monkeypatch.setattr(standard_sync, "MAX_PAGES", 1)
    read_states = [{"thread_key": f"conv_{index}", "thread_kind": "direct", "read_up_to_thread_seq": "1", "state_version": "1"} for index in range(120)]
    with pytest.raises(SyncProtocolError) as raised:
        standard_sync.select_snapshot_package(read_states=read_states, groups=[], notifications=[], messages=[])
    assert raised.value.anp_code == "sync.snapshot_required_state_too_large"


def test_legacy_group_snapshot_has_core_frozen_fields():
    assert sync_contract.host_service_did_for_group(
        "did:wba:open.test:groups:one", "did:wba:127.0.0.1"
    ) == "did:wba:127.0.0.1"
    assert sync_contract.host_service_did_for_group("did:wba:open.test:groups:one") == "did:wba:open.test"


def test_required_state_over_budget_fails_closed():
    huge = {"payload": "x" * (standard_sync.MAX_PAGE_BYTES + 1)}
    with pytest.raises(SyncProtocolError) as raised:
        standard_sync.select_snapshot_package(read_states=[huge], groups=[], notifications=[], messages=[])
    assert raised.value.anp_code == "sync.snapshot_item_too_large"
