from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import shutil
from typing import Any
import urllib.parse

from fastapi import Request

from awiki_open_server.app.settings import Settings
from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import InvalidParams, NotFound, NotSupported, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.user_compat.core import current_did, get_settings, get_store

_load = runtime._load
_object_upload_uri = runtime._object_upload_uri
_object_download_uri = runtime._object_download_uri
_require_meta_string = runtime._require_meta_string
_verify_peer_request_signature = runtime._verify_peer_request_signature


def _parse_iso_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expired(value: Any) -> bool:
    parsed = _parse_iso_time(value)
    return parsed is not None and parsed <= datetime.now(timezone.utc)


def _normalize_mime_type(value: Any) -> str:
    return str(value or "application/octet-stream").split(";", 1)[0].strip().lower() or "application/octet-stream"


def _parse_expected_size(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidParams("attachment_expected_size_invalid") from exc
    if parsed < 0:
        raise InvalidParams("attachment_expected_size_invalid")
    return parsed


def _parse_expected_sha256(value: Any) -> str | None:
    if value is None or value == "":
        return None
    raw: Any
    if isinstance(value, dict):
        alg = str(value.get("alg") or "sha-256").strip().lower()
        if alg not in {"sha-256", "sha256"}:
            raise InvalidParams("attachment_digest_alg_not_supported", data={"alg": alg})
        raw = value.get("value_hex") or value.get("sha256") or value.get("value")
    else:
        raw = value
    digest = str(raw or "").strip().lower()
    for prefix in ("sha-256:", "sha-256=", "sha256:", "sha256="):
        if digest.startswith(prefix):
            digest = digest.split(prefix, 1)[1].strip()
            break
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise InvalidParams("attachment_expected_digest_invalid")
    return digest


def _expected_sha256_from_params(params: dict[str, Any]) -> str | None:
    raw = params.get("expected_digest")
    if raw is None:
        raw = params.get("digest")
    if raw is None:
        raw = params.get("expected_sha256")
    return _parse_expected_sha256(raw)


def _ensure_mime_allowed(settings: Settings, content_type: str) -> None:
    if content_type not in settings.attachment_allowed_mime_types:
        raise InvalidParams("attachment_content_type_not_allowed", data={"content_type": content_type})


def _slot_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()


def attachment_create_slot(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    encryption_info = params.get("encryption_info") if isinstance(params.get("encryption_info"), dict) else {}
    object_encryption_mode = params.get("object_encryption_mode") or encryption_info.get("mode", "none")
    intended_security = params.get("intended_message_security_profile", "transport-protected")
    if object_encryption_mode != "none" or intended_security in {"direct-e2ee", "group-e2ee"}:
        raise NotSupported("anp.attachment.encryption_policy_violation")
    settings = get_settings(request)
    attachment_id = str(params.get("attachment_id") or new_id("att"))
    slot_id = new_id("slot")
    object_id = new_id("obj")
    upload_token = new_id("up")
    commit_token = new_id("commit")
    path = settings.object_dir / f"{object_id}.upload"
    upload_uri = _object_upload_uri(settings, slot_id)
    object_uri = _object_download_uri(settings, object_id)
    expected_size = _parse_expected_size(params.get("expected_size", params.get("size")))
    expected_sha256 = _expected_sha256_from_params(params)
    raw_content_type = params.get("expected_content_type") or params.get("content_type") or params.get("mime_type")
    expected_content_type = _normalize_mime_type(raw_content_type) if raw_content_type else None
    if expected_size is not None and expected_size > settings.max_attachment_bytes:
        raise InvalidParams("attachment_too_large", data={"max": settings.max_attachment_bytes, "actual": expected_size})
    if expected_content_type:
        _ensure_mime_allowed(settings, expected_content_type)
    expires_at = _slot_expiry()
    with get_store(request).connect() as conn:
        conn.execute(
            """
            INSERT INTO attachment_slots(
              slot_id, object_id, attachment_id, object_uri, owner_did, upload_token, commit_token, path, status,
              expected_size, expected_sha256, expected_content_type, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot_id,
                object_id,
                attachment_id,
                object_uri,
                owner,
                upload_token,
                commit_token,
                str(path),
                "open",
                expected_size,
                expected_sha256,
                expected_content_type,
                expires_at,
                now_iso(),
            ),
        )
    result = {
        "attachment_id": attachment_id,
        "slot_id": slot_id,
        "object_id": object_id,
        "upload_token": upload_token,
        "upload_headers": {"X-ANP-Upload-Token": upload_token},
        "commit_token": commit_token,
        "upload_url": upload_uri,
        "upload_uri": upload_uri,
        "object_uri": object_uri,
        "expires_at": expires_at,
    }
    if expected_size is not None:
        result["expected_size"] = expected_size
    if expected_sha256 is not None:
        result["expected_digest"] = {"alg": "sha-256", "value_hex": expected_sha256}
    if expected_content_type is not None:
        result["content_type"] = expected_content_type
    return result


async def upload_slot(slot_id: str, token: str, data: bytes, request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM attachment_slots WHERE slot_id = ? AND upload_token = ?", (slot_id, token)).fetchone()
        if not row:
            raise NotFound("slot_not_found")
        if row["status"] not in {"open", "uploaded"}:
            raise InvalidParams("slot_not_uploadable", data={"status": row["status"]})
        if _is_expired(row["expires_at"]):
            raise InvalidParams("slot_expired")
        if len(data) > settings.max_attachment_bytes:
            raise InvalidParams("attachment_too_large", data={"max": settings.max_attachment_bytes, "actual": len(data)})
        path = Path(row["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        conn.execute("UPDATE attachment_slots SET status = ? WHERE slot_id = ?", ("uploaded", slot_id))
    return {"uploaded": True, "slot_id": slot_id}


def attachment_commit(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    slot_id = params.get("slot_id")
    commit_token = params.get("commit_token")
    if not slot_id or not commit_token:
        raise InvalidParams("slot_id_and_commit_token_required")
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM attachment_slots WHERE slot_id = ? AND commit_token = ? AND owner_did = ?",
            (slot_id, commit_token, owner),
        ).fetchone()
        if not row:
            raise NotFound("slot_not_found")
        if row["status"] != "uploaded":
            raise InvalidParams("object_not_uploaded")
        if _is_expired(row["expires_at"]):
            raise InvalidParams("slot_expired")
        path = Path(row["path"])
        if not path.exists():
            raise InvalidParams("object_not_uploaded")
        data = path.read_bytes()
        settings = get_settings(request)
        if len(data) > settings.max_attachment_bytes:
            raise InvalidParams("attachment_too_large", data={"max": settings.max_attachment_bytes, "actual": len(data)})
        if row["expected_size"] is not None and int(row["expected_size"]) != len(data):
            raise InvalidParams("attachment_size_mismatch", data={"expected": int(row["expected_size"]), "actual": len(data)})
        digest = hashlib.sha256(data).hexdigest()
        if row["expected_sha256"] and str(row["expected_sha256"]).lower() != digest:
            raise InvalidParams("attachment_digest_mismatch", data={"expected": row["expected_sha256"], "actual": digest})
        content_type = _normalize_mime_type(params.get("content_type") or row["expected_content_type"] or "application/octet-stream")
        _ensure_mime_allowed(settings, content_type)
        if row["expected_content_type"] and content_type != row["expected_content_type"]:
            raise InvalidParams("attachment_content_type_mismatch", data={"expected": row["expected_content_type"], "actual": content_type})
        final = path.with_suffix(".bin")
        shutil.move(str(path), str(final))
        object_uri = row["object_uri"] or _object_download_uri(get_settings(request), str(row["object_id"]))
        attachment_id = row["attachment_id"] or params.get("attachment_id")
        conn.execute(
            """
            INSERT INTO attachment_objects(
              object_id, source_attachment_id, object_uri, owner_did, path, size, sha256, content_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["object_id"], attachment_id, object_uri, row["owner_did"], str(final), len(data), digest, content_type, now_iso()),
        )
        conn.execute("UPDATE attachment_slots SET status = ? WHERE slot_id = ?", ("committed", slot_id))
    committed_at = now_iso()
    return {
        "committed": True,
        "attachment_id": attachment_id,
        "slot_id": slot_id,
        "object_id": row["object_id"],
        "object_uri": object_uri,
        "committed_at": committed_at,
        "size": len(data),
        "sha256": digest,
        "digest": {"alg": "sha-256", "value_hex": digest},
        "content_type": content_type,
    }


def attachment_abort(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    slot_id = params.get("slot_id")
    if not slot_id:
        raise InvalidParams("slot_id_required")
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM attachment_slots WHERE slot_id = ? AND owner_did = ?", (slot_id, owner)).fetchone()
        if not row:
            raise NotFound("slot_not_found")
        path = Path(row["path"])
        if path.exists():
            path.unlink()
        conn.execute("UPDATE attachment_slots SET status = ? WHERE slot_id = ?", ("aborted", slot_id))
    return {"aborted": True, "attachment_id": params.get("attachment_id"), "slot_id": slot_id, "aborted_at": now_iso()}


def cleanup_expired_attachments(store: Any, *, now: str | None = None) -> dict[str, int]:
    now_value = now or now_iso()
    removed_slots = 0
    removed_tickets = 0
    with store.connect() as conn:
        slots = conn.execute(
            """
            SELECT slot_id, path FROM attachment_slots
            WHERE expires_at IS NOT NULL AND expires_at <= ? AND status != 'committed'
            """,
            (now_value,),
        ).fetchall()
        for row in slots:
            path = Path(row["path"])
            if path.exists():
                path.unlink()
            conn.execute("DELETE FROM attachment_slots WHERE slot_id = ?", (row["slot_id"],))
            removed_slots += 1
        cursor = conn.execute("DELETE FROM download_tickets WHERE expires_at <= ?", (now_value,))
        removed_tickets = cursor.rowcount if cursor.rowcount is not None else 0
    return {"expired_slots": removed_slots, "expired_download_tickets": removed_tickets}


def _object_id_from_uri(object_uri: Any) -> str | None:
    if not isinstance(object_uri, str) or not object_uri.strip():
        return None
    parsed = urllib.parse.urlparse(object_uri.strip())
    path = parsed.path or object_uri.strip()
    object_id = path.rstrip("/").split("/")[-1]
    return object_id or None


def _is_anp_attachment_ticket_request(params: dict[str, Any]) -> bool:
    if isinstance(params.get("_anp_body"), dict):
        return True
    anp_shape_keys = {"requester_did", "sender_did", "message_id", "message_security_profile", "message_target_did", "group_did"}
    return any(key in params for key in anp_shape_keys)


def _normalize_ticket_security_profile(raw: Any) -> str:
    value = str(raw or "").strip()
    if value not in {"transport-protected", "direct-e2ee", "group-e2ee"}:
        raise InvalidParams("message_security_profile_required")
    return value


def _require_ticket_string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidParams(f"{key}_required")
    return value.strip()


def _ticket_object_uri(settings: Settings, object_id: str, stored_uri: Any) -> str:
    if isinstance(stored_uri, str) and stored_uri.strip():
        return stored_uri
    return _object_download_uri(settings, object_id)


def _ticket_direct_binding(params: dict[str, Any]) -> dict[str, Any]:
    attachment_id = _require_ticket_string(params, "attachment_id")
    object_uri = _require_ticket_string(params, "object_uri")
    sender_did = _require_ticket_string(params, "sender_did")
    requester_did = _require_ticket_string(params, "requester_did")
    message_id = _require_ticket_string(params, "message_id")
    message_security_profile = _normalize_ticket_security_profile(params.get("message_security_profile"))
    message_target_did = params.get("message_target_did")
    group_did = params.get("group_did")
    if isinstance(message_target_did, str) and message_target_did.strip() and isinstance(group_did, str) and group_did.strip():
        raise InvalidParams("exactly_one_message_target_or_group_required")
    if not isinstance(message_target_did, str) or not message_target_did.strip():
        raise InvalidParams("message_target_did_required")
    if message_target_did != requester_did:
        raise Unauthorized("attachment_requester_target_mismatch")
    return {
        "attachment_id": attachment_id,
        "object_uri": object_uri,
        "sender_did": sender_did,
        "requester_did": requester_did,
        "message_id": message_id,
        "message_security_profile": message_security_profile,
        "message_target_did": message_target_did,
    }


def _ticket_group_binding(params: dict[str, Any]) -> dict[str, Any]:
    attachment_id = _require_ticket_string(params, "attachment_id")
    object_uri = _require_ticket_string(params, "object_uri")
    sender_did = _require_ticket_string(params, "sender_did")
    requester_did = _require_ticket_string(params, "requester_did")
    message_id = _require_ticket_string(params, "message_id")
    message_security_profile = _normalize_ticket_security_profile(params.get("message_security_profile"))
    group_did = params.get("group_did")
    message_target_did = params.get("message_target_did")
    if isinstance(message_target_did, str) and message_target_did.strip() and isinstance(group_did, str) and group_did.strip():
        raise InvalidParams("exactly_one_message_target_or_group_required")
    if not isinstance(group_did, str) or not group_did.strip():
        raise InvalidParams("group_did_required")
    return {
        "attachment_id": attachment_id,
        "object_uri": object_uri,
        "sender_did": sender_did,
        "requester_did": requester_did,
        "message_id": message_id,
        "message_security_profile": message_security_profile,
        "group_did": group_did,
    }


def _attachment_manifest_has_object(body_json: str, *, attachment_id: str, object_uri: str) -> bool:
    try:
        body = _load(body_json)
    except Exception:
        return False
    if not isinstance(body, dict):
        return False
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return False
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return False
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        access_info = attachment.get("access_info")
        if not isinstance(access_info, dict):
            continue
        if attachment.get("attachment_id") == attachment_id and access_info.get("object_uri") == object_uri:
            return True
    return False


def _ensure_direct_attachment_context(conn, binding: dict[str, Any], *, owner_did: str) -> None:
    if binding["requester_did"] == binding["sender_did"] == owner_did:
        return
    row = conn.execute(
        """
        SELECT body_json FROM direct_messages
        WHERE message_id = ? AND sender_did = ? AND recipient_did = ?
        """,
        (binding["message_id"], binding["sender_did"], binding["message_target_did"]),
    ).fetchone()
    if not row or not _attachment_manifest_has_object(row["body_json"], attachment_id=binding["attachment_id"], object_uri=binding["object_uri"]):
        raise Unauthorized("anp.attachment.grant_not_found")


def _ensure_group_attachment_context(conn, binding: dict[str, Any]) -> None:
    member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_did = ? AND member_did = ?",
        (binding["group_did"], binding["requester_did"]),
    ).fetchone()
    if not member:
        raise Unauthorized("anp.attachment.unauthorized_requester")
    row = conn.execute(
        """
        SELECT body_json FROM group_messages
        WHERE message_id = ? AND group_did = ? AND sender_did = ?
        """,
        (binding["message_id"], binding["group_did"], binding["sender_did"]),
    ).fetchone()
    if not row or not _attachment_manifest_has_object(row["body_json"], attachment_id=binding["attachment_id"], object_uri=binding["object_uri"]):
        raise Unauthorized("anp.attachment.grant_not_found")


def _validate_attachment_ticket_meta(params: dict[str, Any], settings: Settings) -> None:
    meta = params.get("_anp_meta") if isinstance(params.get("_anp_meta"), dict) else None
    if meta is None:
        return
    profile = _require_meta_string(meta, "profile", "anp_attachment_profile_required")
    if profile != "anp.attachment.v1":
        raise InvalidParams("anp_attachment_profile_mismatch", data={"expected": "anp.attachment.v1", "actual": profile})
    security_profile = _require_meta_string(meta, "security_profile", "anp_attachment_security_profile_required")
    if security_profile != "transport-protected":
        raise InvalidParams("anp_attachment_security_profile_mismatch", data={"expected": "transport-protected", "actual": security_profile})
    _require_meta_string(meta, "sender_did", "anp_meta_sender_did_required")
    _require_meta_string(meta, "operation_id", "anp_meta_operation_id_required")
    target = meta.get("target")
    if not isinstance(target, dict):
        raise InvalidParams("anp_meta_target_required")
    if target.get("kind") != "service":
        raise InvalidParams("anp_meta_target_kind_mismatch", data={"expected": "service", "actual": target.get("kind")})
    if target.get("did") != settings.service_did:
        raise InvalidParams("anp_meta_target_did_mismatch", data={"expected": settings.service_did, "actual": target.get("did")})


def attachment_ticket(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    public_rpc = request.url.path.rstrip("/") == settings.anp_public_rpc_path.rstrip("/")
    object_id = params.get("object_id")
    object_uri = params.get("object_uri")
    if not object_id and isinstance(object_uri, str):
        object_id = _object_id_from_uri(object_uri)
    if not object_id:
        raise InvalidParams("object_id_required")
    anp_ticket = _is_anp_attachment_ticket_request(params)
    if anp_ticket:
        _validate_attachment_ticket_meta(params, settings)
        if public_rpc:
            _verify_peer_request_signature(request, settings)
    authenticated = current_did(request, required=not public_rpc)
    requester = params.get("requester_did") or authenticated
    if not requester:
        raise Unauthorized("missing_requester_did")
    if authenticated and requester != authenticated:
        raise Unauthorized("requester_did_mismatch")
    binding: dict[str, Any] | None = None
    if anp_ticket:
        if params.get("group_did"):
            binding = _ticket_group_binding(params)
        else:
            binding = _ticket_direct_binding(params)
        requester = binding["requester_did"]
    ticket = new_id("ticket")
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT object_id, source_attachment_id, object_uri, owner_did FROM attachment_objects WHERE object_id = ?", (object_id,)).fetchone()
        if not row:
            raise NotFound("object_not_found")
        stored_object_uri = _ticket_object_uri(settings, str(row["object_id"]), row["object_uri"])
        if binding:
            if binding["object_uri"] != stored_object_uri:
                raise InvalidParams("anp.attachment.ticket_binding_mismatch", data={"field": "object_uri"})
            stored_attachment_id = row["source_attachment_id"]
            if stored_attachment_id and binding["attachment_id"] != stored_attachment_id:
                raise InvalidParams("anp.attachment.ticket_binding_mismatch", data={"field": "attachment_id"})
            if "group_did" in binding:
                _ensure_group_attachment_context(conn, binding)
            elif requester not in {row["owner_did"], binding["sender_did"], binding["message_target_did"]}:
                raise Unauthorized("anp.attachment.unauthorized_requester")
            else:
                _ensure_direct_attachment_context(conn, binding, owner_did=row["owner_did"])
        elif row["owner_did"] != requester:
            raise Unauthorized("object_ticket_not_allowed")
        conn.execute("INSERT INTO download_tickets(ticket, object_id, expires_at) VALUES (?, ?, ?)", (ticket, object_id, expires_at))
    download_uri = _object_download_uri(settings, str(object_id), ticket=ticket)
    ticket_binding = binding or {
        "attachment_id": params.get("attachment_id") or row["source_attachment_id"],
        "object_uri": _ticket_object_uri(settings, str(row["object_id"]), row["object_uri"]),
        "requester_did": requester,
    }
    return {
        "ticket": ticket,
        "download_ticket_b64u": ticket,
        "object_id": object_id,
        "attachment_id": params.get("attachment_id") or row["source_attachment_id"],
        "download_url": download_uri,
        "download_uri": download_uri,
        "download_headers": {"Authorization": f"Bearer {ticket}"},
        "ticket_binding": ticket_binding,
        "expires_at": expires_at,
    }


ATTACHMENT_HANDLERS = {
    "attachment.create_slot": attachment_create_slot,
    "attachment.commit_object": attachment_commit,
    "attachment.abort_object": attachment_abort,
    "attachment.get_download_ticket": attachment_ticket,
}
