from __future__ import annotations

import json
from typing import Any

from awiki_open_server.app.settings import Settings


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def refresh_hosted_local_projections(
    conn: Any,
    settings: Settings,
    group_did: str,
    *,
    updated_at: str,
) -> None:
    group = conn.execute("SELECT * FROM hosted_groups WHERE group_did = ?", (group_did,)).fetchone()
    if not group:
        return
    members = conn.execute(
        "SELECT * FROM hosted_group_members WHERE group_did = ? ORDER BY joined_at, agent_did",
        (group_did,),
    ).fetchall()
    local_active = [
        member
        for member in members
        if member["status"] == "active" and member["home_service_did"] == settings.service_did
    ]
    for owner in local_active:
        owner_did = str(owner["agent_did"])
        conn.execute(
            """
            INSERT INTO group_views(
              owner_did, group_did, host_service_did, profile_json, policy_json,
              group_state_version, group_event_seq, member_role, membership_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_did, group_did) DO UPDATE SET
              host_service_did = excluded.host_service_did,
              profile_json = excluded.profile_json,
              policy_json = excluded.policy_json,
              group_state_version = excluded.group_state_version,
              group_event_seq = excluded.group_event_seq,
              member_role = excluded.member_role,
              membership_status = excluded.membership_status,
              updated_at = excluded.updated_at
            """,
            (
                owner_did,
                group_did,
                group["host_service_did"],
                group["profile_json"],
                group["policy_json"],
                group["group_state_version"],
                group["group_event_seq"],
                owner["role"],
                owner["status"],
                updated_at,
            ),
        )
        for member in members:
            conn.execute(
                """
                INSERT INTO group_member_views(
                  owner_did, group_did, agent_did, member_handle, handle_binding_generation,
                  role, status, joined_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_did, group_did, agent_did) DO UPDATE SET
                  member_handle = excluded.member_handle,
                  handle_binding_generation = excluded.handle_binding_generation,
                  role = excluded.role,
                  status = excluded.status,
                  joined_at = excluded.joined_at,
                  updated_at = excluded.updated_at
                """,
                (
                    owner_did,
                    group_did,
                    member["agent_did"],
                    member["member_handle"],
                    member["handle_binding_generation"],
                    member["role"],
                    member["status"],
                    member["joined_at"],
                    updated_at,
                ),
            )
    active_dids = {str(member["agent_did"]) for member in local_active}
    existing = conn.execute(
        "SELECT owner_did FROM group_views WHERE group_did = ? AND host_service_did = ?",
        (group_did, settings.service_did),
    ).fetchall()
    for row in existing:
        if str(row["owner_did"]) not in active_dids:
            conn.execute(
                "UPDATE group_views SET membership_status = 'inactive', updated_at = ? WHERE owner_did = ? AND group_did = ?",
                (updated_at, row["owner_did"], group_did),
            )


def refresh_remote_member_projection(
    conn: Any,
    *,
    owner_did: str,
    snapshot: dict[str, Any],
    updated_at: str,
) -> bool:
    """Replace a remote roster from an authenticated P4 get_info snapshot."""
    group_did = str(snapshot["group_did"])
    existing = conn.execute(
        "SELECT * FROM group_views WHERE owner_did = ? AND group_did = ? AND membership_status = 'active'",
        (owner_did, group_did),
    ).fetchone()
    if existing is None:
        return False

    state_version = int(snapshot["group_state_version"])
    event_seq = int(snapshot.get("group_event_seq", existing["group_event_seq"]))
    if state_version < int(existing["group_state_version"]) or event_seq < int(existing["group_event_seq"]):
        return False

    members = snapshot["member_list"]
    owner = next(member for member in members if member["member_did"] == owner_did)
    profile = snapshot.get("group_profile")
    policy = snapshot.get("group_policy")
    conn.execute(
        """
        UPDATE group_views SET
          host_service_did = ?, profile_json = ?, policy_json = ?,
          group_state_version = ?, group_event_seq = ?, member_role = ?,
          membership_status = 'active', updated_at = ?
        WHERE owner_did = ? AND group_did = ?
        """,
        (
            snapshot.get("host_service_did") or existing["host_service_did"],
            _json(profile) if isinstance(profile, dict) else existing["profile_json"],
            _json(policy) if isinstance(policy, dict) else existing["policy_json"],
            state_version,
            event_seq,
            owner["role"],
            updated_at,
            owner_did,
            group_did,
        ),
    )
    conn.execute(
        "DELETE FROM group_member_views WHERE owner_did = ? AND group_did = ?",
        (owner_did, group_did),
    )
    for member in members:
        conn.execute(
            """
            INSERT INTO group_member_views(
              owner_did, group_did, agent_did, member_handle, handle_binding_generation,
              role, status, joined_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_did,
                group_did,
                member["member_did"],
                member.get("member_handle"),
                member.get("handle_binding_generation"),
                member["role"],
                member["status"],
                member.get("joined_at"),
                updated_at,
            ),
        )
    return True


def project_hosted_message_for_local_members(
    conn: Any,
    settings: Settings,
    *,
    group_did: str,
    message_id: str,
    group_event_seq: int,
    group_state_version: int,
    sender_did: str,
    operation_id: str,
    content_type: str,
    body: dict[str, Any],
    receipt: dict[str, Any],
    accepted_at: str,
) -> None:
    owners = conn.execute(
        """
        SELECT agent_did FROM hosted_group_members
        WHERE group_did = ? AND status = 'active' AND home_service_did = ?
        """,
        (group_did, settings.service_did),
    ).fetchall()
    for owner in owners:
        conn.execute(
            """
            INSERT OR IGNORE INTO group_message_views(
              owner_did, group_did, message_id, group_event_seq, group_state_version,
              sender_did, operation_id, content_type, body_json, receipt_json, accepted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner["agent_did"],
                group_did,
                message_id,
                group_event_seq,
                group_state_version,
                sender_did,
                operation_id,
                content_type,
                _json(body),
                _json(receipt),
                accepted_at,
            ),
        )
