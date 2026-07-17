from __future__ import annotations

import json
from typing import Any

from awiki_open_server.app.settings import Settings
from awiki_open_server.shared.errors import InvalidParams
from awiki_open_server.shared.ids import new_id


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _remote_members(conn: Any, settings: Settings, group_did: str) -> list[Any]:
    return conn.execute(
        """
        SELECT agent_did, home_service_did
        FROM hosted_group_members
        WHERE group_did = ? AND status = 'active'
          AND home_service_did IS NOT NULL AND home_service_did != ?
        ORDER BY agent_did
        """,
        (group_did, settings.service_did),
    ).fetchall()


def ensure_outbox_capacity(
    conn: Any,
    settings: Settings,
    *,
    group_did: str,
    management_operation: bool,
) -> None:
    additional = len(_remote_members(conn, settings, group_did))
    if additional == 0:
        return
    pending = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM group_delivery_outbox WHERE status IN ('pending', 'retry')"
        ).fetchone()["count"]
    )
    reserve = max(10, min(100, settings.group_outbox_max_pending // 100))
    limit = settings.group_outbox_max_pending + (reserve if management_operation else 0)
    if pending + additional > limit:
        raise InvalidParams(
            "group.delivery_backlog_full",
            data={"limit": settings.group_outbox_max_pending, "pending": pending},
        )


def _enqueue(
    conn: Any,
    *,
    group_did: str,
    group_event_seq: int,
    target_did: str,
    target_service_did: str,
    method: str,
    envelope: dict[str, Any],
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO group_delivery_outbox(
          delivery_id, group_did, group_event_seq, target_did, target_service_did,
          method, envelope_json, status, next_attempt_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            new_id("gdlv"),
            group_did,
            group_event_seq,
            target_did,
            target_service_did,
            method,
            _json(envelope),
            created_at,
            created_at,
            created_at,
        ),
    )


def enqueue_state_changed(
    conn: Any,
    settings: Settings,
    *,
    group_did: str,
    group_event_seq: int,
    event: dict[str, Any],
    created_at: str,
) -> None:
    operation_id = str(event["group_receipt"]["operation_id"])
    for member in _remote_members(conn, settings, group_did):
        target_did = str(member["agent_did"])
        envelope = {
            "jsonrpc": "2.0",
            "method": "group.state_changed",
            "params": {
                "meta": {
                    "anp_version": "1.0",
                    "profile": "anp.group.base.v1",
                    "security_profile": "transport-protected",
                    "sender_did": group_did,
                    "target": {"kind": "agent", "did": target_did},
                    "operation_id": operation_id,
                    "content_type": "application/json",
                },
                "body": event,
            },
        }
        _enqueue(
            conn,
            group_did=group_did,
            group_event_seq=group_event_seq,
            target_did=target_did,
            target_service_did=str(member["home_service_did"]),
            method="group.state_changed",
            envelope=envelope,
            created_at=created_at,
        )


def enqueue_incoming_message(
    conn: Any,
    settings: Settings,
    *,
    group_did: str,
    group_state_version: int,
    group_event_seq: int,
    sender_did: str,
    operation_id: str,
    message_id: str,
    content_type: str,
    original_meta: dict[str, Any],
    body: dict[str, Any],
    auth: dict[str, Any],
    receipt: dict[str, Any],
    accepted_at: str,
) -> None:
    delivery_body = {
        "group_did": group_did,
        "group_state_version": str(group_state_version),
        "group_event_seq": str(group_event_seq),
        "accepted_at": accepted_at,
        "group_receipt": receipt,
        **body,
    }
    for member in _remote_members(conn, settings, group_did):
        target_did = str(member["agent_did"])
        envelope = {
            "jsonrpc": "2.0",
            "method": "group.incoming",
            "params": {
                "meta": {**original_meta, "target": {"kind": "agent", "did": target_did}},
                "auth": auth,
                "body": delivery_body,
            },
        }
        _enqueue(
            conn,
            group_did=group_did,
            group_event_seq=group_event_seq,
            target_did=target_did,
            target_service_did=str(member["home_service_did"]),
            method="group.incoming",
            envelope=envelope,
            created_at=accepted_at,
        )
