from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request

from awiki_open_server.messaging.groups.projection import refresh_remote_member_projection
from awiki_open_server.protocol.anp_adapter import verify_group_receipt
from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import Conflict, InvalidParams, NotFound, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.user_compat.core import current_did, get_settings, get_store


MUTATING_GROUP_METHODS = {
    "group.join",
    "group.add",
    "group.remove",
    "group.leave",
    "group.rebind_member",
    "group.update_profile",
    "group.update_policy",
    "group.send",
}

logger = logging.getLogger(__name__)


def _wire_params(params: dict[str, Any]) -> dict[str, Any]:
    meta = params.get("_anp_meta")
    body = params.get("_anp_body")
    if not isinstance(meta, dict) or not isinstance(body, dict):
        raise Unauthorized("missing_origin_proof")
    wire: dict[str, Any] = {"meta": meta, "body": body}
    if isinstance(params.get("_anp_auth"), dict):
        wire["auth"] = params["_anp_auth"]
    if isinstance(params.get("_anp_client"), dict):
        wire["client"] = params["_anp_client"]
    return wire


def _validate_remote_receipt(
    request: Request,
    *,
    method: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> None:
    group_did = str(params["_anp_meta"]["target"]["did"])

    def reject(reason: str) -> None:
        logger.warning(
            "remote group receipt rejected method=%s group_did=%s reason=%s",
            method,
            group_did,
            reason,
        )
        raise InvalidParams("group.invalid_group_receipt")

    receipt = result.get("group_receipt")
    if not isinstance(receipt, dict):
        reject("missing_receipt")
    if receipt.get("group_did") != group_did or receipt.get("subject_method") != method:
        reject("subject_mismatch")
    if receipt.get("operation_id") != params["_anp_meta"].get("operation_id"):
        reject("operation_id_mismatch")
    if receipt.get("group_state_version") != result.get("group_state_version"):
        reject("state_version_mismatch")
    if "group_event_seq" in result and receipt.get("group_event_seq") != result.get("group_event_seq"):
        reject("event_seq_mismatch")
    if method == "group.send" and receipt.get("message_id") != result.get("message_id"):
        reject("message_id_mismatch")
    auth = params.get("_anp_auth")
    origin_proof = auth.get("origin_proof") if isinstance(auth, dict) else None
    if not isinstance(origin_proof, dict) or receipt.get("payload_digest") != origin_proof.get("contentDigest"):
        reject("payload_digest_mismatch")
    document = runtime._resolve_did_document_for_proof(request, group_did)
    if not verify_group_receipt(receipt, issuer_did_document=document):
        reject("proof_verification_failed")


def _apply_terminal_projection(
    request: Request,
    *,
    method: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if method not in {"group.leave", "group.remove", "group.rebind_member"}:
        return
    group_did = str(params["_anp_meta"]["target"]["did"])
    body = params["_anp_body"]
    with get_store(request).connect() as conn:
        if method == "group.leave":
            target_did = str(result.get("leaver_did") or params["_anp_meta"]["sender_did"])
            conn.execute(
                """
                UPDATE group_views SET membership_status = 'left',
                  group_state_version = ?, group_event_seq = ?, updated_at = ?
                WHERE owner_did = ? AND group_did = ?
                """,
                (
                    int(result["group_state_version"]),
                    int(result.get("group_event_seq") or result["group_receipt"]["group_event_seq"]),
                    result["group_receipt"]["accepted_at"],
                    target_did,
                    group_did,
                ),
            )
        elif method == "group.remove":
            target_did = str(result.get("member_did") or body.get("member_did") or "")
            if target_did and runtime._did_belongs_to_domain(target_did, get_settings(request).did_domain):
                conn.execute(
                    """
                    UPDATE group_views SET membership_status = 'removed',
                      group_state_version = ?, group_event_seq = ?, updated_at = ?
                    WHERE owner_did = ? AND group_did = ?
                    """,
                    (
                        int(result["group_state_version"]),
                        int(result.get("group_event_seq") or result["group_receipt"]["group_event_seq"]),
                        result["group_receipt"]["accepted_at"],
                        target_did,
                        group_did,
                    ),
                )
        else:
            previous_did = str(result.get("previous_member_did") or body.get("previous_member_did") or "")
            new_did = str(result.get("member_did") or body.get("new_member_did") or "")
            if previous_did and new_did:
                conn.execute(
                    "UPDATE group_views SET owner_did = ?, updated_at = ? WHERE owner_did = ? AND group_did = ?",
                    (new_did, result["group_receipt"]["accepted_at"], previous_did, group_did),
                )
                conn.execute(
                    "UPDATE group_member_views SET owner_did = ? WHERE owner_did = ? AND group_did = ?",
                    (new_did, previous_did, group_did),
                )
                conn.execute(
                    "UPDATE group_message_views SET owner_did = ? WHERE owner_did = ? AND group_did = ?",
                    (new_did, previous_did, group_did),
                )


def _validated_member_snapshot(
    result: dict[str, Any],
    *,
    group_did: str,
    owner_did: str,
    host_service_did: str,
) -> dict[str, Any]:
    if result.get("group_did") != group_did:
        raise InvalidParams("group.remote_snapshot_identity_mismatch")
    reported_host = result.get("host_service_did")
    if reported_host is not None and reported_host != host_service_did:
        raise InvalidParams("group.remote_snapshot_identity_mismatch")
    state_version = result.get("group_state_version")
    if not isinstance(state_version, str) or not state_version.isdigit():
        raise InvalidParams("group.remote_snapshot_version_invalid", data={"field": "group_state_version"})
    event_seq = result.get("group_event_seq")
    if event_seq is not None and (not isinstance(event_seq, str) or not event_seq.isdigit()):
        raise InvalidParams("group.remote_snapshot_version_invalid", data={"field": "group_event_seq"})
    members = result.get("member_list")
    if not isinstance(members, list):
        raise InvalidParams("group.remote_snapshot_member_list_required")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in members:
        if not isinstance(item, dict):
            raise InvalidParams("group.remote_snapshot_member_invalid")
        member_did = item.get("agent_did")
        role = item.get("role")
        status = item.get("status")
        if not isinstance(member_did, str) or not member_did or member_did in seen:
            raise InvalidParams("group.remote_snapshot_member_invalid")
        if role not in {"owner", "admin", "member"} or status != "active":
            raise InvalidParams("group.remote_snapshot_member_invalid")
        seen.add(member_did)
        normalized.append({**item, "member_did": member_did, "role": role, "status": status})
    if owner_did not in seen:
        raise Unauthorized("group.remote_snapshot_membership_required")
    member_count = result.get("member_count")
    if member_count is not None and str(member_count) != str(len(normalized)):
        raise Conflict("group.remote_snapshot_member_count_mismatch")
    return {**result, "host_service_did": host_service_did, "member_list": normalized}


def refresh_remote_group_members(request: Request, group_did: str) -> bool:
    """Repair a Member Home roster via the standard P4 get_info read."""
    owner_did = current_did(request)
    settings = get_settings(request)
    service = runtime._discover_anp_service(group_did, settings)
    endpoint = service.get("serviceEndpoint")
    host_service_did = service.get("serviceDid")
    if not isinstance(endpoint, str) or not endpoint:
        raise InvalidParams("anp_service_endpoint_required")
    if not isinstance(host_service_did, str) or not host_service_did:
        raise InvalidParams("anp_service_did_required")
    operation_id = new_id("op")
    wire = {
        "meta": {
            "anp_version": "1.0",
            "profile": "anp.group.base.v1",
            "security_profile": "transport-protected",
            "sender_did": owner_did,
            "target": {"kind": "group", "did": group_did},
            "operation_id": operation_id,
            "content_type": "application/json",
        },
        "body": {"include_policy": True, "include_member_list": True},
    }
    payload = {"jsonrpc": "2.0", "method": "group.get_info", "params": wire, "id": operation_id}
    body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-anp-source-service-did": settings.service_did}
    identity = getattr(request.app.state, "service_identity", None)
    if identity is None:
        if not settings.allow_unsigned_peer_dev:
            raise Unauthorized("service_identity_not_configured")
    else:
        headers.update(identity.sign_headers(endpoint, "POST", headers, body_bytes))
    try:
        response = runtime._http_post_json(endpoint, payload, headers=headers, body_bytes=body_bytes)
    except Exception as exc:
        raise InvalidParams("remote_group_snapshot_failed") from exc
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(error, dict):
        raise InvalidParams(
            str(error.get("message") or "remote_group_snapshot_rejected"),
            data={"remote_code": error.get("code")},
        )
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise InvalidParams("remote_group_snapshot_required")
    snapshot = _validated_member_snapshot(
        result,
        group_did=group_did,
        owner_did=owner_did,
        host_service_did=host_service_did,
    )
    with get_store(request).connect() as conn:
        return refresh_remote_member_projection(
            conn,
            owner_did=owner_did,
            snapshot=snapshot,
            updated_at=now_iso(),
        )


def forward_group_command(
    params: dict[str, Any],
    request: Request,
    *,
    method: str,
) -> dict[str, Any]:
    if request.url.path.rstrip("/") != get_settings(request).im_rpc_path.rstrip("/"):
        raise NotFound("group.not_hosted")
    wire_params = _wire_params(params)
    meta = wire_params["meta"]
    sender_did = meta.get("sender_did")
    if not isinstance(sender_did, str) or current_did(request) != sender_did:
        raise Unauthorized("sender_did_mismatch")
    target = meta.get("target")
    if not isinstance(target, dict) or target.get("kind") != "group":
        raise InvalidParams("anp_meta_target_kind_mismatch")
    group_did = target.get("did")
    if not isinstance(group_did, str) or not group_did:
        raise InvalidParams("group_did_required")
    settings = get_settings(request)
    if runtime._did_belongs_to_domain(group_did, settings.did_domain):
        raise NotFound("group.not_found")
    service = runtime._discover_anp_service(group_did, settings)
    endpoint = service.get("serviceEndpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise InvalidParams("anp_service_endpoint_required")
    operation_id = meta.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise InvalidParams("anp_meta_operation_id_required")
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": wire_params,
        "id": operation_id,
    }
    body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-anp-source-service-did": settings.service_did,
    }
    identity = getattr(request.app.state, "service_identity", None)
    if identity is None:
        if not settings.allow_unsigned_peer_dev:
            raise Unauthorized("service_identity_not_configured")
    else:
        headers.update(identity.sign_headers(endpoint, "POST", headers, body_bytes))
    try:
        response = runtime._http_post_json(endpoint, payload, headers=headers, body_bytes=body_bytes)
    except Exception as exc:
        raise InvalidParams("remote_group_delivery_failed", data={"detail": str(exc)}) from exc
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(error, dict):
        remote_data = error.get("data") if isinstance(error.get("data"), dict) else {}
        anp_code = remote_data.get("anp_code")
        error_message = (
            anp_code
            if isinstance(anp_code, str) and anp_code
            else str(error.get("message") or "remote_group_rejected")
        )
        raise InvalidParams(
            error_message,
            data={"remote_code": error.get("code"), "anp_code": anp_code},
        )
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise InvalidParams("remote_group_result_required")
    if method in MUTATING_GROUP_METHODS:
        _validate_remote_receipt(request, method=method, params=params, result=result)
        _apply_terminal_projection(request, method=method, params=params, result=result)
    return result


__all__ = ["forward_group_command", "refresh_remote_group_members"]
