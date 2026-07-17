from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any

from fastapi import FastAPI

from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import InvalidParams, Unauthorized
from awiki_open_server.shared.ids import now_iso


MAX_DELIVERY_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 300
logger = logging.getLogger(__name__)


def _next_attempt(attempt_count: int) -> str:
    delay = min(MAX_BACKOFF_SECONDS, 2 ** max(0, attempt_count - 1))
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


def _error_summary(exc: Exception) -> str:
    value = f"{type(exc).__name__}: {exc}"
    return value[:500]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def group_operations_status(app: FastAPI) -> dict[str, Any]:
    settings = app.state.settings
    with app.state.store.connect() as conn:
        counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM group_delivery_outbox GROUP BY status"
            ).fetchall()
        }
        oldest = conn.execute(
            "SELECT MIN(created_at) AS created_at FROM group_delivery_outbox WHERE status IN ('pending', 'retry')"
        ).fetchone()["created_at"]
        hosted_groups = int(conn.execute("SELECT COUNT(*) AS count FROM hosted_groups").fetchone()["count"])
        active_members = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM hosted_group_members WHERE status = 'active'"
            ).fetchone()["count"]
        )
    now = datetime.now(timezone.utc)
    oldest_time = _parse_time(oldest)
    heartbeat = getattr(app.state, "group_outbox_last_heartbeat", None)
    heartbeat_time = _parse_time(heartbeat)
    db_path = settings.db_path
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    key_dir = settings.group_key_dir
    return {
        "groups": {"hosted": hosted_groups, "active_members": active_members},
        "outbox": {
            "pending": counts.get("pending", 0),
            "retry": counts.get("retry", 0),
            "delivered": counts.get("delivered", 0),
            "dead": counts.get("dead", 0),
            "oldest_pending_age_seconds": (
                max(0, int((now - oldest_time).total_seconds())) if oldest_time is not None else None
            ),
            "worker_last_heartbeat": heartbeat,
            "worker_heartbeat_age_seconds": (
                max(0, int((now - heartbeat_time).total_seconds())) if heartbeat_time is not None else None
            ),
            "last_drain": getattr(app.state, "group_outbox_last_result", None),
        },
        "storage": {
            "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "group_key_directory": {
                "exists": key_dir.is_dir(),
                "readable": key_dir.is_dir() and os.access(key_dir, os.R_OK),
                "writable": key_dir.is_dir() and os.access(key_dir, os.W_OK),
            },
        },
    }


def _deliver(app: FastAPI, row: Any) -> None:
    settings = app.state.settings
    service = runtime._discover_anp_service(str(row["target_did"]), settings)
    discovered_service_did = service.get("serviceDid")
    if discovered_service_did != row["target_service_did"]:
        raise Unauthorized(
            "outbox_target_service_did_changed",
            data={"expected": row["target_service_did"], "actual": discovered_service_did},
        )
    endpoint = service.get("serviceEndpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise InvalidParams("anp_service_endpoint_required")
    envelope = json.loads(row["envelope_json"])
    if not isinstance(envelope, dict) or "id" in envelope:
        raise InvalidParams("group_notification_envelope_invalid")
    body_bytes = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-anp-source-service-did": settings.service_did,
    }
    identity = getattr(app.state, "service_identity", None)
    if identity is None:
        if not settings.allow_unsigned_peer_dev:
            raise Unauthorized("service_identity_not_configured")
    else:
        headers.update(identity.sign_headers(endpoint, "POST", headers, body_bytes))
    response = runtime._http_post_json(endpoint, envelope, headers=headers, body_bytes=body_bytes)
    if isinstance(response, dict) and isinstance(response.get("error"), dict):
        raise InvalidParams(
            "remote_group_notification_rejected",
            data={"message": response["error"].get("message")},
        )


def drain_group_outbox_once(app: FastAPI, *, limit: int = 50) -> dict[str, int]:
    lock = app.state.group_outbox_lock
    if not lock.acquire(blocking=False):
        return {"selected": 0, "delivered": 0, "retried": 0, "dead": 0}
    try:
        return _drain_group_outbox_locked(app, limit=limit)
    finally:
        lock.release()


def _drain_group_outbox_locked(app: FastAPI, *, limit: int) -> dict[str, int]:
    store = app.state.store
    now = now_iso()
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT candidate.* FROM group_delivery_outbox AS candidate
            WHERE candidate.status IN ('pending', 'retry') AND candidate.next_attempt_at <= ?
              AND NOT EXISTS (
                SELECT 1 FROM group_delivery_outbox AS earlier
                WHERE earlier.group_did = candidate.group_did
                  AND earlier.target_did = candidate.target_did
                  AND earlier.group_event_seq < candidate.group_event_seq
                  AND earlier.status NOT IN ('delivered', 'dead')
              )
            ORDER BY candidate.next_attempt_at, candidate.created_at
            LIMIT ?
            """,
            (now, max(1, min(limit, 100))),
        ).fetchall()
    delivered = 0
    retried = 0
    dead = 0
    for row in rows:
        attempt_count = int(row["attempt_count"]) + 1
        try:
            _deliver(app, row)
        except Exception as exc:
            status = "dead" if attempt_count >= MAX_DELIVERY_ATTEMPTS else "retry"
            next_attempt_at = now if status == "dead" else _next_attempt(attempt_count)
            with store.connect() as conn:
                conn.execute(
                    """
                    UPDATE group_delivery_outbox
                    SET status = ?, attempt_count = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                    WHERE delivery_id = ? AND status IN ('pending', 'retry')
                    """,
                    (
                        status,
                        attempt_count,
                        next_attempt_at,
                        _error_summary(exc),
                        now_iso(),
                        row["delivery_id"],
                    ),
                )
            if status == "dead":
                dead += 1
            else:
                retried += 1
            logger.warning(
                "group outbox delivery failed delivery_id=%s method=%s group_event_seq=%s "
                "target_service_did=%s attempt_count=%s status=%s result_code=%s",
                row["delivery_id"],
                row["method"],
                row["group_event_seq"],
                row["target_service_did"],
                attempt_count,
                status,
                getattr(exc, "error_message", type(exc).__name__),
            )
            continue
        with store.connect() as conn:
            conn.execute(
                """
                UPDATE group_delivery_outbox
                SET status = 'delivered', attempt_count = ?, last_error = NULL, updated_at = ?
                WHERE delivery_id = ? AND status IN ('pending', 'retry')
                """,
                (attempt_count, now_iso(), row["delivery_id"]),
            )
        delivered += 1
    return {"selected": len(rows), "delivered": delivered, "retried": retried, "dead": dead}


async def run_group_outbox(app: FastAPI, *, interval_seconds: float = 1.0) -> None:
    while True:
        try:
            result = await asyncio.to_thread(drain_group_outbox_once, app)
            app.state.group_outbox_last_result = result
        except Exception as exc:
            logger.error("group outbox worker cycle failed result_code=%s", type(exc).__name__)
        app.state.group_outbox_last_heartbeat = now_iso()
        await asyncio.sleep(interval_seconds)


__all__ = ["drain_group_outbox_once", "group_operations_status", "run_group_outbox"]
