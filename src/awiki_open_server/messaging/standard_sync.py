"""Standard explicit negotiation and Schema 3 Snapshot helpers.

These reducers operate on plain dicts/lists so pytest can drive them without a
public nginx window. Handlers persist rows and call these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

import jcs

from awiki_open_server.shared.errors import SyncProtocolError
from awiki_open_server.shared.ids import new_id


EXPLICIT_NEGOTIATION_V1 = "awiki.message-sync.explicit-negotiation.v1"
SNAPSHOT_PAGING_V1 = "sync.snapshot_paging.v1"
SYNC_PROFILE_V2 = "anp.sync.local.v2"
LANE_P5 = "lanes.p5_device.v1"
LANE_P6 = "lanes.p6_group.v1"
P6_DELIVERY = "p6.delivery_context.v1"
KNOWN_LANE_CAPABILITIES = (LANE_P5, LANE_P6, P6_DELIVERY)
SECTION_ORDER = (
    "read_states",
    "groups",
    "recent_plain_messages",
    "unexpired_system_notifications",
)
MAX_PAGE_ITEMS = 100
MAX_PAGE_BYTES = 1_048_576
MAX_PACKAGE_ITEMS = 10_000
MAX_PACKAGE_BYTES = 67_108_864
MAX_PAGES = 100
MESSAGE_CUTOFF_HOURS = 48
RECOVERY_TTL_SECONDS = 10 * 60
SNAPSHOT_CAPABILITY = {"schema": 3, "delivery": "paged_v1"}


@dataclass(frozen=True)
class BootstrapCapabilities:
    client_instance_id: str
    extended: bool
    snapshot_paging: bool
    requested: tuple[str, ...]
    p6_delivery: bool


def jcs_bytes(value: Any) -> bytes:
    return jcs.canonicalize(value)


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(jcs_bytes(value)).hexdigest()


def _invalid(details: dict[str, Any] | None = None) -> SyncProtocolError:
    return SyncProtocolError("sync.invalid_request", code=4200, details=details)


def parse_bootstrap_capabilities(body: dict[str, Any]) -> BootstrapCapabilities:
    if not isinstance(body, dict) or set(body) != {"client_instance_id", "capabilities"}:
        raise _invalid({"reason": "sync.bootstrap_body_invalid"})
    client_instance_id = body.get("client_instance_id")
    if not isinstance(client_instance_id, str) or not client_instance_id.strip() or len(client_instance_id) > 255:
        raise _invalid({"reason": "sync.client_instance_id_invalid"})
    capabilities = body.get("capabilities")
    if not isinstance(capabilities, dict):
        raise _invalid({"reason": "sync.bootstrap_capabilities_invalid"})
    if capabilities.get("sync_profile") != SYNC_PROFILE_V2 or capabilities.get("event_schema_max") != 1:
        raise _invalid({"reason": "sync.bootstrap_capabilities_invalid"})
    keys = set(capabilities)
    legacy = {"sync_profile", "event_schema_max"}
    if keys == legacy:
        return BootstrapCapabilities(client_instance_id, False, False, (), False)
    if keys == legacy | {"p6_delivery"}:
        raise SyncProtocolError(
            "sync.lanes_not_supported",
            code=4200,
            details={"requested": [P6_DELIVERY], "supported": []},
        )
    if "requested_sync_capabilities" not in capabilities:
        raise _invalid({"reason": "sync.bootstrap_capabilities_invalid"})
    requested_raw = capabilities.get("requested_sync_capabilities")
    if not isinstance(requested_raw, list) or any(not isinstance(item, str) or not item for item in requested_raw):
        raise _invalid({"field": "requested_sync_capabilities"})
    if len(requested_raw) != len(set(requested_raw)):
        raise _invalid({"field": "requested_sync_capabilities", "reason": "duplicate"})
    unknown = [item for item in requested_raw if item not in KNOWN_LANE_CAPABILITIES]
    if unknown:
        raise _invalid({"field": "requested_sync_capabilities", "unknown": unknown})
    p6_field = capabilities.get("p6_delivery")
    p6_requested = LANE_P6 in requested_raw or P6_DELIVERY in requested_raw
    if p6_field is not None and p6_field != P6_DELIVERY:
        raise _invalid({"field": "p6_delivery"})
    if (LANE_P6 in requested_raw) != (P6_DELIVERY in requested_raw) or p6_requested != (p6_field == P6_DELIVERY):
        raise _invalid({"reason": "p6_unpaired"})
    allowed = legacy | {"requested_sync_capabilities", "requested_snapshot_capabilities", "p6_delivery"}
    extra = keys - allowed
    if extra:
        raise _invalid({"unexpected_fields": sorted(extra)})
    snapshot = capabilities.get("requested_snapshot_capabilities")
    if snapshot is None:
        raise _invalid({"reason": "extended bootstrap requires requested_snapshot_capabilities"})
    if (
        not isinstance(snapshot, dict)
        or set(snapshot) != {"schema_max", "deliveries"}
        or snapshot.get("schema_max") != 3
        or snapshot.get("deliveries") != ["paged_v1"]
    ):
        raise _invalid({"field": "requested_snapshot_capabilities"})
    if requested_raw:
        raise SyncProtocolError(
            "sync.lanes_not_supported",
            code=4200,
            details={"requested": list(requested_raw), "supported": []},
        )
    return BootstrapCapabilities(client_instance_id, True, True, tuple(requested_raw), False)


def encoded_size(item: Any) -> int:
    size = len(jcs_bytes(item))
    if size > MAX_PAGE_BYTES:
        raise SyncProtocolError("sync.snapshot_item_too_large", code=4221, details={"encoded_bytes": size})
    return size


def _history_policy(*, returned: int, encoded: int, pages: int, oldest: str | None, excluded: int, reason: str | None) -> dict[str, Any]:
    return {
        "selection": "newest_complete_suffix",
        "returned_items": returned,
        "returned_encoded_bytes": encoded,
        "returned_pages": pages,
        "oldest_included_event_seq": oldest,
        "excluded_older_messages": excluded,
        "older_history_excluded": excluded > 0,
        "truncation_reason": reason,
        "complete_within_policy": True,
    }


def select_snapshot_package(
    *,
    read_states: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    """Select required state first, then newest ordinary messages within budget."""

    required = {
        "read_states": list(read_states),
        "groups": list(groups),
        "unexpired_system_notifications": list(notifications),
    }
    required_items = 0
    required_bytes = 0
    sized_required: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for name, items in required.items():
        sized = []
        for item in items:
            size = encoded_size(item)
            sized.append((item, size))
            required_items += 1
            required_bytes += size
        sized_required[name] = sized
    if required_items > MAX_PACKAGE_ITEMS or required_bytes > MAX_PACKAGE_BYTES:
        raise SyncProtocolError(
            "sync.snapshot_required_state_too_large",
            code=4222,
            details={"required_state_items": required_items, "required_state_encoded_bytes": required_bytes},
        )
    required_only = {
        "read_states": [item for item, _ in sized_required["read_states"]],
        "groups": [item for item, _ in sized_required["groups"]],
        "unexpired_system_notifications": [item for item, _ in sized_required["unexpired_system_notifications"]],
    }
    required_pages = _page_count_for_sections(required_only)
    if required_pages > MAX_PAGES:
        raise SyncProtocolError(
            "sync.snapshot_required_state_too_large",
            code=4222,
            details={"required_state_pages": required_pages},
        )
    remaining_items = MAX_PACKAGE_ITEMS - required_items
    remaining_bytes = MAX_PACKAGE_BYTES - required_bytes
    remaining_pages = MAX_PAGES - required_pages
    selected_newest: list[dict[str, Any]] = []
    message_bytes = 0
    truncation = None
    for item in messages:
        size = encoded_size(item)
        if len(selected_newest) >= remaining_items:
            truncation = "max_items"
            break
        if message_bytes + size > remaining_bytes:
            truncation = "max_encoded_bytes"
            break
        trial_oldest = list(reversed(selected_newest + [item]))
        if _page_count_for_sections({"recent_plain_messages": trial_oldest}) > remaining_pages:
            truncation = "max_pages"
            break
        selected_newest.append(item)
        message_bytes += size
    # Newest-complete-suffix: caller must pass messages newest-first.
    selected_messages = list(reversed(selected_newest))
    excluded = max(0, len(messages) - len(selected_messages))
    package = {
        "read_states": [item for item, _ in sized_required["read_states"]],
        "groups": [item for item, _ in sized_required["groups"]],
        "recent_plain_messages": selected_messages,
        "unexpired_system_notifications": [item for item, _ in sized_required["unexpired_system_notifications"]],
    }
    oldest = None
    if selected_messages:
        oldest = str(selected_messages[0]["event"]["event_seq"])
    history = _history_policy(
        returned=len(selected_messages),
        encoded=message_bytes,
        pages=_page_count_for_sections({"recent_plain_messages": selected_messages}),
        oldest=oldest,
        excluded=excluded,
        reason=truncation,
    )
    budget = {
        "max_items": MAX_PACKAGE_ITEMS,
        "max_encoded_bytes": MAX_PACKAGE_BYTES,
        "max_pages": MAX_PAGES,
        "required_state_items": required_items,
        "required_state_encoded_bytes": required_bytes,
        "required_state_pages": required_pages,
    }
    return package, budget, history


def _paginate_nonempty_sections(sections: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Page nonempty sections only. Empty sections occupy no pages (Core page_sum)."""
    pages: list[dict[str, Any]] = []
    for name in SECTION_ORDER:
        items = list(sections.get(name) or [])
        if not items:
            continue
        index = 0
        while index < len(items):
            batch: list[dict[str, Any]] = []
            encoded = 0
            while index < len(items) and len(batch) < MAX_PAGE_ITEMS:
                size = encoded_size(items[index])
                if batch and encoded + size > MAX_PAGE_BYTES:
                    break
                batch.append(items[index])
                encoded += size
                index += 1
            pages.append({"section": name, "items": batch, "returned_encoded_bytes": encoded})
            if len(pages) > MAX_PAGES:
                raise SyncProtocolError(
                    "sync.snapshot_required_state_too_large",
                    code=4222,
                    details={"total_pages": len(pages)},
                )
    return pages


def _page_count_for_sections(sections: dict[str, list[dict[str, Any]]]) -> int:
    return len(_paginate_nonempty_sections(sections))


def paginate_sections(sections: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    pages = _paginate_nonempty_sections(sections)
    if not pages:
        pages.append({"section": "read_states", "items": [], "returned_encoded_bytes": 0})
    if len(pages) > MAX_PAGES:
        raise SyncProtocolError("sync.snapshot_required_state_too_large", code=4222, details={"total_pages": len(pages)})
    return pages


def build_manifest(
    *,
    frozen_at: str,
    snapshot_cursor: dict[str, str],
    package: dict[str, list[dict[str, Any]]],
    pages: list[dict[str, Any]],
    budget: dict[str, Any],
    history: dict[str, Any],
    message_cutoff: str,
) -> dict[str, Any]:
    sections = {}
    for name in SECTION_ORDER:
        items = package.get(name) or []
        sections[name] = {"item_count": len(items), "digest": sha256_digest(items)}
    total_items = sum(section["item_count"] for section in sections.values())
    total_bytes = len(jcs_bytes(package))
    manifest = {
        "manifest_schema": 1,
        "frozen_at": frozen_at,
        "snapshot_cursor": snapshot_cursor,
        "sections": sections,
        "recovery_budget": budget,
        "history_policy": history,
        "message_policy": {
            "server_cutoff": message_cutoff,
            "selection": "ordinary_plain_only",
        },
        "system_notification_policy": {
            "scope": "exact_device_unexpired",
            "complete_through_scan_seq": snapshot_cursor["scan_seq"],
            "complete": True,
        },
        "excluded": {"e2ee_messages": True, "plain_messages_before_cutoff": True},
        "total_items": total_items,
        "total_encoded_bytes": total_bytes,
        "total_pages": len(pages),
    }
    manifest["manifest_digest"] = sha256_digest({key: value for key, value in manifest.items() if key != "manifest_digest"})
    return manifest


def decorate_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = []
    for page in pages:
        items = page["items"]
        decorated.append(
            {
                "section": page["section"],
                "items": items,
                "returned_items": len(items),
                "returned_encoded_bytes": page["returned_encoded_bytes"],
                "page_digest": sha256_digest(items),
            }
        )
    return decorated


def load_or_create_page_ref_key(data_dir: Path) -> bytes:
    path = data_dir / "snapshot-page-ref.key"
    if path.exists():
        return path.read_bytes()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".snapshot-key-", delete=False) as tmp:
        os.fchmod(tmp.fileno(), 0o600)
        tmp.write(key)
        tmp.flush()
        temporary = Path(tmp.name)
    temporary.replace(path)
    path.chmod(0o600)
    return key


def sign_page_ref(key: bytes, claims: dict[str, Any]) -> str:
    digest = hmac.new(key, jcs_bytes(claims), hashlib.sha256).digest()
    return _b64u(digest)


def parse_page_ref(key: bytes, token: str, expected: dict[str, Any]) -> None:
    if not hmac.compare_digest(token, sign_page_ref(key, expected)):
        raise SyncProtocolError("sync.recovery_token_invalid", code=4216, details={"field": "page_ref"})


def _b64u(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_hours_ago(hours: int, *, now: str | None = None) -> str:
    current = datetime.fromisoformat((now or iso_now()).replace("Z", "+00:00"))
    return (current - timedelta(hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_later(seconds: int, *, now: str | None = None) -> str:
    current = datetime.fromisoformat((now or iso_now()).replace("Z", "+00:00"))
    return (current + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_recovery_id() -> str:
    return new_id("recovery")


def new_recovery_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def recovery_descriptor(
    *,
    recovery_id: str,
    token: str,
    stream_epoch: str,
    snapshot_scan_seq: str,
    message_cutoff: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "recovery_id": recovery_id,
        "token": token,
        "snapshot_schema": 3,
        "snapshot_delivery": "paged_v1",
        "stream_epoch": stream_epoch,
        "snapshot_scan_seq": snapshot_scan_seq,
        "message_cutoff": message_cutoff,
        "expires_at": expires_at,
    }


def attach_standard_bootstrap_fields(result: dict[str, Any], *, snapshot_paging: bool) -> dict[str, Any]:
    result = dict(result)
    if snapshot_paging:
        result["sync_capabilities"] = []
        result["snapshot_capability"] = dict(SNAPSHOT_CAPABILITY)
    return result
