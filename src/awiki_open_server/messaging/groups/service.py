from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jcs
from fastapi import Request

from awiki_open_server.messaging.groups.delivery import (
    enqueue_incoming_message,
    enqueue_state_changed,
    ensure_outbox_capacity,
)
from awiki_open_server.messaging.groups.identity import (
    binding_generation_is_newer,
    generate_group_identity,
    persist_group_private_key,
    resolve_handle_binding,
    sign_receipt,
)
from awiki_open_server.messaging.groups.projection import (
    project_hosted_message_for_local_members,
    refresh_hosted_local_projections,
)
from awiki_open_server.protocol.anp_adapter import build_content_digest
from awiki_open_server.service_identity import validate_origin_proof_structure
from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import Conflict, InvalidParams, NotFound, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.user_compat.core import current_did, get_settings, get_store


GROUP_PROFILE = "anp.group.base.v1"
TRANSPORT_SECURITY = "transport-protected"
MAX_MEMBERS = 100
ROLE_LEVEL = {"member": 1, "admin": 2, "owner": 3}
POLICY_KEYS = {
    "message_security_profile",
    "bootstrap_security_profile",
    "admission_mode",
    "permissions",
    "attachments_allowed",
    "max_members",
}
PERMISSION_KEYS = {"send", "add", "remove", "update_profile", "update_policy"}
DEFAULT_POLICY = {
    "message_security_profile": TRANSPORT_SECURITY,
    "bootstrap_security_profile": TRANSPORT_SECURITY,
    "admission_mode": "open-join",
    "permissions": {
        "send": "member",
        "add": "admin",
        "remove": "admin",
        "update_profile": "admin",
        "update_policy": "owner",
    },
    "attachments_allowed": False,
    "max_members": str(MAX_MEMBERS),
}


@dataclass(frozen=True)
class GroupRequest:
    method: str
    sender_did: str
    operation_id: str
    target_did: str
    meta: dict[str, Any]
    auth: dict[str, Any]
    body: dict[str, Any]
    payload_digest: str


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str) -> Any:
    return json.loads(value)


def _public_request(request: Request) -> bool:
    settings = get_settings(request)
    return request.url.path.rstrip("/") == settings.anp_public_rpc_path.rstrip("/")


def _require_string(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidParams(error)
    return value


def _home_service_did(request: Request, did: str) -> str:
    settings = get_settings(request)
    if runtime._did_belongs_to_domain(did, settings.did_domain):
        return settings.service_did
    service = runtime._discover_anp_service(did, settings)
    return _require_string(service.get("serviceDid"), "anp_service_did_required")


def _request_context(
    params: dict[str, Any],
    request: Request,
    *,
    method: str,
    target_kind: str,
) -> GroupRequest:
    meta = params.get("_anp_meta")
    body = params.get("_anp_body")
    auth = params.get("_anp_auth")
    if not isinstance(meta, dict) or not isinstance(body, dict):
        raise Unauthorized("missing_origin_proof")
    if not isinstance(auth, dict):
        raise Unauthorized("missing_origin_proof")
    if auth.get("scheme") != "anp-rfc9421-origin-proof-v1":
        raise Unauthorized("invalid_origin_proof_scheme")
    if meta.get("profile") != GROUP_PROFILE:
        raise InvalidParams("anp_meta_profile_mismatch", data={"expected": GROUP_PROFILE, "actual": meta.get("profile")})
    if meta.get("security_profile") != TRANSPORT_SECURITY:
        raise InvalidParams(
            "anp_meta_security_profile_mismatch",
            data={"expected": TRANSPORT_SECURITY, "actual": meta.get("security_profile")},
        )
    sender_did = _require_string(meta.get("sender_did"), "anp_meta_sender_did_required")
    operation_id = _require_string(meta.get("operation_id"), "anp_meta_operation_id_required")
    target = meta.get("target")
    if not isinstance(target, dict):
        raise InvalidParams("anp_meta_target_required")
    if target.get("kind") != target_kind:
        raise InvalidParams(
            "anp_meta_target_kind_mismatch",
            data={"expected": target_kind, "actual": target.get("kind")},
        )
    target_did = _require_string(target.get("did"), "anp_meta_target_did_required")

    public = _public_request(request)
    authenticated = current_did(request, required=not public)
    if authenticated is not None and authenticated != sender_did:
        raise Unauthorized("sender_did_mismatch")
    validate_origin_proof_structure(
        auth,
        method=method,
        meta=meta,
        body=body,
        sender_did_document=runtime._resolve_did_document_for_proof(request, sender_did),
    )
    if public:
        runtime._verify_peer_request_signature(
            request,
            get_settings(request),
            caller_anchor=sender_did,
        )
    payload_digest = build_content_digest(jcs.canonicalize({"method": method, "meta": meta, "body": body}))
    return GroupRequest(method, sender_did, operation_id, target_did, meta, auth, body, payload_digest)


def _validate_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidParams("group.policy_required")
    extra = sorted(set(value) - POLICY_KEYS)
    if extra:
        raise InvalidParams("group.policy_fields_invalid", data={"fields": extra})
    policy = {**DEFAULT_POLICY, **value}
    if policy["message_security_profile"] != TRANSPORT_SECURITY or policy["bootstrap_security_profile"] != TRANSPORT_SECURITY:
        raise InvalidParams("group.security_profile_not_supported")
    if policy["admission_mode"] not in {"open-join", "admin-add"}:
        raise InvalidParams("group.admission_mode_invalid")
    permissions = policy.get("permissions")
    if not isinstance(permissions, dict) or set(permissions) != PERMISSION_KEYS:
        raise InvalidParams("group.permissions_invalid")
    if any(role not in ROLE_LEVEL for role in permissions.values()):
        raise InvalidParams("group.permission_role_invalid")
    try:
        max_members = int(policy.get("max_members", MAX_MEMBERS))
    except (TypeError, ValueError) as exc:
        raise InvalidParams("group.max_members_invalid") from exc
    if max_members < 1 or max_members > MAX_MEMBERS:
        raise InvalidParams("group.max_members_exceeded", data={"limit": str(MAX_MEMBERS)})
    policy["max_members"] = str(max_members)
    if not isinstance(policy.get("attachments_allowed", False), bool):
        raise InvalidParams("group.attachments_allowed_invalid")
    return policy


def _validate_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidParams("group.profile_required")
    profile = dict(value)
    profile.setdefault("discoverability", "public")
    if profile["discoverability"] not in {"public", "listed", "private"}:
        raise InvalidParams("group.discoverability_invalid")
    return profile


def _merge_patch(document: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return patch
    result = dict(document) if isinstance(document, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _merge_patch(result.get(key), value)
    return result


def _operation_replay(conn: Any, context: GroupRequest, scope: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT payload_digest, result_json FROM group_operations
        WHERE sender_did = ? AND group_scope = ? AND method = ? AND operation_id = ?
        """,
        (context.sender_did, scope, context.method, context.operation_id),
    ).fetchone()
    if not row:
        return None
    if row["payload_digest"] != context.payload_digest:
        raise Conflict(
            "group.operation_id_conflict",
            data={"operation_id": context.operation_id, "method": context.method},
        )
    result = _load(row["result_json"])
    result["idempotent_replay"] = True
    return result


def _store_operation(conn: Any, context: GroupRequest, scope: str, result: dict[str, Any], created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO group_operations(
          sender_did, group_scope, method, operation_id, payload_digest, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context.sender_did,
            scope,
            context.method,
            context.operation_id,
            context.payload_digest,
            _json(result),
            created_at,
        ),
    )


def _group_row(conn: Any, group_did: str) -> Any:
    row = conn.execute("SELECT * FROM hosted_groups WHERE group_did = ?", (group_did,)).fetchone()
    if not row:
        raise NotFound("group.not_found")
    return row


def _active_member(conn: Any, group_did: str, agent_did: str) -> Any:
    row = conn.execute(
        "SELECT * FROM hosted_group_members WHERE group_did = ? AND agent_did = ? AND status = 'active'",
        (group_did, agent_did),
    ).fetchone()
    if not row:
        raise Unauthorized("group.not_member")
    return row


def _require_permission(group: Any, member: Any, permission: str) -> None:
    policy = _load(group["policy_json"])
    minimum = policy["permissions"][permission]
    if ROLE_LEVEL.get(member["role"], 0) < ROLE_LEVEL[minimum]:
        raise Unauthorized("group.permission_denied", data={"permission": permission})


def _key_reference(conn: Any, group_did: str) -> str:
    row = conn.execute(
        "SELECT key_reference FROM group_did_documents WHERE group_did = ?",
        (group_did,),
    ).fetchone()
    if not row:
        raise InvalidParams("group_receipt_key_unavailable")
    return str(row["key_reference"])


def _receipt(
    conn: Any,
    context: GroupRequest,
    *,
    group_did: str,
    state_version: int,
    event_seq: int,
    accepted_at: str,
    message_id: str | None = None,
) -> dict[str, Any]:
    value = {
        "receipt_type": "group-message-accepted" if context.method == "group.send" else "group-operation-accepted",
        "group_did": group_did,
        "group_state_version": str(state_version),
        "group_event_seq": str(event_seq),
        "subject_method": context.method,
        "operation_id": context.operation_id,
        "actor_did": context.sender_did,
        "accepted_at": accepted_at,
        "payload_digest": context.payload_digest,
    }
    if message_id is not None:
        value["message_id"] = message_id
    return sign_receipt(value, _key_reference(conn, group_did))


def _write_event(
    conn: Any,
    context: GroupRequest,
    *,
    group_did: str,
    state_version: int,
    event_seq: int,
    event_type: str,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO hosted_group_events(
          group_did, group_event_seq, event_id, event_type, group_state_version,
          subject_method, actor_did, payload_json, payload_digest, receipt_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            group_did,
            event_seq,
            new_id("gevt"),
            event_type,
            state_version,
            context.method,
            context.sender_did,
            _json(payload),
            context.payload_digest,
            _json(receipt),
            created_at,
        ),
    )


def _sync_active_members(conn: Any, group_did: str, event_type: str, payload: dict[str, Any]) -> None:
    rows = conn.execute(
        "SELECT agent_did FROM hosted_group_members WHERE group_did = ? AND status = 'active'",
        (group_did,),
    ).fetchall()
    for row in rows:
        if runtime._user_exists(conn, str(row["agent_did"])):
            runtime.add_sync_event(conn, str(row["agent_did"]), event_type, payload)


def is_hosted_group(request: Request, group_did: str | None) -> bool:
    if not group_did:
        return False
    with get_store(request).connect() as conn:
        return conn.execute("SELECT 1 FROM hosted_groups WHERE group_did = ?", (group_did,)).fetchone() is not None


def has_group_projection(request: Request, group_did: str | None, owner_did: str | None = None) -> bool:
    if not group_did:
        return False
    owner = owner_did or current_did(request)
    with get_store(request).connect() as conn:
        return conn.execute(
            "SELECT 1 FROM group_views WHERE owner_did = ? AND group_did = ? AND membership_status = 'active'",
            (owner, group_did),
        ).fetchone() is not None


def hosted_group_create(params: dict[str, Any], request: Request) -> dict[str, Any]:
    context = _request_context(params, request, method="group.create", target_kind="service")
    settings = get_settings(request)
    if context.target_did != settings.service_did:
        raise InvalidParams("group.target_service_mismatch")
    if _public_request(request) or not runtime._did_belongs_to_domain(context.sender_did, settings.did_domain):
        raise Unauthorized("group.remote_create_not_allowed")
    profile = _validate_profile(context.body.get("group_profile", {}))
    policy = _validate_policy(context.body.get("group_policy"))
    initial_members = context.body.get("initial_members", [])
    if not isinstance(initial_members, list):
        raise InvalidParams("group.initial_members_invalid")
    creator_handle = context.body.get("creator_handle")
    creator_binding = resolve_handle_binding(creator_handle) if isinstance(creator_handle, str) else None
    if creator_handle is not None and creator_binding is None:
        raise InvalidParams("group.creator_handle_invalid")
    if creator_binding is not None and creator_binding.did != context.sender_did:
        raise Unauthorized("group.creator_handle_did_mismatch")
    prepared_members: list[tuple[str, str | None, str | None, str, str]] = []
    seen_dids = {context.sender_did}
    seen_handles = {creator_binding.handle} if creator_binding is not None else set()
    for item in initial_members:
        if not isinstance(item, dict):
            raise InvalidParams("group.initial_member_invalid")
        member_did = item.get("member_did")
        member_handle = item.get("member_handle")
        if (member_did is None) == (member_handle is None):
            raise InvalidParams("group.member_identifier_ambiguous")
        binding = resolve_handle_binding(member_handle) if isinstance(member_handle, str) else None
        if member_handle is not None and binding is None:
            raise InvalidParams("group.member_handle_invalid")
        resolved_did = binding.did if binding is not None else _require_string(member_did, "group.member_did_required")
        role = item.get("role", "member")
        if role not in ROLE_LEVEL:
            raise InvalidParams("group.role_invalid")
        if resolved_did in seen_dids or (binding is not None and binding.handle in seen_handles):
            raise Conflict("group.initial_member_duplicate")
        seen_dids.add(resolved_did)
        if binding is not None:
            seen_handles.add(binding.handle)
        prepared_members.append(
            (
                resolved_did,
                binding.handle if binding is not None else None,
                binding.binding_generation if binding is not None else None,
                role,
                _home_service_did(request, resolved_did),
            )
        )
    if len(prepared_members) + 1 > int(policy["max_members"]):
        raise InvalidParams("group.max_members_exceeded")

    scope = settings.service_did
    with get_store(request).connect() as conn:
        replay = _operation_replay(conn, context, scope)
    if replay is not None:
        return replay

    group_id = new_id("grp")
    document, private_key_pem = generate_group_identity(
        hostname=settings.did_domain,
        group_id=group_id,
        service_endpoint=settings.anp_service_endpoint,
        service_did=settings.service_did,
    )
    group_did = str(document["id"])
    key_path = persist_group_private_key(settings.data_dir / "group-keys", group_id, private_key_pem)
    created_at = now_iso()
    try:
        with get_store(request).connect() as conn:
            replay = _operation_replay(conn, context, scope)
            if replay is not None:
                key_path.unlink(missing_ok=True)
                return replay
            conn.execute(
                """
                INSERT INTO hosted_groups(
                  group_did, host_service_did, creator_did, profile_json, policy_json,
                  group_state_version, group_event_seq, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (group_did, settings.service_did, context.sender_did, _json(profile), _json(policy), created_at, created_at),
            )
            conn.execute(
                """
                INSERT INTO hosted_group_members(
                  group_did, agent_did, member_handle, handle_binding_generation,
                  home_service_did, role, status, joined_at
                ) VALUES (?, ?, ?, ?, ?, 'owner', 'active', ?)
                """,
                (
                    group_did,
                    context.sender_did,
                    creator_binding.handle if creator_binding is not None else None,
                    creator_binding.binding_generation if creator_binding is not None else None,
                    settings.service_did,
                    created_at,
                ),
            )
            for member_did, member_handle, generation, role, home_service_did in prepared_members:
                conn.execute(
                    """
                    INSERT INTO hosted_group_members(
                      group_did, agent_did, member_handle, handle_binding_generation,
                      home_service_did, role, status, joined_at, added_by
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        group_did,
                        member_did,
                        member_handle,
                        generation,
                        home_service_did,
                        role,
                        created_at,
                        context.sender_did,
                    ),
                )
            conn.execute(
                "INSERT INTO group_did_documents(group_did, document_json, key_reference, created_at) VALUES (?, ?, ?, ?)",
                (group_did, _json(document), str(key_path), created_at),
            )
            conn.execute(
                "INSERT INTO did_documents(did, document_json, updated_at, status, revoked_at) VALUES (?, ?, ?, 'active', NULL)",
                (group_did, _json(document), created_at),
            )
            receipt = _receipt(
                conn,
                context,
                group_did=group_did,
                state_version=1,
                event_seq=1,
                accepted_at=created_at,
            )
            result = {
                "group_did": group_did,
                "group_state_version": "1",
                "group_event_seq": "1",
                "created_at": created_at,
                "creator_did": context.sender_did,
                "group_profile": profile,
                "group_policy": policy,
                "group_receipt": receipt,
            }
            if creator_binding is not None:
                result["creator_handle"] = creator_binding.handle
                result["handle_binding_generation"] = creator_binding.binding_generation
            _write_event(
                conn,
                context,
                group_did=group_did,
                state_version=1,
                event_seq=1,
                event_type="group-created",
                payload={"group_did": group_did, "creator_did": context.sender_did},
                receipt=receipt,
                created_at=created_at,
            )
            _store_operation(conn, context, scope, result, created_at)
            _sync_active_members(conn, group_did, "group.created", {"group_did": group_did})
            refresh_hosted_local_projections(conn, settings, group_did, updated_at=created_at)
    except Exception:
        key_path.unlink(missing_ok=True)
        raise
    return result


def hosted_group_get_info(params: dict[str, Any], request: Request) -> dict[str, Any]:
    group_did = params.get("group_did")
    if not isinstance(group_did, str):
        raise InvalidParams("group_did_required")
    public = _public_request(request)
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    body = params.get("_anp_body") if isinstance(params.get("_anp_body"), dict) else params
    sender_did: str | None
    if public:
        sender_did = meta.get("sender_did") if isinstance(meta.get("sender_did"), str) else None
        if sender_did is not None:
            runtime._verify_peer_request_signature(
                request,
                get_settings(request),
                caller_anchor=sender_did,
            )
    else:
        sender_did = current_did(request)
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        member = (
            conn.execute(
                """
                SELECT role, status FROM hosted_group_members
                WHERE group_did = ? AND agent_did = ? AND status = 'active'
                """,
                (group_did, sender_did),
            ).fetchone()
            if sender_did is not None
            else None
        )
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM hosted_group_members WHERE group_did = ? AND status = 'active'",
            (group_did,),
        ).fetchone()["count"]
        member_list = None
        if member is not None and body.get("include_member_list") is True:
            member_list = [
                {
                    "agent_did": row["agent_did"],
                    "member_handle": row["member_handle"],
                    "handle_binding_generation": row["handle_binding_generation"],
                    "role": row["role"],
                    "status": row["status"],
                    "joined_at": row["joined_at"],
                }
                for row in conn.execute(
                    """
                    SELECT agent_did, member_handle, handle_binding_generation, role, status, joined_at
                    FROM hosted_group_members
                    WHERE group_did = ? AND status = 'active' ORDER BY joined_at, agent_did
                    """,
                    (group_did,),
                ).fetchall()
            ]
    profile = _load(group["profile_json"])
    discoverability = profile.get("discoverability", "public")
    local_projection = meta.get("profile") == "anp.group.local.v1" and not public
    wants_private_fields = body.get("include_policy") is True or body.get("include_member_list") is True
    if member is None and (discoverability == "private" or wants_private_fields):
        raise Unauthorized("group.policy_violation")
    result = {
        "group_did": group_did,
        "host_service_did": group["host_service_did"],
        "group_state_version": str(group["group_state_version"]),
        "group_event_seq": str(group["group_event_seq"]),
        "group_profile": profile,
        "member_count": str(count),
        "created_at": group["created_at"],
    }
    if member is not None:
        result.update({"member_role": member["role"], "membership_status": member["status"]})
    if member is not None and (body.get("include_policy") is True or local_projection):
        result["group_policy"] = _load(group["policy_json"])
    if member_list is not None:
        result["member_list"] = member_list
    return result


def hosted_group_list(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    owner = current_did(request)
    try:
        limit = int(params.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise InvalidParams("limit_invalid") from exc
    if limit < 1 or limit > 100:
        raise InvalidParams("limit_too_large")
    with get_store(request).connect() as conn:
        rows = conn.execute(
            """
            SELECT g.*, m.role AS member_role, m.status AS membership_status
            FROM hosted_groups g
            JOIN hosted_group_members m ON m.group_did = g.group_did
            WHERE m.agent_did = ? AND m.status = 'active'
            ORDER BY g.updated_at DESC, g.group_did
            LIMIT ?
            """,
            (owner, limit),
        ).fetchall()
    hosted = [
        {
            "group_did": row["group_did"],
            "host_service_did": row["host_service_did"],
            "group_state_version": str(row["group_state_version"]),
            "group_event_seq": str(row["group_event_seq"]),
            "group_profile": _load(row["profile_json"]),
            "group_policy": _load(row["policy_json"]),
            "member_role": row["member_role"],
            "membership_status": row["membership_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    hosted_dids = {item["group_did"] for item in hosted}
    with get_store(request).connect() as conn:
        projection_rows = conn.execute(
            """
            SELECT * FROM group_views
            WHERE owner_did = ? AND membership_status = 'active'
            ORDER BY updated_at DESC, group_did
            LIMIT ?
            """,
            (owner, limit),
        ).fetchall()
    projections = [
        {
            "group_did": row["group_did"],
            "host_service_did": row["host_service_did"],
            "group_state_version": str(row["group_state_version"]),
            "group_event_seq": str(row["group_event_seq"]),
            "group_profile": _load(row["profile_json"]),
            "group_policy": _load(row["policy_json"]),
            "member_role": row["member_role"],
            "membership_status": row["membership_status"],
            "updated_at": row["updated_at"],
        }
        for row in projection_rows
        if row["group_did"] not in hosted_dids
    ]
    return [*hosted, *projections][:limit]


def projected_group_get(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    group_did = _require_string(params.get("group_did"), "group_did_required")
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM group_views WHERE owner_did = ? AND group_did = ? AND membership_status = 'active'",
            (owner, group_did),
        ).fetchone()
    if not row:
        raise NotFound("group.projection_not_found")
    return {
        "group_did": group_did,
        "host_service_did": row["host_service_did"],
        "group_state_version": str(row["group_state_version"]),
        "group_event_seq": str(row["group_event_seq"]),
        "group_profile": _load(row["profile_json"]),
        "group_policy": _load(row["policy_json"]),
        "member_role": row["member_role"],
        "membership_status": row["membership_status"],
        "updated_at": row["updated_at"],
    }


def projected_group_list_members(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    owner = current_did(request)
    group_did = _require_string(params.get("group_did"), "group_did_required")
    with get_store(request).connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM group_views WHERE owner_did = ? AND group_did = ? AND membership_status = 'active'",
            (owner, group_did),
        ).fetchone():
            raise NotFound("group.projection_not_found")
        rows = conn.execute(
            """
            SELECT * FROM group_member_views
            WHERE owner_did = ? AND group_did = ? AND status = 'active'
            ORDER BY joined_at, agent_did
            """,
            (owner, group_did),
        ).fetchall()
    return [{**dict(row), "member_did": row["agent_did"]} for row in rows]


def projected_group_list_messages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    group_did = _require_string(params.get("group_did"), "group_did_required")
    try:
        since = int(params.get("since_event_seq", params.get("since_seq", 0)))
        limit = int(params.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise InvalidParams("group.messages_since_seq_invalid") from exc
    if since < 0 or limit < 1 or limit > 100:
        raise InvalidParams("limit_too_large" if limit > 100 else "group.messages_since_seq_invalid")
    with get_store(request).connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM group_views WHERE owner_did = ? AND group_did = ? AND membership_status = 'active'",
            (owner, group_did),
        ).fetchone():
            raise NotFound("group.projection_not_found")
        rows = conn.execute(
            """
            SELECT * FROM group_message_views
            WHERE owner_did = ? AND group_did = ? AND group_event_seq > ?
            ORDER BY group_event_seq LIMIT ?
            """,
            (owner, group_did, since, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = []
    for row in rows:
        body = _load(row["body_json"])
        content_type = row["content_type"]
        content = body.get("text", body.get("payload", body.get("payload_b64u")))
        message_type = "text" if content_type == "text/plain" else ("attachment_manifest" if content_type == "application/anp-attachment-manifest+json" else "json" if content_type == "application/json" else "binary")
        messages.append(
            {
                "id": row["message_id"],
                "message_id": row["message_id"],
                "group_did": group_did,
                "sender_did": row["sender_did"],
                "operation_id": row["operation_id"],
                "content_type": content_type,
                "body": body,
                "content": content,
                "type": message_type,
                "server_seq": row["group_event_seq"],
                "group_event_seq": str(row["group_event_seq"]),
                "group_state_version": str(row["group_state_version"]),
                "group_receipt": _load(row["receipt_json"]),
                "accepted_at": row["accepted_at"],
            }
        )
    next_seq = messages[-1]["group_event_seq"] if messages else str(since)
    return {
        "group_did": group_did,
        "messages": messages,
        "total": len(messages),
        "has_more": has_more,
        "next_since_seq": next_seq,
        "next_server_seq": next_seq,
        "source": "remote_projection",
    }


def _membership_mutation(
    params: dict[str, Any],
    request: Request,
    *,
    method: str,
) -> dict[str, Any]:
    context = _request_context(params, request, method=method, target_kind="group")
    group_did = context.target_did
    created_at = now_iso()
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        replay = _operation_replay(conn, context, group_did)
        if replay is not None:
            return replay
        policy = _load(group["policy_json"])
        if method == "group.join":
            if policy["admission_mode"] != "open-join":
                raise Unauthorized("group.policy_violation")
            requested_handle = context.body.get("member_handle")
            binding = resolve_handle_binding(requested_handle) if isinstance(requested_handle, str) else None
            if requested_handle is not None and binding is None:
                raise InvalidParams("group.member_handle_invalid")
            if binding is not None and binding.did != context.sender_did:
                raise Unauthorized("group.handle_did_mismatch")
            target_did = binding.did if binding is not None else context.sender_did
            role = "member"
            added_by = None
        else:
            actor = _active_member(conn, group_did, context.sender_did)
            _require_permission(group, actor, "add")
            member_did = context.body.get("member_did")
            member_handle = context.body.get("member_handle")
            if (member_did is None) == (member_handle is None):
                raise InvalidParams("group.member_identifier_ambiguous")
            binding = resolve_handle_binding(member_handle) if isinstance(member_handle, str) else None
            if member_handle is not None and binding is None:
                raise InvalidParams("group.member_handle_invalid")
            target_did = binding.did if binding is not None else _require_string(member_did, "group.member_did_required")
            role = context.body.get("role", "member")
            if role not in ROLE_LEVEL:
                raise InvalidParams("group.role_invalid")
            added_by = context.sender_did
        existing = conn.execute(
            "SELECT status FROM hosted_group_members WHERE group_did = ? AND agent_did = ?",
            (group_did, target_did),
        ).fetchone()
        if existing and existing["status"] == "active":
            raise Conflict("group.member_already_active")
        active_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM hosted_group_members WHERE group_did = ? AND status = 'active'",
                (group_did,),
            ).fetchone()["count"]
        )
        if active_count >= int(policy["max_members"]):
            raise InvalidParams("group.max_members_exceeded")
        home_service_did = _home_service_did(request, target_did)
        conn.execute(
            """
            INSERT INTO hosted_group_members(
              group_did, agent_did, member_handle, handle_binding_generation,
              home_service_did, role, status, joined_at, ended_at, added_by
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?)
            ON CONFLICT(group_did, agent_did) DO UPDATE SET
              member_handle = excluded.member_handle,
              handle_binding_generation = excluded.handle_binding_generation,
              home_service_did = excluded.home_service_did,
              role = excluded.role, status = 'active', joined_at = excluded.joined_at,
              ended_at = NULL, added_by = excluded.added_by
            """,
            (
                group_did,
                target_did,
                binding.handle if binding is not None else None,
                binding.binding_generation if binding is not None else None,
                home_service_did,
                role,
                created_at,
                added_by,
            ),
        )
        ensure_outbox_capacity(
            conn,
            get_settings(request),
            group_did=group_did,
            management_operation=True,
        )
        state_version = int(group["group_state_version"]) + 1
        event_seq = int(group["group_event_seq"]) + 1
        conn.execute(
            "UPDATE hosted_groups SET group_state_version = ?, group_event_seq = ?, updated_at = ? WHERE group_did = ?",
            (state_version, event_seq, created_at, group_did),
        )
        receipt = _receipt(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            accepted_at=created_at,
        )
        result = {
            "group_did": group_did,
            "member_did": target_did,
            "membership_status": "active",
            "role": role,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "group_receipt": receipt,
        }
        if binding is not None:
            result["member_handle"] = binding.handle
            result["handle_binding_generation"] = binding.binding_generation
        event = {
            "group_did": group_did,
            "event_type": "member-activated",
            "subject_method": method,
            "subject_did": target_did,
            "membership_status": "active",
            "role": role,
            "group_profile": _load(group["profile_json"]),
            "group_policy": policy,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "changed_at": created_at,
            "actor_did": context.sender_did,
            "group_receipt": receipt,
        }
        if binding is not None:
            event["subject_handle"] = binding.handle
            event["handle_binding_generation"] = binding.binding_generation
        _write_event(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            event_type="member-activated",
            payload=event,
            receipt=receipt,
            created_at=created_at,
        )
        _store_operation(conn, context, group_did, result, created_at)
        _sync_active_members(conn, group_did, "group.member.activated", event)
        refresh_hosted_local_projections(conn, get_settings(request), group_did, updated_at=created_at)
        enqueue_state_changed(
            conn,
            get_settings(request),
            group_did=group_did,
            group_event_seq=event_seq,
            event=event,
            created_at=created_at,
        )
    return result


def hosted_group_join(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _membership_mutation(params, request, method="group.join")


def hosted_group_add(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _membership_mutation(params, request, method="group.add")


def _end_membership(params: dict[str, Any], request: Request, *, method: str) -> dict[str, Any]:
    context = _request_context(params, request, method=method, target_kind="group")
    group_did = context.target_did
    changed_at = now_iso()
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        replay = _operation_replay(conn, context, group_did)
        if replay is not None:
            return replay
        if method == "group.leave":
            _active_member(conn, group_did, context.sender_did)
            target_did = context.sender_did
            status = "left"
            event_type = "member-left"
        else:
            actor = _active_member(conn, group_did, context.sender_did)
            _require_permission(group, actor, "remove")
            target_did = _require_string(context.body.get("member_did"), "group.member_did_required")
            _active_member(conn, group_did, target_did)
            status = "removed"
            event_type = "member-removed"
        conn.execute(
            "UPDATE hosted_group_members SET status = ?, ended_at = ? WHERE group_did = ? AND agent_did = ?",
            (status, changed_at, group_did, target_did),
        )
        ensure_outbox_capacity(
            conn,
            get_settings(request),
            group_did=group_did,
            management_operation=True,
        )
        state_version = int(group["group_state_version"]) + 1
        event_seq = int(group["group_event_seq"]) + 1
        conn.execute(
            "UPDATE hosted_groups SET group_state_version = ?, group_event_seq = ?, updated_at = ? WHERE group_did = ?",
            (state_version, event_seq, changed_at, group_did),
        )
        receipt = _receipt(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            accepted_at=changed_at,
        )
        result = {
            "group_did": group_did,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "group_receipt": receipt,
        }
        if method == "group.leave":
            result["leaver_did"] = target_did
        else:
            result.update({"member_did": target_did, "membership_status": status})
        event = {
            "group_did": group_did,
            "event_type": event_type,
            "subject_method": method,
            "subject_did": target_did,
            "membership_status": status,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "changed_at": changed_at,
            "actor_did": context.sender_did,
            "group_receipt": receipt,
        }
        _write_event(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            event_type=event_type,
            payload=event,
            receipt=receipt,
            created_at=changed_at,
        )
        _store_operation(conn, context, group_did, result, changed_at)
        _sync_active_members(conn, group_did, f"group.{event_type}", event)
        refresh_hosted_local_projections(conn, get_settings(request), group_did, updated_at=changed_at)
        enqueue_state_changed(
            conn,
            get_settings(request),
            group_did=group_did,
            group_event_seq=event_seq,
            event=event,
            created_at=changed_at,
        )
    return result


def hosted_group_remove(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _end_membership(params, request, method="group.remove")


def hosted_group_leave(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _end_membership(params, request, method="group.leave")


def hosted_group_rebind_member(params: dict[str, Any], request: Request) -> dict[str, Any]:
    context = _request_context(params, request, method="group.rebind_member", target_kind="group")
    group_did = context.target_did
    member_handle = _require_string(context.body.get("member_handle"), "group.member_handle_required")
    previous_did = _require_string(
        context.body.get("previous_member_did"),
        "group.previous_member_did_required",
    )
    new_did = _require_string(context.body.get("new_member_did"), "group.new_member_did_required")
    requested_generation = _require_string(
        context.body.get("handle_binding_generation"),
        "group.handle_binding_generation_required",
    )
    if context.sender_did != new_did:
        raise Unauthorized("group.rebind_sender_mismatch")
    binding = resolve_handle_binding(member_handle)
    if binding.did != new_did:
        raise Unauthorized("group.handle_did_mismatch")
    if binding.binding_generation != requested_generation:
        raise InvalidParams("group.binding_generation_mismatch")

    changed_at = now_iso()
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        replay = _operation_replay(conn, context, group_did)
        if replay is not None:
            return replay
        member = conn.execute(
            """
            SELECT * FROM hosted_group_members
            WHERE group_did = ? AND member_handle = ? AND agent_did = ? AND status = 'active'
            """,
            (group_did, binding.handle, previous_did),
        ).fetchone()
        if not member:
            raise NotFound("group.handle_member_not_found")
        previous_generation = member["handle_binding_generation"]
        if not isinstance(previous_generation, str):
            raise InvalidParams("group.did_only_member_cannot_rebind")
        if not binding_generation_is_newer(binding.binding_generation, previous_generation):
            raise Conflict("group.binding_generation_not_advanced")
        conflicting = conn.execute(
            """
            SELECT 1 FROM hosted_group_members
            WHERE group_did = ? AND agent_did = ? AND status = 'active'
            """,
            (group_did, new_did),
        ).fetchone()
        if conflicting:
            raise Conflict("group.rebind_target_already_member")
        conn.execute(
            """
            UPDATE hosted_group_members
            SET agent_did = ?, handle_binding_generation = ?, home_service_did = ?
            WHERE group_did = ? AND member_handle = ? AND agent_did = ? AND status = 'active'
            """,
            (
                new_did,
                binding.binding_generation,
                _home_service_did(request, new_did),
                group_did,
                binding.handle,
                previous_did,
            ),
        )
        ensure_outbox_capacity(
            conn,
            get_settings(request),
            group_did=group_did,
            management_operation=True,
        )
        state_version = int(group["group_state_version"]) + 1
        event_seq = int(group["group_event_seq"]) + 1
        conn.execute(
            "UPDATE hosted_groups SET group_state_version = ?, group_event_seq = ?, updated_at = ? WHERE group_did = ?",
            (state_version, event_seq, changed_at, group_did),
        )
        receipt = _receipt(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            accepted_at=changed_at,
        )
        result = {
            "group_did": group_did,
            "member_handle": binding.handle,
            "previous_member_did": previous_did,
            "member_did": new_did,
            "handle_binding_generation": binding.binding_generation,
            "membership_status": "active",
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "group_receipt": receipt,
        }
        event = {
            "group_did": group_did,
            "event_type": "member-credential-rebound",
            "subject_method": context.method,
            "subject_handle": binding.handle,
            "previous_subject_did": previous_did,
            "subject_did": new_did,
            "handle_binding_generation": binding.binding_generation,
            "membership_status": "active",
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "changed_at": changed_at,
            "actor_did": context.sender_did,
            "group_receipt": receipt,
        }
        _write_event(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            event_type="member-credential-rebound",
            payload=event,
            receipt=receipt,
            created_at=changed_at,
        )
        _store_operation(conn, context, group_did, result, changed_at)
        _sync_active_members(conn, group_did, "group.member.credential_rebound", event)
        refresh_hosted_local_projections(conn, get_settings(request), group_did, updated_at=changed_at)
        enqueue_state_changed(
            conn,
            get_settings(request),
            group_did=group_did,
            group_event_seq=event_seq,
            event=event,
            created_at=changed_at,
        )
    return result


def _update_group(params: dict[str, Any], request: Request, *, method: str) -> dict[str, Any]:
    context = _request_context(params, request, method=method, target_kind="group")
    group_did = context.target_did
    changed_at = now_iso()
    permission = "update_profile" if method == "group.update_profile" else "update_policy"
    patch_key = "group_profile_patch" if method == "group.update_profile" else "group_policy_patch"
    patch = context.body.get(patch_key)
    if not isinstance(patch, dict):
        raise InvalidParams(f"group.{patch_key}_required")
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        replay = _operation_replay(conn, context, group_did)
        if replay is not None:
            return replay
        member = _active_member(conn, group_did, context.sender_did)
        _require_permission(group, member, permission)
        ensure_outbox_capacity(
            conn,
            get_settings(request),
            group_did=group_did,
            management_operation=True,
        )
        if method == "group.update_profile":
            value = _validate_profile(_merge_patch(_load(group["profile_json"]), patch))
            column = "profile_json"
            result_key = "group_profile"
            event_type = "group-profile-updated"
        else:
            value = _validate_policy(_merge_patch(_load(group["policy_json"]), patch))
            column = "policy_json"
            result_key = "group_policy"
            event_type = "group-policy-updated"
        state_version = int(group["group_state_version"]) + 1
        event_seq = int(group["group_event_seq"]) + 1
        conn.execute(
            f"UPDATE hosted_groups SET {column} = ?, group_state_version = ?, group_event_seq = ?, updated_at = ? WHERE group_did = ?",
            (_json(value), state_version, event_seq, changed_at, group_did),
        )
        receipt = _receipt(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            accepted_at=changed_at,
        )
        result = {
            "group_did": group_did,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            result_key: value,
            "group_receipt": receipt,
        }
        event = {
            "group_did": group_did,
            "event_type": event_type,
            "subject_method": method,
            "group_state_version": str(state_version),
            "group_event_seq": str(event_seq),
            "changed_at": changed_at,
            "actor_did": context.sender_did,
            result_key: value,
            "group_receipt": receipt,
        }
        _write_event(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            event_type=event_type,
            payload=event,
            receipt=receipt,
            created_at=changed_at,
        )
        _store_operation(conn, context, group_did, result, changed_at)
        _sync_active_members(conn, group_did, f"group.{event_type}", event)
        refresh_hosted_local_projections(conn, get_settings(request), group_did, updated_at=changed_at)
        enqueue_state_changed(
            conn,
            get_settings(request),
            group_did=group_did,
            group_event_seq=event_seq,
            event=event,
            created_at=changed_at,
        )
    return result


def hosted_group_update_profile(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _update_group(params, request, method="group.update_profile")


def hosted_group_update_policy(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _update_group(params, request, method="group.update_policy")


def hosted_group_send(params: dict[str, Any], request: Request) -> dict[str, Any]:
    context = _request_context(params, request, method="group.send", target_kind="group")
    group_did = context.target_did
    message_id = _require_string(context.meta.get("message_id"), "anp_meta_message_id_required")
    content_type = _require_string(context.meta.get("content_type"), "anp_meta_content_type_required")
    content_fields = [key for key in ("text", "payload", "payload_b64u") if key in context.body]
    if len(content_fields) != 1:
        raise InvalidParams("group.message_content_required")
    if content_type == "text/plain" and not isinstance(context.body.get("text"), str):
        raise InvalidParams("message_body_text_required")
    if content_type in {"application/json", "application/anp-attachment-manifest+json"} and not isinstance(context.body.get("payload"), dict):
        raise InvalidParams("message_body_payload_object_required")
    if len(jcs.canonicalize(context.body)) > get_settings(request).group_max_message_bytes:
        raise InvalidParams(
            "group.message_too_large",
            data={"limit": get_settings(request).group_max_message_bytes},
        )
    accepted_at = now_iso()
    with get_store(request).connect() as conn:
        group = _group_row(conn, group_did)
        replay = _operation_replay(conn, context, group_did)
        if replay is not None:
            return replay
        member = _active_member(conn, group_did, context.sender_did)
        _require_permission(group, member, "send")
        ensure_outbox_capacity(
            conn,
            get_settings(request),
            group_did=group_did,
            management_operation=False,
        )
        existing = conn.execute("SELECT operation_id FROM hosted_group_messages WHERE message_id = ?", (message_id,)).fetchone()
        if existing:
            raise Conflict("message_id_conflict", data={"message_id": message_id})
        state_version = int(group["group_state_version"])
        event_seq = int(group["group_event_seq"]) + 1
        conn.execute(
            "UPDATE hosted_groups SET group_event_seq = ?, updated_at = ? WHERE group_did = ?",
            (event_seq, accepted_at, group_did),
        )
        receipt = _receipt(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            accepted_at=accepted_at,
            message_id=message_id,
        )
        conn.execute(
            """
            INSERT INTO hosted_group_messages(
              message_id, group_did, group_event_seq, sender_did, operation_id,
              body_json, content_type, origin_auth_json, receipt_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                group_did,
                event_seq,
                context.sender_did,
                context.operation_id,
                _json(context.body),
                content_type,
                _json(context.auth),
                _json(receipt),
                accepted_at,
            ),
        )
        result = {
            "accepted": True,
            "delivery_state": "accepted",
            "final_acceptance": True,
            "message_id": message_id,
            "operation_id": context.operation_id,
            "group_did": group_did,
            "sender_did": context.sender_did,
            "server_seq": event_seq,
            "group_event_seq": str(event_seq),
            "group_state_version": str(state_version),
            "accepted_at": accepted_at,
            "content_type": content_type,
            "body": context.body,
            "group_receipt": receipt,
        }
        _write_event(
            conn,
            context,
            group_did=group_did,
            state_version=state_version,
            event_seq=event_seq,
            event_type="group-message-created",
            payload={
                "group_did": group_did,
                "message_id": message_id,
                "sender_did": context.sender_did,
                "group_event_seq": str(event_seq),
            },
            receipt=receipt,
            created_at=accepted_at,
        )
        _store_operation(conn, context, group_did, result, accepted_at)
        refresh_hosted_local_projections(conn, get_settings(request), group_did, updated_at=accepted_at)
        project_hosted_message_for_local_members(
            conn,
            get_settings(request),
            group_did=group_did,
            message_id=message_id,
            group_event_seq=event_seq,
            group_state_version=state_version,
            sender_did=context.sender_did,
            operation_id=context.operation_id,
            content_type=content_type,
            body=context.body,
            receipt=receipt,
            accepted_at=accepted_at,
        )
        enqueue_incoming_message(
            conn,
            get_settings(request),
            group_did=group_did,
            group_state_version=state_version,
            group_event_seq=event_seq,
            sender_did=context.sender_did,
            operation_id=context.operation_id,
            message_id=message_id,
            content_type=content_type,
            original_meta=context.meta,
            body=context.body,
            auth=context.auth,
            receipt=receipt,
            accepted_at=accepted_at,
        )
        _sync_active_members(
            conn,
            group_did,
            "group.message.created",
            {
                "thread_kind": "group",
                "thread": {"kind": "group", "group_did": group_did},
                "message": {
                    "id": f"{group_did}:{event_seq}",
                    "message_id": message_id,
                    "server_seq": str(event_seq),
                    "group_event_seq": str(event_seq),
                    "group_did": group_did,
                    "sender_did": context.sender_did,
                    "content_type": content_type,
                },
            },
        )
    return result


def hosted_group_list_members(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    owner = current_did(request)
    group_did = _require_string(params.get("group_did"), "group_did_required")
    with get_store(request).connect() as conn:
        _group_row(conn, group_did)
        _active_member(conn, group_did, owner)
        rows = conn.execute(
            """
            SELECT agent_did, member_handle, handle_binding_generation, role, status, joined_at, added_by
            FROM hosted_group_members
            WHERE group_did = ? AND status = 'active'
            ORDER BY joined_at, agent_did
            """,
            (group_did,),
        ).fetchall()
    return [
        {
            **dict(row),
            "member_did": row["agent_did"],
            **(
                {"handle_binding_generation": str(row["handle_binding_generation"])}
                if row["handle_binding_generation"] is not None
                else {}
            ),
        }
        for row in rows
    ]


def hosted_group_list_messages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    group_did = _require_string(params.get("group_did"), "group_did_required")
    try:
        since = int(params.get("since_event_seq", params.get("since_seq", 0)))
        limit = int(params.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise InvalidParams("group.messages_since_seq_invalid") from exc
    if since < 0 or limit < 1 or limit > 100:
        raise InvalidParams("limit_too_large" if limit > 100 else "group.messages_since_seq_invalid")
    with get_store(request).connect() as conn:
        _group_row(conn, group_did)
        _active_member(conn, group_did, owner)
        rows = conn.execute(
            """
            SELECT * FROM hosted_group_messages
            WHERE group_did = ? AND group_event_seq > ?
            ORDER BY group_event_seq ASC LIMIT ?
            """,
            (group_did, since, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [
        {
            "id": row["message_id"],
            "message_id": row["message_id"],
            "group_did": row["group_did"],
            "sender_did": row["sender_did"],
            "operation_id": row["operation_id"],
            "body": _load(row["body_json"]),
            **(
                {"type": "text", "content": _load(row["body_json"])["text"]}
                if row["content_type"] == "text/plain"
                else {
                    "type": "attachment_manifest" if row["content_type"] == "application/anp-attachment-manifest+json" else ("json" if row["content_type"] == "application/json" else "binary"),
                    "content": _load(row["body_json"]).get("payload", _load(row["body_json"]).get("payload_b64u")),
                }
            ),
            "content_type": row["content_type"],
            "server_seq": row["group_event_seq"],
            "group_event_seq": str(row["group_event_seq"]),
            "created_at": row["created_at"],
            "group_receipt": _load(row["receipt_json"]),
        }
        for row in rows
    ]
    next_seq = messages[-1]["group_event_seq"] if messages else str(since)
    return {
        "group_did": group_did,
        "messages": messages,
        "total": len(messages),
        "has_more": has_more,
        "next_since_seq": next_seq,
        "next_server_seq": next_seq,
        "source": "local_projection",
    }
