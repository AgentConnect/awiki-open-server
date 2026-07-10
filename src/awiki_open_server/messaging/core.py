from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from fastapi import Request

from awiki_open_server.app.settings import Settings
from awiki_open_server.attachments.core import ATTACHMENT_HANDLERS
from awiki_open_server.service_identity import validate_origin_proof_structure
from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import Conflict, InvalidParams, NotFound, NotSupported, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.user_compat.core import current_did, get_settings, get_store

_json = runtime._json
_load = runtime._load
_did_belongs_to_domain = runtime._did_belongs_to_domain
_discover_anp_service = runtime._discover_anp_service
_object_download_uri = runtime._object_download_uri
_resolve_did_document_for_proof = runtime._resolve_did_document_for_proof
_verify_peer_request_signature = runtime._verify_peer_request_signature
_publish_realtime = runtime._publish_realtime
_user_exists = runtime._user_exists
add_sync_event = runtime.add_sync_event


def _direct_sync_event_payload(
    *,
    message_id: str,
    peer_did: str,
    sender_did: str,
    recipient_did: str,
    server_seq: int,
    content_type: str,
) -> dict[str, Any]:
    return {
        "thread_kind": "direct",
        "thread": {"kind": "direct", "peer_did": peer_did},
        "message": {
            "id": message_id,
            "message_id": message_id,
            "server_seq": str(server_seq),
            "sender_did": sender_did,
            "receiver_did": recipient_did,
            "recipient_did": recipient_did,
            "content_type": _normalize_content_type(content_type),
        },
    }


def _group_sync_event_payload(
    *,
    message_id: str,
    group_did: str,
    sender_did: str,
    server_seq: int,
    content_type: str,
) -> dict[str, Any]:
    return {
        "thread_kind": "group",
        "thread": {"kind": "group", "group_did": group_did},
        "message": {
            "id": f"{group_did}:{server_seq}",
            "message_id": message_id,
            "server_seq": str(server_seq),
            "group_event_seq": str(server_seq),
            "group_did": group_did,
            "sender_did": sender_did,
            "content_type": _normalize_content_type(content_type),
        },
    }


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, body_bytes: bytes | None = None) -> dict[str, Any]:
    return runtime._http_post_json(url, payload, headers=headers, body_bytes=body_bytes)


def capabilities(_: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    return {
        "service_did": settings.service_did,
        "edition": "community",
        "supported_profiles": [
            "anp.core.binding.v1",
            "anp.direct.base.v1",
            "anp.group.base.v1",
            "anp.attachment.v1",
            "anp.sync.local.v1",
            "anp.read_state.local.v1",
            "anp.direct.local.v1",
        ],
        "supported_security_profiles": ["transport-protected"],
        "supported_content_types": [
            "text/plain",
            "application/json",
            "application/anp-attachment-manifest+json",
        ],
        "transports": ["http", "ws"],
        "limits": {
            "max_attachment_bytes": "10485760",
            "max_joined_groups_per_user": "20",
            "max_content_pages_per_handle": "5",
        },
        "proof_policies": {
            "direct_base_origin_proof": "required_for_cross_domain",
            "direct_e2ee_origin_proof": "not_supported",
            "service_http_signature": "required_for_cross_domain",
        },
        "direct_e2ee": {"enabled": False, "reason": "community_edition"},
        "group_e2ee": {"enabled": False, "reason": "community_edition"},
        "features": {
            "cross_domain_direct": {"enabled": True, "mode": "did_discovery_direct_call"},
            "group_participant": {
                "enabled": True,
                "management": False,
                "join_modes": ["open_join", "invite_token"],
                "supported_methods": [
                    "group.get_info",
                    "group.join",
                    "group.leave",
                    "group.send",
                    "group.get",
                    "group.list",
                    "group.list_members",
                    "group.list_messages",
                ],
            },
        },
        "disabled_features": {
            "direct_e2ee": "commercial",
            "group_management": "commercial",
            "group_e2ee": "commercial",
            "federation": "commercial",
            "managed_runtime_agents": "commercial",
            "tenant_site_hosting": "commercial",
        },
    }


def _store_direct_message(
    request: Request,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    content_type: str,
    message_id: str,
    operation_id: str | None,
    idempotency_operation_id: str | None,
    sender_local: bool,
    recipient_local: bool,
    delivery_state: str = "accepted",
    final_acceptance: bool = True,
) -> dict[str, Any]:
    recipient_event_seq: int | None = None
    store = get_store(request)
    body_json = _json(body)
    with store.connect() as conn:
        existing = conn.execute("SELECT * FROM direct_messages WHERE message_id = ?", (message_id,)).fetchone()
        if existing:
            return _direct_idempotent_result_or_raise(
                existing,
                sender=sender,
                recipient=recipient,
                body_json=body_json,
                content_type=content_type,
                operation_id=idempotency_operation_id,
                delivery_state=delivery_state,
                final_acceptance=final_acceptance,
            )
        seq = store.next_seq(conn, "direct_messages")
        created_at = now_iso()
        conn.execute(
            "INSERT INTO direct_messages(message_id, sender_did, recipient_did, operation_id, body_json, content_type, created_at, server_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, sender, recipient, operation_id, body_json, content_type, created_at, seq),
        )
        if sender_local:
            conn.execute("INSERT OR IGNORE INTO direct_message_views(owner_did, message_id, peer_did) VALUES (?, ?, ?)", (sender, message_id, recipient))
            add_sync_event(
                conn,
                sender,
                "direct.message.created",
                _direct_sync_event_payload(
                    message_id=message_id,
                    peer_did=recipient,
                    sender_did=sender,
                    recipient_did=recipient,
                    server_seq=seq,
                    content_type=content_type,
                ),
            )
        if recipient_local:
            conn.execute("INSERT OR IGNORE INTO direct_message_views(owner_did, message_id, peer_did) VALUES (?, ?, ?)", (recipient, message_id, sender))
            recipient_event_seq = add_sync_event(
                conn,
                recipient,
                "direct.message.created",
                _direct_sync_event_payload(
                    message_id=message_id,
                    peer_did=sender,
                    sender_did=sender,
                    recipient_did=recipient,
                    server_seq=seq,
                    content_type=content_type,
                ),
            )
    accepted_at = created_at
    result = {
        "accepted": delivery_state in {"accepted", "delivered"},
        "message_id": message_id,
        "operation_id": operation_id,
        "server_seq": seq,
        "sender_did": sender,
        "recipient_did": recipient,
        "target_did": recipient,
        "delivery_state": delivery_state,
        "final_acceptance": final_acceptance,
        "accepted_at": accepted_at,
        "content_type": content_type,
        "body": body,
    }
    if recipient_local:
        _publish_realtime(
            request,
            recipient,
            "direct.incoming",
            {
                "message": {
                    "message_id": message_id,
                    "sender_did": sender,
                    "recipient_did": recipient,
                    "content_type": content_type,
                    "body": body,
                    "server_seq": seq,
                    "created_at": accepted_at,
                }
            },
            {
                "owner_did": recipient,
                "event_type": "direct.message.created",
                "event_seq": str(recipient_event_seq or 0),
            },
        )
    return result


def _message_conflict(message_id: str, fields: list[str]) -> None:
    raise Conflict("message_id_conflict", data={"message_id": message_id, "fields": fields})


def _stored_operation_id(row: Any) -> str | None:
    if "operation_id" not in row.keys():
        return None
    value = row["operation_id"]
    return str(value) if value is not None else None


def _direct_idempotent_result_or_raise(
    row: Any,
    *,
    sender: str,
    recipient: str,
    body_json: str,
    content_type: str,
    operation_id: str | None,
    delivery_state: str = "accepted",
    final_acceptance: bool = True,
) -> dict[str, Any]:
    fields: list[str] = []
    if row["sender_did"] != sender:
        fields.append("sender_did")
    if row["recipient_did"] != recipient:
        fields.append("recipient_did")
    if row["content_type"] != content_type:
        fields.append("content_type")
    if row["body_json"] != body_json:
        fields.append("body")
    stored_operation_id = _stored_operation_id(row)
    if operation_id is not None and stored_operation_id != operation_id:
        fields.append("operation_id")
    if fields:
        _message_conflict(str(row["message_id"]), fields)
    body = _load(row["body_json"])
    return {
        "accepted": delivery_state in {"accepted", "delivered"},
        "message_id": row["message_id"],
        "operation_id": stored_operation_id or operation_id,
        "server_seq": row["server_seq"],
        "sender_did": row["sender_did"],
        "recipient_did": row["recipient_did"],
        "target_did": row["recipient_did"],
        "delivery_state": delivery_state,
        "final_acceptance": final_acceptance,
        "accepted_at": row["created_at"],
        "content_type": row["content_type"],
        "body": body,
        "idempotent_replay": True,
    }


def _direct_existing_idempotent_result(
    request: Request,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    content_type: str,
    message_id: str,
    operation_id: str | None,
) -> dict[str, Any] | None:
    with get_store(request).connect() as conn:
        existing = conn.execute("SELECT * FROM direct_messages WHERE message_id = ?", (message_id,)).fetchone()
    if not existing:
        return None
    return _direct_idempotent_result_or_raise(
        existing,
        sender=sender,
        recipient=recipient,
        body_json=_json(body),
        content_type=content_type,
        operation_id=operation_id,
    )


def _is_daemon_heartbeat(meta: dict[str, Any], body: dict[str, Any], content_type: str) -> bool:
    payload = body.get("payload")
    return (
        meta.get("profile") == "anp.direct.base.v1"
        and meta.get("security_profile") == "transport-protected"
        and _normalize_content_type(meta.get("content_type") or content_type) == "application/json"
        and _normalize_content_type(content_type) == "application/json"
        and isinstance(payload, dict)
        and payload.get("schema") == "awiki.agent.status.v1"
        and payload.get("status_scope") == "daemon"
        and payload.get("message") == "daemon heartbeat"
    )


def _accept_ephemeral_direct(
    request: Request,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    content_type: str,
    message_id: str,
    operation_id: str | None,
    recipient_local: bool,
) -> dict[str, Any]:
    accepted_at = now_iso()
    result = {
        "accepted": True,
        "message_id": message_id,
        "operation_id": operation_id,
        "sender_did": sender,
        "recipient_did": recipient,
        "target_did": recipient,
        "delivery_state": "ephemeral",
        "final_acceptance": True,
        "accepted_at": accepted_at,
        "content_type": content_type,
        "body": body,
    }
    if recipient_local:
        _publish_realtime(
            request,
            recipient,
            "direct.incoming",
            {
                "message": {
                    "message_id": message_id,
                    "sender_did": sender,
                    "recipient_did": recipient,
                    "content_type": content_type,
                    "body": body,
                    "delivery_state": "ephemeral",
                    "created_at": accepted_at,
                }
            },
        )
    return result


def _remote_direct_payload(
    settings: Settings,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    message_id: str,
    operation_id: str,
    content_type: str,
    meta: dict[str, Any] | None = None,
    auth: dict[str, Any],
    client: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forwarded_meta = dict(meta or {})
    # Do not mutate ANP meta after origin_proof validation. The receiver verifies
    # the proof over the exact meta/body envelope it receives.
    return {
        "jsonrpc": "2.0",
        "method": "direct.send",
        "params": {
            "meta": forwarded_meta,
            "auth": auth,
            "body": body,
            "client": client or {"response_mode": "wait-final"},
        },
        "id": operation_id,
    }


def _send_remote_direct(
    settings: Settings,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    message_id: str,
    operation_id: str,
    content_type: str,
    meta: dict[str, Any] | None,
    auth: dict[str, Any],
    client: dict[str, Any] | None,
    service_identity: Any,
) -> dict[str, Any]:
    service = _discover_anp_service(recipient, settings)
    payload = _remote_direct_payload(
        settings,
        sender=sender,
        recipient=recipient,
        body=body,
        message_id=message_id,
        operation_id=operation_id,
        content_type=content_type,
        meta=meta,
        auth=auth,
        client=client,
    )
    headers = {"x-anp-source-service-did": settings.service_did}
    body_bytes = json.dumps(payload).encode()
    if service_identity is None:
        if not settings.allow_unsigned_peer_dev:
            raise Unauthorized("service_identity_not_configured")
    else:
        headers.update(service_identity.sign_headers(str(service["serviceEndpoint"]), "POST", {"Content-Type": "application/json", **headers}, body_bytes))
    try:
        response = _http_post_json(str(service["serviceEndpoint"]), payload, headers=headers, body_bytes=body_bytes)
    except Exception as exc:
        if isinstance(exc, (InvalidParams, NotFound)):
            raise
        raise AwikiRemoteDeliveryError("remote_delivery_failed", data={"recipient_did": recipient, "detail": str(exc)}) from exc
    if "error" in response:
        raise AwikiRemoteDeliveryError("remote_delivery_failed", data={"recipient_did": recipient, "remote_error": response["error"]})
    result = response.get("result")
    if not isinstance(result, dict):
        raise AwikiRemoteDeliveryError("remote_direct_result_required", data={"recipient_did": recipient})
    _validate_remote_direct_result(result, recipient=recipient, operation_id=operation_id, message_id=message_id)
    return result


class AwikiRemoteDeliveryError(InvalidParams):
    message = "remote_delivery_failed"


def _validate_remote_direct_result(result: dict[str, Any], *, recipient: str, operation_id: str, message_id: str) -> None:
    if result.get("accepted") is not True:
        raise AwikiRemoteDeliveryError("remote_direct_not_accepted", data={"recipient_did": recipient, "remote_result": result})
    if result.get("final_acceptance") is not True:
        raise AwikiRemoteDeliveryError("remote_direct_final_acceptance_required", data={"recipient_did": recipient, "remote_result": result})
    if result.get("message_id") != message_id:
        raise AwikiRemoteDeliveryError("remote_direct_message_id_mismatch", data={"recipient_did": recipient, "remote_result": result})
    if result.get("operation_id") != operation_id:
        raise AwikiRemoteDeliveryError("remote_direct_operation_id_mismatch", data={"recipient_did": recipient, "remote_result": result})
    if result.get("target_did") != recipient:
        raise AwikiRemoteDeliveryError("remote_direct_target_did_mismatch", data={"recipient_did": recipient, "remote_result": result})
    accepted_at = result.get("accepted_at")
    if not isinstance(accepted_at, str):
        raise AwikiRemoteDeliveryError("remote_direct_accepted_at_required", data={"recipient_did": recipient, "remote_result": result})
    try:
        datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AwikiRemoteDeliveryError("remote_direct_accepted_at_invalid", data={"recipient_did": recipient, "remote_result": result}) from exc
    delivery_state = result.get("delivery_state")
    if delivery_state == "ephemeral":
        raise AwikiRemoteDeliveryError("remote_direct_ephemeral_not_durable", data={"recipient_did": recipient, "remote_result": result})


def _direct_body(params: dict[str, Any], content_type: str) -> dict[str, Any]:
    body = params.get("body")
    if not isinstance(body, dict):
        if "payload" in params:
            body = {"payload": params.get("payload")}
        elif "payload_b64u" in params:
            body = {"payload_b64u": params.get("payload_b64u")}
        else:
            body = {"content_type": content_type, "text": params.get("text", "")}
    return body


def direct_send(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    public_rpc = request.url.path.rstrip("/") == settings.anp_public_rpc_path.rstrip("/")
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    envelope_body = params.get("_anp_body") if isinstance(params.get("_anp_body"), dict) else None
    auth = params.get("_anp_auth") if isinstance(params.get("_anp_auth"), dict) else None
    client = params.get("_anp_client") if isinstance(params.get("_anp_client"), dict) else None
    authenticated_sender = current_did(request, required=not public_rpc)
    sender = params.get("sender_did") or authenticated_sender
    recipient = params.get("recipient_did") or params.get("to")
    content_type = params.get("content_type") or meta.get("content_type") or "text/plain"
    body = _direct_body(params, content_type)
    proof_body = envelope_body or body
    _validate_send_envelope_meta(params, meta, target_kind="agent", target_did=recipient)
    if _should_validate_body_shape(params, content_type):
        _validate_message_body_shape(proof_body, content_type, kind="direct")
    if not sender or not recipient:
        raise InvalidParams("sender_and_recipient_required")
    if not public_rpc and authenticated_sender and sender != authenticated_sender:
        raise Unauthorized("sender_did_mismatch")
    message_id = params.get("message_id") or new_id("msg")
    operation_id = params.get("operation_id")
    response_operation_id = operation_id or new_id("op")
    with get_store(request).connect() as conn:
        sender_local = _user_exists(conn, sender)
        recipient_local = _user_exists(conn, recipient)

    if public_rpc:
        if not recipient_local:
            raise InvalidParams("recipient_not_local", data={"recipient_did": recipient})
        validate_origin_proof_structure(
            auth,
            method="direct.send",
            meta=meta,
            body=proof_body,
            sender_did_document=_resolve_did_document_for_proof(request, sender),
        )
        _verify_peer_request_signature(request, settings)
        if _is_daemon_heartbeat(meta, proof_body, content_type):
            return _accept_ephemeral_direct(
                request,
                sender=sender,
                recipient=recipient,
                body=proof_body,
                content_type=content_type,
                message_id=message_id,
                operation_id=response_operation_id,
                recipient_local=True,
            )
        return _store_direct_message(
            request,
            sender=sender,
            recipient=recipient,
            body=proof_body,
            content_type=content_type,
            message_id=message_id,
            operation_id=response_operation_id,
            idempotency_operation_id=operation_id,
            sender_local=sender_local,
            recipient_local=True,
        )

    if not sender_local:
        raise Unauthorized("sender_not_local", data={"sender_did": sender})
    if recipient_local:
        if _is_daemon_heartbeat(meta, proof_body, content_type):
            return _accept_ephemeral_direct(
                request,
                sender=sender,
                recipient=recipient,
                body=proof_body,
                content_type=content_type,
                message_id=message_id,
                operation_id=response_operation_id,
                recipient_local=True,
            )
        return _store_direct_message(
            request,
            sender=sender,
            recipient=recipient,
            body=body,
            content_type=content_type,
            message_id=message_id,
            operation_id=response_operation_id,
            idempotency_operation_id=operation_id,
            sender_local=True,
            recipient_local=True,
        )
    if _did_belongs_to_domain(recipient, settings.did_domain):
        raise NotFound("recipient_not_found", data={"recipient_did": recipient})

    validate_origin_proof_structure(
        auth,
        method="direct.send",
        meta=meta,
        body=proof_body,
        sender_did_document=_resolve_did_document_for_proof(request, sender),
    )
    existing = _direct_existing_idempotent_result(
        request,
        sender=sender,
        recipient=recipient,
        body=proof_body,
        content_type=content_type,
        message_id=message_id,
        operation_id=operation_id,
    )
    if existing:
        return existing
    remote = _send_remote_direct(
        settings,
        sender=sender,
        recipient=recipient,
        body=proof_body,
        content_type=content_type,
        message_id=message_id,
        operation_id=response_operation_id,
        meta=meta,
        auth=auth,
        client=client,
        service_identity=getattr(request.app.state, "service_identity", None),
    )
    return _store_direct_message(
        request,
        sender=sender,
        recipient=recipient,
        body=proof_body,
        content_type=content_type,
        message_id=message_id,
        operation_id=response_operation_id,
        idempotency_operation_id=operation_id,
        sender_local=True,
        recipient_local=False,
        delivery_state=str(remote.get("delivery_state") or "accepted"),
        final_acceptance=bool(remote.get("final_acceptance", False)),
    )


_DIRECT_BODY_EXTENSION_KEYS = {"conversation_id", "reply_to_message_id", "annotations"}
_GROUP_BODY_EXTENSION_KEYS = {"thread_id", "reply_to_message_id", "annotations", "expected_group_state_version"}
_ATTACHMENT_MANIFEST_CONTENT_TYPE = "application/anp-attachment-manifest+json"


def _normalize_content_type(raw: Any) -> str:
    value = str(raw or "text/plain").strip().lower()
    return value or "text/plain"


def _validate_message_body_shape(body: dict[str, Any], content_type: str, *, kind: str) -> None:
    normalized = _normalize_content_type(content_type)
    extension_keys = _GROUP_BODY_EXTENSION_KEYS if kind == "group" else _DIRECT_BODY_EXTENSION_KEYS
    allowed: set[str]
    if normalized == "text/plain":
        allowed = {"text", *extension_keys}
        if "text" not in body or not isinstance(body.get("text"), str):
            raise InvalidParams("message_body_text_required", data={"content_type": content_type})
    elif normalized in {"application/json", _ATTACHMENT_MANIFEST_CONTENT_TYPE}:
        allowed = {"payload", *extension_keys}
        if "payload" not in body or not isinstance(body.get("payload"), dict):
            raise InvalidParams("message_body_payload_object_required", data={"content_type": content_type})
    else:
        allowed = {"payload_b64u", *extension_keys}
        if "payload_b64u" not in body or not str(body.get("payload_b64u") or "").strip():
            raise InvalidParams("message_body_payload_b64u_required", data={"content_type": content_type})
    extra = sorted(set(body) - allowed)
    if extra:
        raise InvalidParams("message_body_fields_mismatch_content_type", data={"content_type": content_type, "fields": extra})


def _should_validate_body_shape(params: dict[str, Any], content_type: str) -> bool:
    if isinstance(params.get("_anp_body"), dict):
        return True
    return _normalize_content_type(content_type) != "text/plain"


def _is_anp_envelope(params: dict[str, Any]) -> bool:
    return isinstance(params.get("_anp_body"), dict) or isinstance(params.get("_anp_meta"), dict)


def _require_meta_string(meta: dict[str, Any], key: str, error_message: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidParams(error_message)
    return value


def _validate_send_envelope_meta(params: dict[str, Any], meta: dict[str, Any], *, target_kind: str, target_did: str | None) -> None:
    if not _is_anp_envelope(params):
        return
    expected_profile = "anp.group.base.v1" if target_kind == "group" else "anp.direct.base.v1"
    profile = _require_meta_string(meta, "profile", "anp_meta_profile_required")
    if profile != expected_profile:
        raise InvalidParams("anp_meta_profile_mismatch", data={"expected": expected_profile, "actual": profile})
    security_profile = _require_meta_string(meta, "security_profile", "anp_meta_security_profile_required")
    if security_profile != "transport-protected":
        raise InvalidParams(
            "anp_meta_security_profile_mismatch",
            data={"expected": "transport-protected", "actual": security_profile},
        )
    _require_meta_string(meta, "sender_did", "anp_meta_sender_did_required")
    target = meta.get("target")
    if not isinstance(target, dict):
        raise InvalidParams("anp_meta_target_required")
    kind = target.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise InvalidParams("anp_meta_target_kind_required")
    if kind != target_kind:
        raise InvalidParams("anp_meta_target_kind_mismatch", data={"expected": target_kind, "actual": kind})
    meta_target_did = target.get("did")
    if not isinstance(meta_target_did, str) or not meta_target_did.strip():
        raise InvalidParams("anp_meta_target_did_required")
    if target_did and meta_target_did != target_did:
        raise InvalidParams("anp_meta_target_did_mismatch", data={"expected": target_did, "actual": meta_target_did})
    _require_meta_string(meta, "operation_id", "anp_meta_operation_id_required")
    _require_meta_string(meta, "message_id", "anp_meta_message_id_required")
    _require_meta_string(meta, "content_type", "anp_meta_content_type_required")


def _project_message_content(body: Any, content_type: str) -> tuple[str, Any]:
    if not isinstance(body, dict):
        return "json", body
    normalized = _normalize_content_type(content_type)
    if normalized == _ATTACHMENT_MANIFEST_CONTENT_TYPE:
        return "attachment_manifest", body.get("payload", body)
    if isinstance(body.get("text"), str):
        return "text", body["text"]
    if "payload" in body:
        return "json", body["payload"]
    if isinstance(body.get("payload_b64u"), str):
        return "binary", body["payload_b64u"]
    return "json", body


def _direct_message_result(row: Any, owner_did: str | None = None) -> dict[str, Any]:
    body = _load(row["body_json"])
    sender = row["sender_did"]
    recipient = row["recipient_did"]
    direction = "outgoing" if owner_did and owner_did == sender else "incoming"
    read_at = row["read_at"] if "read_at" in row.keys() else None
    content_type = row["content_type"] if "content_type" in row.keys() else (body.get("content_type", "text/plain") if isinstance(body, dict) else "text/plain")
    message_type, content = _project_message_content(body, content_type)
    return {
        **dict(row),
        "id": row["message_id"],
        "type": message_type,
        "sender_did": sender,
        "receiver_did": recipient,
        "recipient_did": recipient,
        "content_type": content_type,
        "content": content,
        "body": body,
        "sent_at": row["created_at"],
        "received_at": row["created_at"],
        "is_read": read_at is not None,
        "read_at": read_at,
        "direction": direction,
    }


def _message_page(messages: list[dict[str, Any]], limit: int | None = None) -> dict[str, Any]:
    return {
        "messages": messages,
        "total": len(messages),
        "has_more": bool(limit and len(messages) >= limit),
        "source": "remote_http",
    }


def _parse_non_negative_int(raw: Any, *, field: str, default: int = 0) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidParams(f"{field}_invalid") from exc
    if value < 0:
        raise InvalidParams(f"{field}_invalid")
    return value


def _parse_local_view_limit(raw: Any, *, default: int) -> int:
    limit = _parse_non_negative_int(raw, field="limit", default=default)
    if limit <= 0:
        limit = default
    if limit > 100:
        raise InvalidParams("limit_too_large")
    return limit


def _validate_local_view_owner(params: dict[str, Any], owner: str, *, prefix: str) -> None:
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    sender = meta.get("sender_did")
    if sender and sender != owner:
        raise Unauthorized(f"{prefix}.sender_did_mismatch")
    user_did = params.get("user_did")
    if user_did and user_did != owner:
        raise Unauthorized(f"{prefix}.user_did_mismatch")
    if params.get("inbox_owner_did") or params.get("inbox_auth_verification_method"):
        raise NotSupported("delegated_local_view_not_supported", data={"method": prefix})


def _validate_group_local_view(params: dict[str, Any], owner: str, *, group_did: str | None = None) -> None:
    _validate_local_view_owner(params, owner, prefix="group.local")
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    target = meta.get("target")
    if not isinstance(target, dict):
        return
    if target.get("kind") and target.get("kind") != "group":
        raise InvalidParams("group.local_target_kind_mismatch", data={"actual": target.get("kind")})
    target_did = target.get("did")
    if group_did and target_did and target_did != group_did:
        raise InvalidParams("group.local_target_did_mismatch", data={"expected": group_did, "actual": target_did})


def direct_history(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    _validate_local_view_owner(params, owner, prefix="direct.history")
    if params.get("group_did"):
        raise InvalidParams("direct.history_group_path_deprecated", data={"use": "group.list_messages"})
    peer = params.get("peer_did") or params.get("with")
    if not peer:
        raise InvalidParams("peer_did_required")
    since_seq = _parse_non_negative_int(params.get("since_seq", params.get("since")), field="direct.history_since_seq", default=0)
    skip = _parse_non_negative_int(params.get("skip"), field="skip", default=0)
    limit = _parse_local_view_limit(params.get("limit"), default=100)
    with get_store(request).connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, v.read_at AS read_at FROM direct_messages m
            JOIN direct_message_views v ON v.message_id = m.message_id
            WHERE v.owner_did = ? AND v.peer_did = ? AND m.server_seq > ?
            ORDER BY m.server_seq ASC
            LIMIT ?
            OFFSET ?
            """,
            (owner, peer, since_seq, limit, skip),
        ).fetchall()
    return _message_page([_direct_message_result(row, owner) for row in rows], limit)


def inbox_get(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    _validate_local_view_owner(params, owner, prefix="inbox")
    limit = _parse_local_view_limit(params.get("limit"), default=20)
    skip = _parse_non_negative_int(params.get("skip"), field="skip", default=0)
    include_read = bool(params.get("include_read", False))
    read_filter = "" if include_read else "AND v.read_at IS NULL"
    with get_store(request).connect() as conn:
        rows = conn.execute(
            f"""
            SELECT m.*, v.read_at AS read_at FROM direct_messages m
            JOIN direct_message_views v ON v.message_id = m.message_id
            WHERE v.owner_did = ?
              {read_filter}
            ORDER BY m.server_seq DESC
            LIMIT ?
            OFFSET ?
            """,
            (owner, limit, skip),
        ).fetchall()
    return _message_page([_direct_message_result(row, owner) for row in rows], limit)


def _message_ids_from_params(params: dict[str, Any]) -> list[str]:
    raw_ids = params.get("message_ids")
    if raw_ids is None and params.get("message_id") is not None:
        raw_ids = [params.get("message_id")]
    if raw_ids is None:
        raise InvalidParams("message_ids_required")
    if not isinstance(raw_ids, list):
        raise InvalidParams("message_ids_must_be_list")
    if not raw_ids:
        raise InvalidParams("message_ids_required")
    message_ids: list[str] = []
    for raw_id in raw_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise InvalidParams("message_id_invalid")
        message_ids.append(raw_id)
    return message_ids


def inbox_mark_read(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    _validate_local_view_owner(params, owner, prefix="inbox")
    message_ids = _message_ids_from_params(params)
    read_at = now_iso()
    placeholders = ",".join("?" for _ in message_ids)
    with get_store(request).connect() as conn:
        visible_rows = conn.execute(
            f"""
            SELECT message_id
            FROM direct_message_views
            WHERE owner_did = ? AND message_id IN ({placeholders})
            """,
            (owner, *message_ids),
        ).fetchall()
        visible_ids = [str(row["message_id"]) for row in visible_rows]
        if visible_ids:
            visible_placeholders = ",".join("?" for _ in visible_ids)
            conn.execute(
                f"""
                UPDATE direct_message_views
                SET read_at = ?
                WHERE owner_did = ?
                  AND message_id IN ({visible_placeholders})
                  AND read_at IS NULL
                """,
                (read_at, owner, *visible_ids),
            )
            updated_count = int(conn.execute("SELECT changes() AS count").fetchone()["count"])
        else:
            updated_count = 0
    return {
        "updated_count": updated_count,
        "message_ids": visible_ids,
        "read_at": read_at,
    }


def not_supported(params: dict[str, Any], request: Request) -> None:
    raise NotSupported("not_supported", data={"upgrade": "commercial", "params": params})


def group_get_info(params: dict[str, Any], request: Request) -> dict[str, Any]:
    group_did = params.get("group_did")
    if not group_did:
        raise InvalidParams("group_did_required")
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM groups WHERE group_did = ?", (group_did,)).fetchone()
    if not row:
        raise NotFound("group_not_found")
    return dict(row)


def _require_group_member(conn: Any, group_did: str, member_did: str) -> None:
    group = conn.execute("SELECT 1 FROM groups WHERE group_did = ?", (group_did,)).fetchone()
    if not group:
        raise NotFound("group_not_found")
    member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_did = ? AND member_did = ?",
        (group_did, member_did),
    ).fetchone()
    if not member:
        raise Unauthorized("group.not_member")


def _request_is_public_anp(request: Request) -> bool:
    settings = get_settings(request)
    return request.url.path.rstrip("/") == settings.anp_public_rpc_path.rstrip("/")


def group_join(params: dict[str, Any], request: Request) -> dict[str, Any]:
    public_rpc = _request_is_public_anp(request)
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    envelope_body = params.get("_anp_body") if isinstance(params.get("_anp_body"), dict) else None
    auth = params.get("_anp_auth") if isinstance(params.get("_anp_auth"), dict) else None
    did = params.get("sender_did") or current_did(request, required=not public_rpc)
    if not did:
        raise InvalidParams("sender_did_required")
    group = group_get_info(params, request)
    if public_rpc:
        proof_body = envelope_body or {"group_did": group["group_did"], **({"invite_token": params.get("invite_token")} if params.get("invite_token") else {})}
        validate_origin_proof_structure(
            auth,
            method="group.join",
            meta=meta,
            body=proof_body,
            sender_did_document=_resolve_did_document_for_proof(request, str(did)),
        )
        _verify_peer_request_signature(request, get_settings(request))
    if group["join_mode"] == "invite_token" and params.get("invite_token") != group["invite_token"]:
        raise Unauthorized("invalid_invite_token")
    member_events: list[tuple[str, int, str]] = []
    with get_store(request).connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO group_members(group_did, member_did, role, joined_at) VALUES (?, ?, ?, ?)",
            (group["group_did"], did, "member", now_iso()),
        )
        members = conn.execute("SELECT member_did FROM group_members WHERE group_did = ?", (group["group_did"],)).fetchall()
        for member_row in members:
            owner_did = str(member_row["member_did"])
            event_type = "group.joined" if owner_did == did else "group.member.joined"
            event_seq = add_sync_event(
                conn,
                owner_did,
                event_type,
                {"group_did": group["group_did"], "member_did": did},
            )
            member_events.append((owner_did, event_seq, event_type))
    for owner_did, event_seq, event_type in member_events:
        _publish_realtime(
            request,
            owner_did,
            "group.state_changed",
            {"group_did": group["group_did"], "change": "member_joined", "member_did": did},
            {"owner_did": owner_did, "event_type": event_type, "event_seq": str(event_seq)},
        )
    return {"joined": True, "group_did": group["group_did"], "member_did": did}


def group_leave(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = params.get("sender_did") or current_did(request)
    group_did = params.get("group_did")
    if not group_did:
        raise InvalidParams("group_did_required")
    member_events: list[tuple[str, int, str]] = []
    with get_store(request).connect() as conn:
        _require_group_member(conn, group_did, did)
        conn.execute("DELETE FROM group_members WHERE group_did = ? AND member_did = ?", (group_did, did))
        members = conn.execute("SELECT member_did FROM group_members WHERE group_did = ?", (group_did,)).fetchall()
        owner_dids = {str(did), *(str(row["member_did"]) for row in members)}
        for owner_did in owner_dids:
            event_type = "group.left" if owner_did == did else "group.member.left"
            event_seq = add_sync_event(conn, owner_did, event_type, {"group_did": group_did, "member_did": did})
            member_events.append((owner_did, event_seq, event_type))
    for owner_did, event_seq, event_type in member_events:
        _publish_realtime(
            request,
            owner_did,
            "group.state_changed",
            {"group_did": group_did, "change": "member_left", "member_did": did},
            {"owner_did": owner_did, "event_type": event_type, "event_seq": str(event_seq)},
        )
    return {"left": True, "group_did": group_did}


def group_send(params: dict[str, Any], request: Request) -> dict[str, Any]:
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else {}
    envelope_body = params.get("_anp_body") if isinstance(params.get("_anp_body"), dict) else None
    sender = params.get("sender_did") or current_did(request)
    group_did = params.get("group_did")
    content_type = params.get("content_type") or meta.get("content_type") or "text/plain"
    body = envelope_body or params.get("body")
    if not isinstance(body, dict):
        body = {"content_type": content_type, "text": params.get("text", "")}
    _validate_send_envelope_meta(params, meta, target_kind="group", target_did=group_did)
    if _should_validate_body_shape(params, content_type):
        _validate_message_body_shape(body, content_type, kind="group")
    if not group_did:
        raise InvalidParams("group_did_required")
    member_events: list[tuple[str, int]] = []
    store = get_store(request)
    with store.connect() as conn:
        member = conn.execute("SELECT 1 FROM group_members WHERE group_did = ? AND member_did = ?", (group_did, sender)).fetchone()
        if not member:
            raise Unauthorized("not_group_member")
        message_id = params.get("message_id") or new_id("gmsg")
        operation_id = params.get("operation_id") or meta.get("operation_id")
        existing = conn.execute("SELECT * FROM group_messages WHERE message_id = ?", (message_id,)).fetchone()
        if existing:
            return _group_idempotent_result_or_raise(
                existing,
                group_did=group_did,
                sender=sender,
                body_json=_json(body),
                content_type=content_type,
                operation_id=operation_id,
            )
        seq = store.next_seq(conn, "group_messages")
        created_at = now_iso()
        conn.execute(
            "INSERT INTO group_messages(message_id, group_did, sender_did, operation_id, body_json, content_type, created_at, server_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, group_did, sender, operation_id, _json(body), content_type, created_at, seq),
        )
        members = conn.execute("SELECT member_did FROM group_members WHERE group_did = ?", (group_did,)).fetchall()
        for member_row in members:
            event_seq = add_sync_event(
                conn,
                member_row["member_did"],
                "group.message.created",
                _group_sync_event_payload(
                    message_id=message_id,
                    group_did=group_did,
                    sender_did=sender,
                    server_seq=seq,
                    content_type=content_type,
                ),
            )
            member_events.append((str(member_row["member_did"]), event_seq))
    for owner_did, event_seq in member_events:
        _publish_realtime(
            request,
            owner_did,
            "group.incoming",
            {
                "message": {
                    "message_id": message_id,
                    "group_did": group_did,
                    "sender_did": sender,
                    "content_type": content_type,
                    "body": body,
                    "server_seq": seq,
                    "created_at": created_at,
                }
            },
            {
                "owner_did": owner_did,
                "event_type": "group.message.created",
                "event_seq": str(event_seq),
            },
        )
    return {
        "accepted": True,
        "delivery_state": "accepted",
        "final_acceptance": True,
        "message_id": message_id,
        "operation_id": operation_id,
        "group_did": group_did,
        "sender_did": sender,
        "server_seq": seq,
        "group_event_seq": str(seq),
        "group_state_version": str(seq),
        "accepted_at": created_at,
        "content_type": content_type,
        "body": body,
    }


def _group_idempotent_result_or_raise(
    row: Any,
    *,
    group_did: str,
    sender: str,
    body_json: str,
    content_type: str,
    operation_id: str | None,
) -> dict[str, Any]:
    fields: list[str] = []
    if row["group_did"] != group_did:
        fields.append("group_did")
    if row["sender_did"] != sender:
        fields.append("sender_did")
    if row["content_type"] != content_type:
        fields.append("content_type")
    if row["body_json"] != body_json:
        fields.append("body")
    stored_operation_id = _stored_operation_id(row)
    if operation_id is not None and stored_operation_id != operation_id:
        fields.append("operation_id")
    if fields:
        _message_conflict(str(row["message_id"]), fields)
    body = _load(row["body_json"])
    return {
        "accepted": True,
        "delivery_state": "accepted",
        "final_acceptance": True,
        "message_id": row["message_id"],
        "operation_id": stored_operation_id or operation_id,
        "group_did": row["group_did"],
        "sender_did": row["sender_did"],
        "server_seq": row["server_seq"],
        "group_event_seq": str(row["server_seq"]),
        "group_state_version": str(row["server_seq"]),
        "accepted_at": row["created_at"],
        "content_type": row["content_type"],
        "body": body,
        "idempotent_replay": True,
    }


def group_list(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    did = current_did(request)
    _validate_group_local_view(params, did)
    limit = _parse_local_view_limit(params.get("limit"), default=50)
    with get_store(request).connect() as conn:
        rows = conn.execute(
            "SELECT g.* FROM groups g JOIN group_members m ON m.group_did = g.group_did WHERE m.member_did = ? ORDER BY g.display_name",
            (did,),
        ).fetchall()
    return [dict(row) for row in rows[:limit]]


def group_members(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    did = current_did(request)
    group_did = params.get("group_did")
    if not group_did:
        raise InvalidParams("group_did_required")
    _validate_group_local_view(params, did, group_did=group_did)
    limit = _parse_local_view_limit(params.get("limit"), default=100)
    with get_store(request).connect() as conn:
        _require_group_member(conn, group_did, did)
        rows = conn.execute("SELECT * FROM group_members WHERE group_did = ? ORDER BY joined_at LIMIT ?", (group_did, limit)).fetchall()
    return [dict(row) for row in rows]


def _group_message_result(row: Any) -> dict[str, Any]:
    body = _load(row["body_json"])
    content_type = row["content_type"] if "content_type" in row.keys() else (body.get("content_type", "text/plain") if isinstance(body, dict) else "text/plain")
    message_type, content = _project_message_content(body, content_type)
    return {
        **dict(row),
        "id": row["message_id"],
        "type": message_type,
        "content_type": content_type,
        "content": content,
        "body": body,
        "sent_at": row["created_at"],
        "received_at": row["created_at"],
        "direction": "incoming",
    }


def group_messages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    group_did = params.get("group_did")
    if not group_did:
        raise InvalidParams("group_did_required")
    _validate_group_local_view(params, did, group_did=group_did)
    since_seq = _parse_non_negative_int(
        params.get("since_event_seq", params.get("since_seq")),
        field="group.messages_since_seq",
        default=0,
    )
    skip = _parse_non_negative_int(params.get("skip"), field="skip", default=0)
    limit = _parse_local_view_limit(params.get("limit"), default=50)
    with get_store(request).connect() as conn:
        _require_group_member(conn, group_did, did)
        total = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM group_messages WHERE group_did = ? AND server_seq > ?",
                (group_did, since_seq),
            ).fetchone()["total"]
        )
        rows = conn.execute(
            """
            SELECT * FROM group_messages
            WHERE group_did = ? AND server_seq > ?
            ORDER BY server_seq ASC
            LIMIT ?
            OFFSET ?
            """,
            (group_did, since_seq, limit, skip),
        ).fetchall()
    messages = [_group_message_result(row) for row in rows]
    page = _message_page(messages, limit)
    next_since_seq = messages[-1]["server_seq"] if messages else since_seq
    page.update(
        {
            "group_did": group_did,
            "total": total,
            "has_more": total > skip + len(messages),
            "next_since_seq": str(next_since_seq),
            "next_server_seq": str(next_since_seq),
        }
    )
    return page


def _thread_from_params(params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    thread = params.get("thread") if isinstance(params.get("thread"), dict) else None
    thread_id = params.get("thread_id")
    if thread:
        kind = thread.get("kind")
        if kind == "direct" and thread.get("peer_did"):
            return thread, f"direct:{thread['peer_did']}"
        if kind == "group" and thread.get("group_did"):
            return thread, f"group:{thread['group_did']}"
        raise InvalidParams("thread_required")
    if thread_id:
        raw = str(thread_id)
        if raw.startswith("group:"):
            group_did = raw.removeprefix("group:")
            return {"kind": "group", "group_did": group_did}, raw
        peer_did = raw.removeprefix("direct:")
        return {"kind": "direct", "peer_did": peer_did}, f"direct:{peer_did}"
    raise InvalidParams("thread_required")


def _thread_message_seq(conn: Any, *, owner: str, thread: dict[str, Any], message_id: str) -> int:
    kind = thread.get("kind")
    if kind == "direct":
        peer = thread.get("peer_did")
        if not peer:
            raise InvalidParams("thread_required")
        row = conn.execute(
            """
            SELECT m.server_seq FROM direct_messages m
            JOIN direct_message_views v ON v.message_id = m.message_id
            WHERE v.owner_did = ? AND v.peer_did = ? AND m.message_id = ?
            """,
            (owner, peer, message_id),
        ).fetchone()
    elif kind == "group":
        group_did = thread.get("group_did")
        if not group_did:
            raise InvalidParams("thread_required")
        member = conn.execute(
            "SELECT 1 FROM group_members WHERE group_did = ? AND member_did = ?",
            (group_did, owner),
        ).fetchone()
        if not member:
            raise Unauthorized("read_state.group_membership_required")
        row = conn.execute(
            "SELECT server_seq FROM group_messages WHERE group_did = ? AND message_id = ?",
            (group_did, message_id),
        ).fetchone()
    else:
        raise InvalidParams("read_state.unsupported_thread_kind")
    if not row:
        raise InvalidParams("read_state.watermark_mismatch")
    return int(row["server_seq"])


def _parse_read_watermark_seq(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        seq = int(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidParams("read_state.server_seq_invalid") from exc
    if seq < 0:
        raise InvalidParams("read_state.server_seq_invalid")
    return seq


def _apply_read_watermark(
    conn: Any,
    *,
    owner: str,
    thread: dict[str, Any],
    saved_seq: int,
    previous_seq: int,
    read_at: str,
) -> tuple[int, int | None]:
    kind = thread.get("kind")
    if kind == "direct":
        peer = thread.get("peer_did")
        if not peer:
            raise InvalidParams("thread_required")
        cursor = conn.execute(
            """
            UPDATE direct_message_views
            SET read_at = ?
            WHERE owner_did = ?
              AND peer_did = ?
              AND read_at IS NULL
              AND message_id IN (
                SELECT message_id FROM direct_messages WHERE server_seq <= ?
              )
            """,
            (read_at, owner, peer, saved_seq),
        )
        unread = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM direct_message_views v
            JOIN direct_messages m ON m.message_id = v.message_id
            WHERE v.owner_did = ?
              AND v.peer_did = ?
              AND v.read_at IS NULL
            """,
            (owner, peer),
        ).fetchone()
        return int(cursor.rowcount or 0), int(unread["count"])
    if kind == "group":
        group_did = thread.get("group_did")
        if not group_did:
            raise InvalidParams("thread_required")
        _require_group_member(conn, group_did, owner)
        updated = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM group_messages
            WHERE group_did = ?
              AND server_seq > ?
              AND server_seq <= ?
            """,
            (group_did, previous_seq, saved_seq),
        ).fetchone()
        unread = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM group_messages
            WHERE group_did = ?
              AND server_seq > ?
            """,
            (group_did, saved_seq),
        ).fetchone()
        return int(updated["count"]), int(unread["count"])
    raise InvalidParams("read_state.unsupported_thread_kind")


def mark_read(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    if params.get("event_seq") or params.get("since_event_seq") or params.get("next_event_seq") or params.get("checkpoint") or params.get("read_up_to_group_event_seq"):
        raise InvalidParams("read_state.server_seq_invalid")
    thread, thread_id = _thread_from_params(params)
    read_message_id = params.get("read_up_to_message_id")
    seq = _parse_read_watermark_seq(params.get("read_up_to_server_seq", params.get("read_up_to_seq")))
    if seq is None and not read_message_id:
        raise InvalidParams("read_state.watermark_required")
    read_at = now_iso()
    with get_store(request).connect() as conn:
        if read_message_id:
            message_seq = _thread_message_seq(conn, owner=owner, thread=thread, message_id=str(read_message_id))
            if seq is not None and seq != message_seq:
                raise InvalidParams("read_state.watermark_mismatch")
            seq = message_seq
        assert seq is not None
        previous = conn.execute(
            "SELECT read_up_to_seq FROM thread_read_states WHERE owner_did = ? AND thread_id = ?",
            (owner, thread_id),
        ).fetchone()
        previous_seq = int(previous["read_up_to_seq"]) if previous else 0
        saved_seq = max(previous_seq, seq)
        conn.execute(
            "INSERT OR REPLACE INTO thread_read_states(owner_did, thread_id, read_up_to_seq, updated_at) VALUES (?, ?, ?, ?)",
            (owner, thread_id, saved_seq, read_at),
        )
        updated_count, unread_count = _apply_read_watermark(
            conn,
            owner=owner,
            thread=thread,
            saved_seq=saved_seq,
            previous_seq=previous_seq,
            read_at=read_at,
        )
    advanced = saved_seq > previous_seq
    warnings = [] if advanced or seq == previous_seq else ["read_state.watermark_not_advanced"]
    return {
        "user_did": owner,
        "owner_did": owner,
        "thread": thread,
        "thread_id": thread_id,
        "updated_count": updated_count,
        "remote_acknowledged": True,
        "partial": False,
        "fallback_used": False,
        "pending_remote_ack": False,
        "read_watermark_server_seq": str(saved_seq),
        "previous_read_watermark_server_seq": str(previous_seq) if previous else None,
        "read_watermark_message_id": read_message_id,
        "advanced": advanced,
        "read_at": read_at,
        "unread_count": unread_count,
        "warnings": warnings,
        "read_up_to_seq": saved_seq,
    }

def sync_delta(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    user_did = params.get("user_did")
    if user_did and user_did != owner:
        raise Unauthorized("user_did_mismatch")
    after = _parse_non_negative_int(params.get("since_event_seq", params.get("after_event_seq", params.get("after", 0))), field="sync.since_event_seq", default=0)
    limit = _parse_non_negative_int(params.get("limit"), field="limit", default=100)
    if limit <= 0:
        limit = 100
    if limit > 500:
        raise InvalidParams("sync.limit_too_large")
    with get_store(request).connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM sync_events
            WHERE owner_did = ? AND event_seq > ?
            ORDER BY event_seq ASC
            LIMIT ?
            """,
            (owner, after, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    events = []
    for row in rows:
        payload = _load(row["payload_json"])
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        thread = payload.get("thread") if isinstance(payload.get("thread"), dict) else {}
        aggregate_id = (
            payload.get("message_id")
            or message.get("message_id")
            or payload.get("group_did")
            or thread.get("group_did")
            or payload.get("thread_id")
            or row["event_id"]
        )
        event_type = str(row["event_type"])
        if event_type.startswith("direct.message."):
            aggregate_kind = "direct_message"
        elif event_type.startswith("group.message."):
            aggregate_kind = "group_message"
        elif event_type.startswith("group."):
            aggregate_kind = "group"
        elif event_type.startswith("read_state."):
            aggregate_kind = "read_state"
        else:
            aggregate_kind = "event"
        events.append(
            {
                **dict(row),
                "event_seq": str(row["event_seq"]),
                "owner_subject_id": row["owner_did"],
                "aggregate_kind": aggregate_kind,
                "aggregate_id": aggregate_id,
                "payload": payload,
            }
        )
    next_seq = events[-1]["event_seq"] if events else after
    return {
        "owner_did": owner,
        "owner_subject_id": owner,
        "events": events,
        "next_event_seq": str(next_seq),
        "has_more": has_more,
        "snapshot_required": False,
        "retention_floor_event_seq": "0",
        "warnings": [],
    }


def thread_after(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    user_did = params.get("user_did")
    if user_did and user_did != owner:
        raise Unauthorized("user_did_mismatch")
    thread, thread_id = _thread_from_params(params)
    after = _parse_non_negative_int(params.get("after_server_seq"), field="after_server_seq", default=0)
    limit = _parse_local_view_limit(params.get("limit"), default=100)
    with get_store(request).connect() as conn:
        if thread_id.startswith("group:"):
            group_did = thread_id.removeprefix("group:")
            _require_group_member(conn, group_did, owner)
            rows = conn.execute(
                "SELECT * FROM group_messages WHERE group_did = ? AND server_seq > ? ORDER BY server_seq ASC LIMIT ?",
                (group_did, after, limit + 1),
            ).fetchall()
        else:
            peer = thread_id.removeprefix("direct:")
            rows = conn.execute(
                """
                SELECT m.*, v.read_at AS read_at FROM direct_messages m
                JOIN direct_message_views v ON v.message_id = m.message_id
                WHERE v.owner_did = ? AND v.peer_did = ? AND m.server_seq > ?
                ORDER BY m.server_seq ASC
                LIMIT ?
                """,
                (owner, peer, after, limit + 1),
            ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if thread_id.startswith("group:"):
        messages = [_group_message_result(row) for row in rows]
    else:
        messages = [_direct_message_result(row, owner) for row in rows]
    next_seq = messages[-1]["server_seq"] if messages else after
    return {
        "thread_id": thread_id,
        "thread": thread,
        "messages": messages,
        "next_server_seq": next_seq,
        "next_after_server_seq": str(next_seq),
        "has_more": has_more,
        "warnings": [],
    }


MESSAGE_HANDLERS = {
    "anp.get_capabilities": capabilities,
    "direct.send": direct_send,
    "direct.get_history": direct_history,
    "inbox.get": inbox_get,
    "inbox.mark_read": inbox_mark_read,
    "read_state.mark_read": mark_read,
    "sync.delta": sync_delta,
    "sync.thread_after": thread_after,
    "group.get_info": group_get_info,
    "group.join": group_join,
    "group.leave": group_leave,
    "group.send": group_send,
    "group.get": group_get_info,
    "group.list": group_list,
    "group.list_members": group_members,
    "group.list_messages": group_messages,
    **ATTACHMENT_HANDLERS,
    "direct.e2ee.publish_prekey_bundle": not_supported,
    "direct.e2ee.get_prekey_bundle": not_supported,
    "group.e2ee.publish_key_package": not_supported,
    "group.create": not_supported,
    "group.add": not_supported,
    "group.remove": not_supported,
    "group.update_profile": not_supported,
    "group.update_policy": not_supported,
}
