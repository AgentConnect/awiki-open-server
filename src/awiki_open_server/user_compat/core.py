from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
import re
import secrets
from typing import Any
from urllib.parse import unquote

from fastapi import Request
import jcs

from awiki_open_server.app.settings import Settings
from awiki_open_server.protocol.anp_adapter import (
    AnpProtocolError,
    SingleDeviceManifest,
    require_did_document_binding,
    signature_keyid,
    validate_single_device_document,
    valid_handle_local_part,
    verify_service_http_signature,
    web_handle_hint,
    web_handle_resolution_url,
    verify_web_handle_documents,
)
from awiki_open_server.protocol.registry import STANDARD_PROFILES
from awiki_open_server.service_identity import verify_did_document_data_integrity_proof
from awiki_open_server.shared.errors import (
    Conflict,
    InvalidParams,
    NotFound,
    NotSupported,
    Unauthorized,
    UserServiceNotFound,
)
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.shared import runtime
from awiki_open_server.storage.db import Store
from awiki_open_server.user_compat.device_auth import (
    bind_device_account, consume_auth_nonce, device_account, issue_device_token, validate_device_token,
)
from awiki_open_server.user_compat.registration import registration_check


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load(raw: str) -> Any:
    return json.loads(raw)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _user_service_not_found(resource: str, value: str | None = None) -> UserServiceNotFound:
    labels = {"did": "DID", "handle": "Handle", "user": "User", "profile": "Profile"}
    data: dict[str, Any] = {"code": f"{resource}_not_found", "resource": resource}
    if value:
        data[resource] = value
    return UserServiceNotFound(f"{labels.get(resource, resource.title())} not found", data=data)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600


def _future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _validate_single_device_manifest(document: dict[str, Any]) -> SingleDeviceManifest | None:
    try:
        return validate_single_device_document(document)
    except AnpProtocolError as exc:
        if exc.code == "multiple_devices_not_supported":
            raise NotSupported(
                exc.code, data={"max_devices_per_did": 1, "sync_mode": "single_device_pull_only"},
            ) from exc
        raise InvalidParams("device_manifest_invalid") from exc


def _is_past(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return _parse_time(value) <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


def _did_parts(did: str) -> list[str]:
    return did.split(":")


def _did_domain(did: str) -> str | None:
    parts = _did_parts(did)
    if len(parts) < 3 or parts[0] != "did" or parts[1] != "wba":
        return None
    return parts[2].lower()


def _is_e1_did(did: str) -> bool:
    return len(_did_parts(did)) > 3 and _did_parts(did)[-1].startswith("e1_")


def _default_user_did(settings: Settings, local_handle: str) -> str:
    return f"did:wba:{settings.did_domain}:users:{local_handle}:e1_default"


def _validate_local_user_did(did: str, settings: Settings) -> str:
    value = str(did or "").strip()
    if not value.startswith("did:wba:"):
        raise InvalidParams("valid_did_required")
    domain = _did_domain(value)
    if domain != settings.did_domain.lower():
        raise InvalidParams("did_domain_mismatch", data={"expected": settings.did_domain, "actual": domain})
    if not _is_e1_did(value):
        raise InvalidParams("did_e1_required")
    if value == settings.service_did or unquote(_did_parts(value)[3]).lower() in {"group", "groups", "service", "services"}:
        raise InvalidParams("did_namespace_reserved")
    return value


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def bearer_token(request: Request) -> str | None:
    values = request.headers.getlist("authorization")
    if len(values) > 1:
        raise Unauthorized("invalid_bearer_token")
    auth = values[0] if values else None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if not token:
            raise Unauthorized("invalid_bearer_token")
        return token
    return None


def _active_did_row(request: Request, did: str) -> Any | None:
    with get_store(request).connect() as conn:
        return conn.execute(
            """
            SELECT u.did, u.handle, u.token, u.created_at, u.revoked_at AS user_revoked_at,
                   d.status AS document_status, d.revoked_at AS document_revoked_at
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.did = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (did,),
        ).fetchone()


def _is_active_did(request: Request, did: str) -> bool:
    return _active_did_row(request, did) is not None


def did_for_token(request: Request, token: str) -> str | None:
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT u.did, u.access_expires_at, d.document_json
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.token = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (token,),
        ).fetchone()
        if row:
            if _is_past(row["access_expires_at"]):
                return None
            try:
                manifest = _validate_single_device_manifest(_load(row["document_json"]))
                if manifest is not None:
                    account = bind_device_account(conn, device_account(str(row["did"]), manifest))
                    validate_device_token(token, account, request.app.state.auth_token_signing_key)
                    request.state.device_account = account
                elif conn.execute("SELECT 1 FROM single_device_accounts WHERE owner_did = ?", (row["did"],)).fetchone():
                    return None
            except (InvalidParams, NotSupported, Unauthorized, ValueError):
                return None
            return str(row["did"])
    if get_settings(request).allow_unsigned_peer_dev and token.startswith("did:"):
        with get_store(request).connect() as conn:
            legacy = conn.execute(
                """SELECT d.document_json FROM users u JOIN did_documents d ON d.did = u.did
                   WHERE u.did = ? AND u.revoked_at IS NULL AND d.status = 'active'
                     AND d.revoked_at IS NULL
                     AND NOT EXISTS (SELECT 1 FROM single_device_accounts a WHERE a.owner_did = u.did)""",
                (token,),
            ).fetchone()
        if legacy is not None and "deviceManifest" not in _load(legacy["document_json"]):
            return token
    return None


def current_did(request: Request, *, required: bool = True) -> str | None:
    token = bearer_token(request)
    if token:
        did = did_for_token(request, token)
        if did:
            return did
        if required:
            raise Unauthorized("invalid_bearer_token")
        return None
    did_auth_signature_path = request.url.path in {
        "/user-service/v1/did-auth/rpc",
        "/user-service/did-auth/rpc",
        "/did-auth/rpc",
    }
    if (
        did_auth_signature_path
        and request.headers.get("signature-input")
        and request.headers.get("signature")
    ):
        try:
            key_id = signature_keyid(dict(request.headers))
            did = key_id.split("#", 1)[0]
            with get_store(request).connect() as conn:
                row = conn.execute(
                    """
                    SELECT d.document_json FROM did_documents d
                    JOIN users u ON u.did = d.did
                    WHERE d.did = ? AND d.status = 'active' AND d.revoked_at IS NULL
                      AND u.revoked_at IS NULL
                    """,
                    (did,),
                ).fetchone()
            if row is None:
                raise Unauthorized("invalid_http_signature")
            document = _load(row["document_json"])
            manifest = _validate_single_device_manifest(document)
            if manifest is not None and key_id != manifest.signing_key_id:
                raise Unauthorized("device_signature_required")
            raw_body = getattr(request.state, "raw_body", getattr(request, "_body", b""))
            public_url = f"{get_settings(request).public_base_url.rstrip('/')}{request.url.path}"
            if request.url.query:
                public_url = f"{public_url}?{request.url.query}"
            verification = verify_service_http_signature(
                did_document=document,
                request_method=request.method,
                request_url=public_url,
                headers=dict(request.headers),
                body=raw_body,
            )
            with get_store(request).connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                consume_auth_nonce(conn, key_id, verification.metadata)
            if manifest is not None:
                request.state.signed_device_account = device_account(did, manifest)
                request.state.device_account = request.state.signed_device_account
            return did
        except (AnpProtocolError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise Unauthorized("invalid_http_signature") from exc
    if required:
        raise Unauthorized("invalid_bearer_token" if token else "missing_authentication")
    return None


def did_document(settings: Settings, did: str, handle: str | None = None) -> dict[str, Any]:
    return {
        "id": did,
        "alsoKnownAs": [handle] if handle else [],
        "service": [
            {
                "id": f"{did}#anp-message",
                "type": "ANPMessageService",
                "serviceEndpoint": settings.anp_service_endpoint,
                "serviceDid": settings.service_did,
                "profiles": list(STANDARD_PROFILES),
                "securityProfiles": ["transport-protected"],
                "authSchemes": ["bearer", "didwba"],
            }
        ],
    }


def _ensure_anp_message_service(document: dict[str, Any], settings: Settings, did: str) -> dict[str, Any]:
    doc = dict(document)
    if isinstance(doc.get("proof"), dict):
        if doc.get("id") != did:
            raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": doc.get("id")})
        proof = doc["proof"]
        verification_method = proof.get("verificationMethod")
        if not isinstance(verification_method, str) or not verification_method.startswith(f"{did}#"):
            raise InvalidParams("did_document_proof_verification_method_mismatch")
        try:
            verify_did_document_data_integrity_proof(doc, expected_did=did)
            if not settings.allow_unsigned_peer_dev:
                require_did_document_binding(doc)
        except AnpProtocolError as exc:
            raise InvalidParams(exc.code) from exc
        services = _anp_message_services(doc)
        if not services:
            raise InvalidParams("signed_did_document_requires_anp_message_service")
        if len(services) != 1:
            raise InvalidParams("signed_did_document_requires_single_anp_message_service")
        service = services[0]
        if service.get("serviceEndpoint") != settings.anp_service_endpoint:
            raise InvalidParams(
                "signed_did_document_service_endpoint_mismatch",
                data={"actual": service.get("serviceEndpoint"), "expected": settings.anp_service_endpoint},
            )
        if service.get("serviceDid") != settings.service_did:
            raise InvalidParams(
                "signed_did_document_service_did_mismatch",
                data={"actual": service.get("serviceDid"), "expected": settings.service_did},
            )
        return doc
    services = doc.get("service")
    if not isinstance(services, list):
        services = []
    service_template = did_document(settings, did).get("service", [])[0]
    normalized_services: list[dict[str, Any]] = []
    replaced = False
    for service in services:
        if not isinstance(service, dict):
            continue
        if service.get("type") != "ANPMessageService":
            normalized_services.append(service)
            continue
        if replaced:
            continue
        merged = {
            **service,
            "id": service.get("id") or service_template["id"],
            "type": "ANPMessageService",
            "serviceEndpoint": settings.anp_service_endpoint,
            "serviceDid": settings.service_did,
            "profiles": service_template["profiles"],
            "securityProfiles": service_template["securityProfiles"],
            "authSchemes": service_template["authSchemes"],
        }
        normalized_services.append(merged)
        replaced = True
    if not replaced:
        normalized_services.append(service_template)
    services = normalized_services
    doc["service"] = services
    return doc


def _anp_message_services(document: dict[str, Any]) -> list[dict[str, Any]]:
    services = document.get("service")
    if not isinstance(services, list):
        return []
    return [
        service
        for service in services
        if isinstance(service, dict) and service.get("type") == "ANPMessageService"
    ]


def _normalize_domain(raw: Any) -> str:
    domain = str(raw or "").strip().lower()
    if domain.startswith("http://") or domain.startswith("https://") or "/" in domain:
        raise InvalidParams("bare_domain_required")
    if not domain or len(domain) > 255:
        raise InvalidParams("valid_domain_required")
    if not re.fullmatch(r"[a-z0-9.-]+", domain):
        raise InvalidParams("valid_domain_required")
    if any(not part for part in domain.split(".")):
        raise InvalidParams("valid_domain_required")
    return domain


def _user_exists(conn, did: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1 FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.did = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (did,),
        ).fetchone()
        is not None
    )


def not_supported(params: dict[str, Any], request: Request) -> None:
    raise NotSupported("not_supported", data={"upgrade": "commercial", "params": params})


def _token_payload(
    *,
    did: str,
    access_token: str,
    refresh_token: str,
    access_expires_at: str,
    refresh_expires_at: str,
    refreshed: bool = False,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "access_token": access_token,
        "token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "expires_at": access_expires_at,
        "refresh_expires_at": refresh_expires_at,
        "did": did,
        "user_id": user_id or did,
        "refreshed": refreshed,
    }


def _rotate_tokens_for_did(request: Request, did: str) -> dict[str, Any]:
    access_token = new_id("tok")
    refresh_token = new_id("rtok")
    access_expires_at = _future_iso(ACCESS_TOKEN_TTL_SECONDS)
    refresh_expires_at = _future_iso(REFRESH_TOKEN_TTL_SECONDS)
    account = None
    with get_store(request).connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT u.did, d.document_json
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.did = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (did,),
        ).fetchone()
        if not row:
            raise Unauthorized("did_not_found")
        manifest = _validate_single_device_manifest(_load(row["document_json"]))
        if manifest is not None:
            account = device_account(did, manifest)
            signed_account = getattr(request.state, "signed_device_account", None)
            if signed_account is not None and signed_account != account:
                raise Unauthorized("device_authorization_invalid")
            bind_device_account(conn, account, create=signed_account == account)
            access_token = issue_device_token(account, request.app.state.auth_token_signing_key, ACCESS_TOKEN_TTL_SECONDS)
        conn.execute(
            """
            UPDATE users
            SET token = ?, refresh_token = ?, access_expires_at = ?, refresh_expires_at = ?
            WHERE did = ?
            """,
            (access_token, refresh_token, access_expires_at, refresh_expires_at, did),
        )
    if account is not None:
        request.state.response_access_token = access_token
    return _token_payload(
        did=did,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        refreshed=True,
        user_id=account.account_id if account is not None else None,
    )


def refresh_access_token(params: dict[str, Any], request: Request) -> dict[str, Any]:
    raw = str(params.get("refresh_token") or params.get("token") or params.get("access_token") or "").strip()
    if not raw:
        raise InvalidParams("refresh_token_required")
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT u.did, u.refresh_expires_at
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE (u.refresh_token = ? OR (u.refresh_token IS NULL AND u.token = ?))
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (raw, raw),
        ).fetchone()
    if not row or _is_past(row["refresh_expires_at"]):
        raise Unauthorized("invalid_refresh_token")
    return _rotate_tokens_for_did(request, str(row["did"]))


def _otp_hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _consume_registration_otp(conn, *, phone: str, otp: str, handle: str | None) -> None:
    row = conn.execute(
        "SELECT * FROM local_registration_otps WHERE phone=? AND purpose=?",
        (phone, "awiki.identity.register.v1"),
    ).fetchone()
    if row is None or _is_past(row["expires_at"]) or row["otp_hash"] != _otp_hash(otp):
        raise Unauthorized("invalid_otp")
    if handle and row["handle"] and row["handle"] != handle:
        raise Unauthorized("invalid_otp")
    conn.execute(
        "DELETE FROM local_registration_otps WHERE phone=? AND purpose=?",
        (phone, "awiki.identity.register.v1"),
    )


def register(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    raw_handle = str(params.get("handle") or f"user-{new_id('h')[2:8]}").strip().removeprefix("@").lower()
    local_handle, handle_domain, stored_handle, full_handle = _split_handle(raw_handle, settings.did_domain.lower())
    if handle_domain != settings.did_domain.lower():
        raise InvalidParams("domain_not_supported")
    if not valid_handle_local_part(local_handle):
        raise InvalidParams("handle_invalid")
    uploaded_doc = params.get("did_document") if isinstance(params.get("did_document"), dict) else None
    if uploaded_doc and not isinstance(uploaded_doc.get("proof"), dict) and not settings.allow_unsigned_peer_dev:
        raise InvalidParams("unsigned_did_document_requires_dev_mode")
    did = params.get("did") or (uploaded_doc or {}).get("id") or _default_user_did(settings, local_handle)
    did = _validate_local_user_did(str(did), settings)
    if uploaded_doc and uploaded_doc.get("id") not in (None, did):
        raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": uploaded_doc.get("id")})
    display_name = params.get("display_name") or local_handle
    token = new_id("tok")
    refresh_token = new_id("rtok")
    access_expires_at = _future_iso(ACCESS_TOKEN_TTL_SECONDS)
    refresh_expires_at = _future_iso(REFRESH_TOKEN_TTL_SECONDS)
    doc = _ensure_anp_message_service(uploaded_doc or did_document(settings, did, stored_handle), settings, did)
    doc["id"] = did
    manifest = _validate_single_device_manifest(doc)
    user_id = f"user-{hashlib.sha256(did.encode()).hexdigest()[:24]}"
    account = device_account(did, manifest) if manifest is not None else None
    if account is not None:
        token = issue_device_token(account, request.app.state.auth_token_signing_key, ACCESS_TOKEN_TTL_SECONDS)
    phone = str(params.get("phone") or "").strip()
    otp_code = str(params.get("otp_code") or params.get("otp") or "").strip()
    with get_store(request).connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if phone:
            if not otp_code:
                raise InvalidParams("otp_required")
            _consume_registration_otp(conn, phone=phone, otp=otp_code, handle=local_handle)
        existing_handle = conn.execute("SELECT did FROM users WHERE lower(handle) = ?", (stored_handle,)).fetchone()
        if existing_handle:
            raise Conflict("handle_already_registered", data={"handle": stored_handle, "did": existing_handle["did"]})
        existing_did = conn.execute("SELECT did FROM users WHERE did = ?", (did,)).fetchone()
        if existing_did:
            raise Conflict("did_already_registered", data={"did": did})
        conn.execute(
            """
            INSERT INTO users(did, handle, token, refresh_token, access_expires_at, refresh_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (did, stored_handle, token, refresh_token, access_expires_at, refresh_expires_at, now_iso()),
        )
        if account is not None:
            bind_device_account(conn, account, create=True)
        conn.execute(
            "INSERT INTO profiles(did, handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (did, stored_handle, display_name, params.get("avatar_uri"), params.get("profile_uri"), params.get("description"), "human", params.get("profile_md")),
        )
        conn.execute(
            "INSERT INTO did_documents(did, document_json, updated_at, status, revoked_at) VALUES (?, ?, ?, 'active', NULL)",
            (did, _json(doc), now_iso()),
        )
    result = {
        "did": did,
        "user_id": user_id if account is not None else did,
        "message": "Registration successful",
        "handle": local_handle,
        "domain": settings.did_domain,
        "full_handle": full_handle,
        "token": token,
        "access_token": token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "expires_at": access_expires_at,
        "refresh_expires_at": refresh_expires_at,
        "document": doc,
    }
    if account is not None:
        request.state.response_access_token = token
    if request.url.path == "/user-service/v1/did-auth/rpc" and account is not None:
        # Official CLI 1.0.52 parse_register_outcome requires exactly these nine
        # fields; extra members fail closed as permission_denied.
        return {
            "state": "registered",
            "did": did,
            "user_id": user_id,
            "message": "Registration successful",
            "access_token": token,
            "handle": local_handle,
            "domain": settings.did_domain,
            "full_handle": full_handle,
            "binding_generation": "1",
        }
    return result


def verify(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return {"active": True, "did": did}


def verify_http_request(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return {"ok": True, "did": did, "scheme": "bearer-dev"}


def update_document(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    did = current_did(request)
    _validate_local_user_did(did, settings)
    document = params.get("document") if isinstance(params.get("document"), dict) else params.get("did_document")
    if not isinstance(document, dict):
        raise InvalidParams("did_document_required")
    if not isinstance(document.get("proof"), dict) and not settings.allow_unsigned_peer_dev:
        raise InvalidParams("unsigned_did_document_requires_dev_mode")
    if document.get("id") not in (None, did):
        raise InvalidParams("document_id_mismatch")
    if isinstance(document.get("proof"), dict) and document.get("id") != did:
        raise InvalidParams("signed_did_document_id_required")
    if document.get("id") is None:
        document["id"] = did
    document = _ensure_anp_message_service(document, settings, did)
    new_manifest = _validate_single_device_manifest(document)
    expected_hash = params.get("expected_document_hash")
    if "expected_document_hash" in params and (not isinstance(expected_hash, str) or re.fullmatch(r"sha256:[A-Za-z0-9_-]{43}", expected_hash) is None):
        raise InvalidParams("expected_document_hash_invalid")
    expected_version = params.get("expected_document_version")
    if "expected_document_version" in params and (type(expected_version) is not int or not 1 <= expected_version < 9223372036854775807 or expected_hash is None):
        raise InvalidParams("expected_document_version_invalid")
    with get_store(request).connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old_row = conn.execute(
            "SELECT document_json, document_version FROM did_documents WHERE did = ? AND status = 'active' AND revoked_at IS NULL",
            (did,),
        ).fetchone()
        if old_row is None:
            raise Unauthorized("did_not_found")
        old_document = _load(old_row["document_json"])
        version = int(old_row["document_version"])
        current_hash = "sha256:" + base64.urlsafe_b64encode(hashlib.sha256(jcs.canonicalize(old_document)).digest()).decode().rstrip("=")
        exact_cas = expected_hash == current_hash and expected_version == version
        if expected_version is not None:
            if not exact_cas and not (document == old_document and expected_version < version):
                raise Conflict("did_document_changed")
        elif expected_hash is not None and document != old_document and current_hash != expected_hash:
            raise Conflict("did_document_changed")
        old_manifest = _validate_single_device_manifest(old_document)
        if (old_manifest is None) != (new_manifest is None):
            raise NotSupported("device_enrollment_or_removal_not_supported")
        if old_manifest is not None:
            current = device_account(did, old_manifest)
            if device_account(did, new_manifest) != current:
                raise NotSupported("device_key_or_root_change_not_supported")
            bind_device_account(conn, current)
        elif isinstance(old_document.get("proof"), dict) and not settings.allow_unsigned_peer_dev:
            root_id = old_document["proof"].get("verificationMethod")
            old_root = next((item for item in old_document.get("verificationMethod", []) if item.get("id") == root_id), None)
            new_root = next((item for item in document.get("verificationMethod", []) if item.get("id") == root_id), None)
            if old_root is None or new_root != old_root or document.get("proof", {}).get("verificationMethod") != root_id:
                raise NotSupported("root_change_not_supported")
        if document != old_document or exact_cas:
            if version >= 9223372036854775807:
                raise Conflict("document_version_exhausted")
            version += 1
            conn.execute("UPDATE did_documents SET document_json=?, document_version=?, updated_at=? WHERE did=?", (_json(document), version, now_iso(), did))
    return {"did": did, "document": document, "did_document": document, "document_version": version}


def revoke(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    revoked_at = now_iso()
    with get_store(request).connect() as conn:
        user_row = conn.execute("SELECT did FROM users WHERE did = ?", (did,)).fetchone()
        if not user_row:
            raise NotFound("did_not_found")
        conn.execute("UPDATE users SET revoked_at = ? WHERE did = ? AND revoked_at IS NULL", (revoked_at, did))
        conn.execute(
            """
            UPDATE did_documents
            SET status = 'revoked', revoked_at = ?, updated_at = ?
            WHERE did = ?
            """,
            (revoked_at, revoked_at, did),
        )
    return {"ok": True, "revoked": True, "status": "revoked", "did": did, "user_id": did, "revoked_at": revoked_at}


def _did_verify_user_row(did: str, request: Request):
    with get_store(request).connect() as conn:
        return conn.execute(
            """
            SELECT u.did, u.handle, u.token, u.refresh_token, u.access_expires_at, u.refresh_expires_at, d.document_json
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.did = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (did,),
        ).fetchone()


def did_verify_send_code(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = str(params.get("did") or "").strip()
    if not did:
        raise InvalidParams("did_required")
    settings = get_settings(request)
    _validate_local_user_did(did, settings)
    return {
        "message": f"[DEV] Use DID verify code {settings.did_verify_dev_code}",
        "ok": True,
        "sent": True,
        "did": did,
        "provider": "dev",
        "dev_code": settings.did_verify_dev_code,
    }


def did_verify_login(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = str(params.get("did") or "").strip()
    code = str(params.get("code") or "").strip()
    if not did or not code:
        raise InvalidParams("did_and_code_required")
    settings = get_settings(request)
    _validate_local_user_did(did, settings)
    if code != settings.did_verify_dev_code:
        raise Unauthorized("invalid_code")
    row = _did_verify_user_row(did, request)
    if not row:
        raise Unauthorized("did_not_found")
    if not row["document_json"]:
        raise Unauthorized("did_document_not_found")
    return {**_rotate_tokens_for_did(request, did), "provider": "did_verify_dev"}


def did_verify_refresh(params: dict[str, Any], request: Request) -> dict[str, Any]:
    refresh_token = str(params.get("refresh_token") or "").strip()
    if not refresh_token:
        raise InvalidParams("refresh_token_required")
    try:
        result = refresh_access_token({"refresh_token": refresh_token}, request)
    except Unauthorized:
        raise Unauthorized("invalid_refresh_token")
    row = _did_verify_user_row(str(result["did"]), request)
    if not row or not row["document_json"]:
        raise Unauthorized("did_document_not_found")
    return {**result, "provider": "did_verify_dev"}


def get_me(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    with get_store(request).connect() as conn:
        document_row = conn.execute("SELECT document_json,document_version FROM did_documents WHERE did=? AND status='active' AND revoked_at IS NULL", (did,)).fetchone()
        if document_row is None:
            raise Unauthorized("did_not_found")
        profile["did_document"] = _load(document_row["document_json"])
        profile["document_version"] = int(document_row["document_version"])
        profile["service_endpoints"] = profile["did_document"].get("service", [])
    account = getattr(request.state, "device_account", None)
    if account is not None:
        profile["user_id"] = account.account_id
    if not bearer_token(request) and request.headers.get("signature-input"):
        return {**profile, **_rotate_tokens_for_did(request, did)}
    return profile


def update_me(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    alias_map = {
        "nick_name": "display_name",
        "nickName": "display_name",
        "avatar_url": "avatar_uri",
        "avatarUrl": "avatar_uri",
        "bio": "description",
        "profile_url": "profile_uri",
        "profileUrl": "profile_uri",
    }
    normalized = dict(params)
    for source, target in alias_map.items():
        if source in params and target not in normalized:
            normalized[target] = params[source]
    fields = ["display_name", "avatar_uri", "profile_uri", "description", "profile_md", "subject_type"]
    with get_store(request).connect() as conn:
        for field in fields:
            if field in normalized:
                conn.execute(f"UPDATE profiles SET {field} = ? WHERE did = ?", (normalized.get(field), did))
    return get_me({}, request)


def public_profile(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    did = params.get("did") or params.get("user_id")
    handle = params.get("handle")
    if did and handle:
        raise InvalidParams("did_or_handle_exclusive")
    with get_store(request).connect() as conn:
        if did:
            row = conn.execute(
                """
                SELECT p.* FROM profiles p
                JOIN users u ON u.did = p.did
                JOIN did_documents d ON d.did = p.did
                WHERE p.did = ?
                  AND u.revoked_at IS NULL
                  AND d.status = 'active'
                  AND d.revoked_at IS NULL
                """,
                (did,),
            ).fetchone()
        elif handle:
            _, _, stored_handle, _ = _split_handle(str(handle), settings.did_domain)
            row = conn.execute(
                """
                SELECT p.* FROM profiles p
                JOIN users u ON u.did = p.did
                JOIN did_documents d ON d.did = p.did
                WHERE p.handle = ?
                  AND u.revoked_at IS NULL
                  AND d.status = 'active'
                  AND d.revoked_at IS NULL
                """,
                (stored_handle,),
            ).fetchone()
        else:
            raise InvalidParams("did_or_handle_required")
    if not row:
        if handle:
            raise _user_service_not_found("handle", str(handle))
        raise _user_service_not_found("did", str(did))
    profile = dict(row)
    with get_store(request).connect() as conn:
        doc_row = conn.execute(
            """
            SELECT document_json FROM did_documents
            WHERE did = ? AND COALESCE(status, 'active') = 'active' AND revoked_at IS NULL
            """,
            (profile["did"],),
        ).fetchone()
    document = _load(doc_row["document_json"]) if doc_row else {}
    services = document.get("service") if isinstance(document, dict) else []
    service_endpoints = services if isinstance(services, list) else []
    display_name = profile.get("display_name")
    description = profile.get("description")
    avatar_uri = profile.get("avatar_uri")
    profile_uri = profile.get("profile_uri")
    return {
        **profile,
        "full_handle": _split_handle(str(profile["handle"]), settings.did_domain)[3],
        "user_id": profile["did"],
        "user_name": display_name,
        "nick_name": display_name,
        "nickName": display_name,
        "avatar_url": avatar_uri,
        "avatarUrl": avatar_uri,
        "bio": description,
        "profile_url": profile_uri,
        "profileUrl": profile_uri,
        "service_endpoints": service_endpoints,
        "did_document": document,
    }


def _legacy_profile_view(profile: dict[str, Any], request: Request, *, public_only: bool = False) -> dict[str, Any]:
    settings = get_settings(request)
    local, domain, _, full_handle = _split_handle(str(profile["handle"]), settings.did_domain)
    display_name = profile.get("display_name")
    description = profile.get("description")
    avatar_uri = profile.get("avatar_uri")
    profile_uri = profile.get("profile_uri") or f"{settings.public_base_url.rstrip('/')}/profiles/{profile['did']}"
    result = {
        "user_id": profile["did"],
        "did": profile["did"],
        "user_name": local,
        "nick_name": display_name,
        "nickName": display_name,
        "display_name": display_name,
        "avatar_url": avatar_uri,
        "avatarUrl": avatar_uri,
        "avatar_uri": avatar_uri,
        "bio": description,
        "description": description,
        "profile_md": profile.get("profile_md"),
        "profile_url": profile_uri,
        "profileUrl": profile_uri,
        "profile_uri": profile_uri,
        "handle": full_handle,
        "domain": domain,
        "subject_type": profile.get("subject_type") or "human",
        "status": "active",
    }
    if not public_only:
        result.update(
            {
                "email": None,
                "phone": None,
                "gender": None,
                "tags": [],
                "created_at": None,
                "updated_at": None,
            }
        )
    return result


def legacy_me_profile(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return _legacy_profile_view(_profile_from_did(request, did), request)


def legacy_update_me(params: dict[str, Any], request: Request) -> dict[str, Any]:
    update_me(params, request)
    return legacy_me_profile({}, request)


def legacy_public_profile(params: dict[str, Any], request: Request) -> dict[str, Any]:
    user_id = params.get("user_id") or params.get("did")
    handle = params.get("handle")
    if user_id:
        profile = _profile_from_did(request, str(user_id))
    elif handle:
        result = public_profile({"handle": handle}, request)
        profile = {
            "did": result["did"],
            "handle": result["handle"],
            "display_name": result.get("display_name"),
            "avatar_uri": result.get("avatar_uri"),
            "profile_uri": result.get("profile_uri"),
            "description": result.get("description"),
            "subject_type": result.get("subject_type"),
            "profile_md": result.get("profile_md"),
        }
    else:
        raise InvalidParams("user_id_required")
    return _legacy_profile_view(profile, request, public_only=True)


def profile_markdown(user_id: str, request: Request) -> str:
    profile = _profile_from_did(request, user_id)
    view = _legacy_profile_view(profile, request, public_only=True)
    title = view.get("nick_name") or view.get("user_name") or user_id
    lines = [f"# {title}", ""]
    if view.get("bio"):
        lines.extend([str(view["bio"]), ""])
    if view.get("profile_md"):
        lines.extend([str(view["profile_md"]).strip(), ""])
    else:
        lines.extend(["No public profile content yet.", ""])
    lines.extend(
        [
            "## Identity",
            "",
            f"- DID: `{user_id}`",
            f"- Handle: `{view['handle']}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _profile_from_did(request: Request, did: str) -> dict[str, Any]:
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE did = ?", (did,)).fetchone()
    if not row:
        raise NotFound("profile_not_found")
    return dict(row)


def _users_profile_view(profile: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    local, domain, _, full = _split_handle(str(profile["handle"]), settings.did_domain)
    display_name = profile.get("display_name") or local
    description = profile.get("description")
    profile_uri = profile.get("profile_uri") or f"{settings.public_base_url.rstrip('/')}/profiles/{profile['did']}"
    with get_store(request).connect() as conn:
        user_row = conn.execute("SELECT created_at FROM users WHERE did = ?", (profile["did"],)).fetchone()
    return {
        "did": profile["did"],
        "user_name": local,
        "nick_name": profile.get("display_name"),
        "display_name": display_name,
        "avatar_uri": profile.get("avatar_uri"),
        "bio": description,
        "description": description,
        "subject_type": profile.get("subject_type") or "unknown",
        "tags": [],
        "profile_md": profile.get("profile_md"),
        "profile_uri": profile_uri,
        "created_at": user_row["created_at"] if user_row else "",
        "handle": local,
        "handle_domain": domain,
        "full_handle": full,
    }


def users_get_me(_: dict[str, Any], request: Request) -> dict[str, Any]:
    return _users_profile_view(_profile_from_did(request, current_did(request)), request)


def users_get_by_did(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = params.get("did")
    if not did:
        raise InvalidParams("did_required")
    return _users_profile_view(_profile_from_did(request, str(did)), request)


def users_get_by_dids(params: dict[str, Any], request: Request) -> dict[str, Any]:
    dids = params.get("dids")
    if not isinstance(dids, list) or not dids:
        raise InvalidParams("dids_required")
    if len(dids) > 100:
        raise InvalidParams("too_many_dids", data={"max": 100})
    users: list[dict[str, Any]] = []
    for did in dids:
        if not isinstance(did, str):
            continue
        try:
            users.append(_users_profile_view(_profile_from_did(request, did), request))
        except NotFound:
            continue
    return {"users": users}


def users_get_by_handle(params: dict[str, Any], request: Request) -> dict[str, Any]:
    handle = params.get("handle")
    if not isinstance(handle, str) or not handle.strip():
        raise InvalidParams("handle_required")
    settings = get_settings(request)
    domain = params.get("domain")
    if domain is not None and not isinstance(domain, str):
        raise InvalidParams("domain_must_be_string")
    if "." in handle.strip().removeprefix("wba://"):
        local, parsed_domain, stored_handle, _ = _split_handle(handle, settings.did_domain)
        if domain and parsed_domain != _normalize_domain(domain):
            raise InvalidParams("handle_domain_mismatch")
    else:
        local = handle.strip().removeprefix("wba://").lower()
        parsed_domain = _normalize_domain(domain) if domain else settings.did_domain
        stored_handle = f"{local}@{parsed_domain}"
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE handle = ?", (stored_handle,)).fetchone()
    if not row:
        raise NotFound("handle_not_found")
    return _users_profile_view(dict(row), request)


def resolve_profile(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = params.get("did")
    if not did:
        raise InvalidParams("did_required")
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT document_json FROM did_documents
            WHERE did = ? AND COALESCE(status, 'active') = 'active' AND revoked_at IS NULL
            """,
            (did,),
        ).fetchone()
    if not row:
        raise _user_service_not_found("did", str(did))
    return {"did": did, "document": _load(row["document_json"])}


def _split_handle(handle: str, default_domain: str) -> tuple[str, str, str, str]:
    raw = handle.strip()
    if raw.startswith("wba://"):
        raw = raw.removeprefix("wba://")
    if "@" in raw:
        local, domain = raw.split("@", 1)
    elif "." in raw:
        local, domain = raw.split(".", 1)
    else:
        local, domain = raw, default_domain
    stored = f"{local}@{domain}"
    full = f"{local}.{domain}"
    return local, domain, stored, full


def _remote_web_handle_lookup(request: Request, *, did: str | None = None, handle: str | None = None) -> dict[str, Any]:
    settings = get_settings(request)
    document = runtime._fetch_did_document(did, settings) if did else None
    if document is not None:
        if document.get("id") != did:
            raise InvalidParams("did_document_id_mismatch")
        handle = web_handle_hint(document)
    if not handle:
        raise _user_service_not_found("handle")
    # Keep Web compatibility requests on the same pinned, bounded, no-redirect
    # HTTP path as DID discovery; do not use the SDK's separate network client.
    binding = runtime._http_get_json(web_handle_resolution_url(handle))
    resolved = binding.get("did")
    if not isinstance(resolved, str) or not resolved.startswith("did:web:") or (did is not None and resolved != did):
        raise InvalidParams("web_handle_binding_invalid")
    document = document or runtime._fetch_did_document(resolved, settings)
    try:
        verified = verify_web_handle_documents(handle, binding, document)
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code) from exc
    local, domain = verified.handle.split(".", 1)
    # Preserve the existing directory-subject namespace; this is not a foreign
    # account claim and does not create a local Web user or device binding.
    return {"did": resolved, "user_id": f"user-{hashlib.sha256(resolved.encode()).hexdigest()[:24]}",
            "handle": local, "domain": domain, "full_handle": verified.handle,
            "binding_generation": verified.binding_generation, "status": "active",
            "profile": {"did": resolved, "handle": f"{local}@{domain}",
                        "display_name": verified.profile.display_name if verified.profile else local}}


def handle_lookup(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    did = params.get("did")
    handle = params.get("handle")
    stored_handle = None
    if handle:
        _, _, stored_handle, _ = _split_handle(str(handle), settings.did_domain)
    with get_store(request).connect() as conn:
        if did:
            row = conn.execute(
                """
                SELECT p.* FROM profiles p
                JOIN users u ON u.did = p.did
                LEFT JOIN did_documents d ON d.did = p.did
                WHERE p.did = ?
                  AND u.revoked_at IS NULL
                  AND COALESCE(d.status, 'active') = 'active'
                  AND d.revoked_at IS NULL
                """,
                (did,),
            ).fetchone()
        elif stored_handle:
            row = conn.execute(
                """
                SELECT p.* FROM profiles p
                JOIN users u ON u.did = p.did
                LEFT JOIN did_documents d ON d.did = p.did
                WHERE p.handle = ?
                  AND u.revoked_at IS NULL
                  AND COALESCE(d.status, 'active') = 'active'
                  AND d.revoked_at IS NULL
                """,
                (stored_handle,),
            ).fetchone()
        else:
            raise InvalidParams("did_or_handle_required")
    if not row:
        if isinstance(did, str) and did.startswith("did:web:"):
            return _remote_web_handle_lookup(request, did=did)
        if not isinstance(did, str) or _did_domain(did) in {None, settings.did_domain.lower()}:
            value = str(handle) if handle else None
            error = _user_service_not_found("handle", value)
            if did and not handle:
                error.data["did"] = str(did)
            raise error
        document = runtime._fetch_did_document(did, settings)
        verify_did_document_data_integrity_proof(document, expected_did=did)
        parts = _did_parts(did)
        try:
            user_marker = "user" if "user" in parts else "users"
            local = parts[parts.index(user_marker) + 1]
        except (ValueError, IndexError) as exc:
            raise _user_service_not_found("handle") from exc
        domain = _did_domain(did)
        if not local or not domain:
            raise _user_service_not_found("handle")
        full = f"{local}.{domain}"
        return {
            "did": did,
            "user_id": f"user-{hashlib.sha256(did.encode()).hexdigest()[:24]}",
            "handle": local,
            "domain": domain,
            "full_handle": full,
            "status": "active",
            "profile": {
                "did": did,
                "handle": f"{local}@{domain}",
                "display_name": local,
            },
        }
    profile = dict(row)
    local, domain, _, full = _split_handle(profile["handle"], settings.did_domain)
    return {
        "did": profile["did"],
        # The latest clients treat the Handle authority subject as the stable
        # account identifier and explicitly reject a credential DID fallback.
        "user_id": f"user-{hashlib.sha256(profile['did'].encode()).hexdigest()[:24]}",
        "handle": local,
        "domain": domain,
        "full_handle": full,
        "status": "active",
        "profile": {**profile, "full_handle": full},
    }


def _handle_document_from_profile(profile: dict[str, Any], settings: Settings) -> dict[str, Any]:
    local, domain, _, full = _split_handle(profile["handle"], settings.did_domain)
    revoked = bool(
        profile.get("user_revoked_at")
        or profile.get("did_revoked_at")
        or profile.get("did_status") == "revoked"
    )
    updated = str(profile.get("did_updated_at") or now_iso())
    display_name = profile.get("display_name")
    description = profile.get("description")
    avatar_uri = profile.get("avatar_uri")
    profile_uri = profile.get("profile_uri") or f"https://{full}/"
    return {
        "handle": full,
        "did": profile["did"],
        "status": "revoked" if revoked else "active",
        "binding_generation": str(profile.get("handle_binding_generation") or "1"),
        "updated": updated,
        "profile": {
            "type": "DIDSubjectProfile",
            "subject_did": profile["did"],
            "subject_type": profile.get("subject_type") or "person",
            "handle": full,
            "display_name": display_name,
            "description": description,
            "avatar_uri": avatar_uri,
            "profile_uri": profile_uri,
            "updated": updated,
        },
        "local_part": local,
        "domain": domain,
    }


def handle_resolution_document(local_part: str, request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    _, _, stored_handle, _ = _split_handle(local_part, settings.did_domain)
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   u.handle_binding_generation,
                   u.revoked_at AS user_revoked_at,
                   d.status AS did_status,
                   d.revoked_at AS did_revoked_at,
                   d.updated_at AS did_updated_at
            FROM profiles p
            JOIN users u ON u.did = p.did
            JOIN did_documents d ON d.did = p.did
            WHERE p.handle = ?
            """,
            (stored_handle,),
        ).fetchone()
    if not row:
        raise _user_service_not_found("handle", stored_handle.replace("@", ".", 1))
    return _handle_document_from_profile(dict(row), settings)


def handle_confirmation_document(did: str, request: Request) -> dict[str, Any]:
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   u.handle_binding_generation,
                   u.revoked_at AS user_revoked_at,
                   d.status AS did_status,
                   d.revoked_at AS did_revoked_at,
                   d.updated_at AS did_updated_at
            FROM profiles p
            JOIN users u ON u.did = p.did
            JOIN did_documents d ON d.did = p.did
            WHERE p.did = ?
            """,
            (did,),
        ).fetchone()
    if not row:
        raise _user_service_not_found("did", did)
    handle_document = _handle_document_from_profile(dict(row), get_settings(request))
    return {
        "did": did,
        "confirmed": True,
        "status": handle_document["status"],
        "binding_generation": handle_document["binding_generation"],
        "updated": handle_document["updated"],
        "handle": handle_document["handle"],
    }


def get_my_handle(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = _profile_from_did(request, did)
    local, domain, _, full = _split_handle(profile["handle"], get_settings(request).did_domain)
    return {"handle": local, "did": did, "domain": domain, "status": "active", "full_handle": full}


def get_my_handles(_: dict[str, Any], request: Request) -> dict[str, Any]:
    return {"handles": [get_my_handle({}, request)]}


def get_quota(_: dict[str, Any], request: Request) -> dict[str, Any]:
    current_did(request)
    return {"max_handles": 1, "used": 1, "remaining": 0, "community_edition": True}


def issue_agent_token(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    agent_kind = str(params.get("agent_kind") or params.get("kind") or "daemon")
    ttl_seconds = int(params.get("ttl_seconds") or 3600)
    ttl_seconds = max(60, min(ttl_seconds, 86400))
    token = new_id("agt")
    token_hash = _sha256_hex(token)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    with get_store(request).connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_registration_tokens(token_hash, owner_did, agent_kind, expires_at, revoked_at, used_at, agent_did, created_at)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (token_hash, owner, agent_kind, expires_at, now_iso()),
        )
    return {
        "token": token,
        "registration_token": token,
        "token_hash": token_hash,
        "owner_did": owner,
        "agent_kind": agent_kind,
        "expires_at": expires_at,
        "expires_in": ttl_seconds,
        "one_time": True,
    }


def _agent_token_row(params: dict[str, Any], request: Request):
    token = params.get("token") or params.get("registration_token")
    if not token:
        raise InvalidParams("registration_token_required")
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_registration_tokens WHERE token_hash = ?",
            (_sha256_hex(str(token)),),
        ).fetchone()
    if not row:
        raise NotFound("registration_token_not_found")
    return dict(row)


def _agent_token_status(row: dict[str, Any]) -> str:
    if row.get("revoked_at"):
        return "revoked"
    if row.get("used_at"):
        return "used"
    if _parse_time(str(row["expires_at"])) < datetime.now(timezone.utc):
        return "expired"
    return "active"


def verify_agent_token(params: dict[str, Any], request: Request) -> dict[str, Any]:
    row = _agent_token_row(params, request)
    status = _agent_token_status(row)
    return {
        "active": status == "active",
        "status": status,
        "owner_did": row["owner_did"],
        "agent_kind": row["agent_kind"],
        "expires_at": row["expires_at"],
        "used_at": row["used_at"],
        "revoked_at": row["revoked_at"],
        "agent_did": row["agent_did"],
    }


def exchange_agent_token(params: dict[str, Any], request: Request) -> dict[str, Any]:
    row = _agent_token_row(params, request)
    status = _agent_token_status(row)
    if status != "active":
        raise InvalidParams("registration_token_not_active", data={"status": status})
    agent_did = params.get("agent_did") or (params.get("did_document") if isinstance(params.get("did_document"), dict) else {}).get("id")
    if not agent_did:
        agent_did = f"{row['owner_did']}:agents:{new_id('agent')[6:]}"
    document = params.get("did_document") if isinstance(params.get("did_document"), dict) else None
    if document:
        document["id"] = str(agent_did)
    with get_store(request).connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM did_documents WHERE did=?", (str(agent_did),)).fetchone() is not None:
            raise Conflict("did_document_already_registered")
        conn.execute(
            "UPDATE agent_registration_tokens SET used_at = ?, agent_did = ? WHERE token_hash = ?",
            (now_iso(), str(agent_did), row["token_hash"]),
        )
        if document:
            conn.execute(
                "INSERT INTO did_documents(did, document_json, updated_at) VALUES (?, ?, ?)",
                (str(agent_did), _json(document), now_iso()),
            )
    owner_profile = _profile_from_did(request, str(row["owner_did"]))
    _, _, _, owner_full_handle = _split_handle(owner_profile["handle"], get_settings(request).did_domain)
    token_id = row["token_hash"][:16]
    handle = str(params.get("handle") or params.get("name") or str(agent_did).split(":")[-1])
    return {
        "exchanged": True,
        "token_id": token_id,
        "did": str(agent_did),
        "status": "used",
        "owner_did": row["owner_did"],
        "user_id": str(agent_did),
        "agent_did": str(agent_did),
        "agent_kind": row["agent_kind"],
        "controller_did": row["owner_did"],
        "controller_user_id": row["owner_did"],
        "controller_full_handle": owner_full_handle,
        "handle": handle,
        "did_document": document,
    }


def revoke_agent_token(params: dict[str, Any], request: Request) -> dict[str, Any]:
    row = _agent_token_row(params, request)
    revoked_at = now_iso()
    with get_store(request).connect() as conn:
        conn.execute(
            "UPDATE agent_registration_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (revoked_at, row["token_hash"]),
        )
    return {"revoked": True, "status": "revoked", "revoked_at": revoked_at}


def _binding_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": row["binding_id"],
        "human_did": row["human_did"],
        "daemon_did": row["daemon_did"],
        "runtime_agent_did": row["runtime_agent_did"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
    }


def ensure_agent_binding(params: dict[str, Any], request: Request) -> dict[str, Any]:
    authenticated = current_did(request, required=False)
    human_did = str(params.get("human_did") or authenticated or "")
    daemon_did = str(params.get("daemon_did") or "")
    runtime_agent_did = str(params.get("runtime_agent_did") or params.get("agent_did") or "")
    if not human_did or not daemon_did or not runtime_agent_did:
        raise InvalidParams("human_daemon_runtime_did_required")
    now = now_iso()
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM message_agent_bindings
            WHERE human_did = ? AND daemon_did = ? AND runtime_agent_did = ?
            """,
            (human_did, daemon_did, runtime_agent_did),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE message_agent_bindings SET status = 'active', updated_at = ? WHERE binding_id = ?",
                (now, row["binding_id"]),
            )
            row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (row["binding_id"],)).fetchone()
        else:
            binding_id = new_id("bind")
            conn.execute(
                """
                INSERT INTO message_agent_bindings(binding_id, human_did, daemon_did, runtime_agent_did, status, created_at, updated_at, last_seen_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                """,
                (binding_id, human_did, daemon_did, runtime_agent_did, now, now),
            )
            row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (binding_id,)).fetchone()
    return {"binding": _binding_payload(dict(row)), **_binding_payload(dict(row))}


def get_active_binding(params: dict[str, Any], request: Request) -> dict[str, Any]:
    authenticated = current_did(request, required=False)
    human_did = params.get("human_did") or authenticated
    with get_store(request).connect() as conn:
        if human_did:
            row = conn.execute(
                "SELECT * FROM message_agent_bindings WHERE human_did = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                (human_did,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM message_agent_bindings WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        raise NotFound("active_binding_not_found")
    return {"binding": _binding_payload(dict(row)), **_binding_payload(dict(row))}


def list_bindings(params: dict[str, Any], request: Request) -> dict[str, Any]:
    authenticated = current_did(request, required=False)
    human_did = params.get("human_did") or authenticated
    with get_store(request).connect() as conn:
        if human_did:
            rows = conn.execute(
                "SELECT * FROM message_agent_bindings WHERE human_did = ? ORDER BY updated_at DESC",
                (human_did,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM message_agent_bindings ORDER BY updated_at DESC").fetchall()
    bindings = [_binding_payload(dict(row)) for row in rows]
    return {"bindings": bindings, "count": len(bindings)}


def _update_binding_status(params: dict[str, Any], request: Request, status: str) -> dict[str, Any]:
    binding_id = params.get("binding_id")
    if not binding_id:
        raise InvalidParams("binding_id_required")
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (binding_id,)).fetchone()
        if not row:
            raise NotFound("binding_not_found")
        conn.execute(
            "UPDATE message_agent_bindings SET status = ?, updated_at = ? WHERE binding_id = ?",
            (status, now_iso(), binding_id),
        )
        row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (binding_id,)).fetchone()
    return {"binding": _binding_payload(dict(row)), **_binding_payload(dict(row))}


def disable_binding(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _update_binding_status(params, request, "disabled")


def revoke_binding(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return _update_binding_status(params, request, "revoked")


def mark_binding_seen(params: dict[str, Any], request: Request) -> dict[str, Any]:
    binding_id = params.get("binding_id")
    daemon_did = params.get("daemon_did")
    now = now_iso()
    with get_store(request).connect() as conn:
        if binding_id:
            row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (binding_id,)).fetchone()
        elif daemon_did:
            row = conn.execute(
                "SELECT * FROM message_agent_bindings WHERE daemon_did = ? ORDER BY updated_at DESC LIMIT 1",
                (daemon_did,),
            ).fetchone()
        else:
            raise InvalidParams("binding_id_or_daemon_did_required")
        if not row:
            raise NotFound("binding_not_found")
        conn.execute(
            "UPDATE message_agent_bindings SET last_seen_at = ?, updated_at = ? WHERE binding_id = ?",
            (now, now, row["binding_id"]),
        )
        row = conn.execute("SELECT * FROM message_agent_bindings WHERE binding_id = ?", (row["binding_id"],)).fetchone()
    return {"seen": True, "last_seen_at": now, "binding": _binding_payload(dict(row))}


def _controller_scope_for_daemon(request: Request, daemon_agent_did: str) -> dict[str, str]:
    with get_store(request).connect() as conn:
        binding = conn.execute(
            """
            SELECT * FROM message_agent_bindings
            WHERE daemon_did = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (daemon_agent_did,),
        ).fetchone()
    if binding:
        controller_did = str(binding["human_did"])
    else:
        token_owner = None
        with get_store(request).connect() as conn:
            row = conn.execute(
                "SELECT owner_did FROM agent_registration_tokens WHERE agent_did = ? ORDER BY created_at DESC LIMIT 1",
                (daemon_agent_did,),
            ).fetchone()
            if row:
                token_owner = str(row["owner_did"])
        controller_did = token_owner or current_did(request, required=False) or daemon_agent_did
    try:
        profile = _profile_from_did(request, controller_did)
        _, _, _, full_handle = _split_handle(profile["handle"], get_settings(request).did_domain)
    except NotFound:
        full_handle = controller_did
    return {
        "controller_user_id": controller_did,
        "controller_full_handle": full_handle,
        "controller_did": controller_did,
    }


def _agent_inventory_row_payload(row: dict[str, Any], request: Request) -> dict[str, Any]:
    latest = _load(row["latest_status_json"]) if row.get("latest_status_json") else {}
    policy = _load(row["invocation_policy_json"]) if row.get("invocation_policy_json") else _default_invocation_policy()
    return {
        "agent_did": row["agent_did"],
        "daemon_agent_did": row["daemon_agent_did"],
        "controller_did": row["controller_did"],
        "controller_user_id": row["controller_did"],
        "controller_full_handle": _controller_scope_for_daemon(request, row["daemon_agent_did"])["controller_full_handle"],
        "agent_kind": row["agent_kind"],
        "status": row["status"],
        "display_name": row["display_name"],
        "latest_status": latest,
        "invocation_policy": policy,
        "archived_at": row["archived_at"],
        "updated_at": row["updated_at"],
    }


def _default_invocation_policy() -> dict[str, Any]:
    return {
        "active_mode": "controller_only",
        "whitelist_handles": [],
        "blacklist_handles": [],
    }


def _status_item(params: dict[str, Any], daemon_agent_did: str, controller_did: str, item: dict[str, Any], request: Request) -> dict[str, Any]:
    agent_did = str(item.get("agent_did") or "")
    if not agent_did:
        raise InvalidParams("agent_did_required")
    agent_kind = str(item.get("agent_kind") or item.get("kind") or "runtime")
    status = str(item.get("status") or "unknown")
    now = now_iso()
    latest = dict(item)
    latest.setdefault("agent_did", agent_did)
    latest.setdefault("agent_kind", agent_kind)
    latest.setdefault("status", status)
    with get_store(request).connect() as conn:
        existing = conn.execute("SELECT invocation_policy_json, display_name FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
        policy_json = existing["invocation_policy_json"] if existing else _json(_default_invocation_policy())
        display_name = existing["display_name"] if existing else item.get("display_name")
        conn.execute(
            """
            INSERT INTO agent_inventory_statuses(
              agent_did, daemon_agent_did, controller_did, agent_kind, status,
              display_name, latest_status_json, invocation_policy_json, archived_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(agent_did) DO UPDATE SET
              daemon_agent_did = excluded.daemon_agent_did,
              controller_did = excluded.controller_did,
              agent_kind = excluded.agent_kind,
              status = excluded.status,
              latest_status_json = excluded.latest_status_json,
              updated_at = excluded.updated_at
            """,
            (agent_did, daemon_agent_did, controller_did, agent_kind, status, display_name, _json(latest), policy_json, now),
        )
        row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
    payload = _agent_inventory_row_payload(dict(row), request)
    return {
        "agent_did": payload["agent_did"],
        "daemon_agent_did": payload["daemon_agent_did"],
        "controller_did": payload["controller_did"],
        "status": payload["status"],
        "agent_kind": payload["agent_kind"],
        "updated_at": payload["updated_at"],
    }


def agent_inventory_update_latest_status(params: dict[str, Any], request: Request) -> dict[str, Any]:
    daemon_agent_did = str(params.get("daemon_agent_did") or "")
    if not daemon_agent_did:
        raise InvalidParams("daemon_agent_did_required")
    statuses = params.get("statuses")
    if not isinstance(statuses, list):
        raise InvalidParams("statuses_required")
    scope = _controller_scope_for_daemon(request, daemon_agent_did)
    updated = [
        _status_item(params, daemon_agent_did, scope["controller_did"], item, request)
        for item in statuses
        if isinstance(item, dict)
    ]
    return {"updated": updated}


def agent_inventory_sync_controller_scope(params: dict[str, Any], request: Request) -> dict[str, Any]:
    daemon_agent_did = str(params.get("daemon_agent_did") or "")
    if not daemon_agent_did:
        raise InvalidParams("daemon_agent_did_required")
    scope = _controller_scope_for_daemon(request, daemon_agent_did)
    with get_store(request).connect() as conn:
        updated = conn.execute(
            "UPDATE agent_inventory_statuses SET controller_did = ?, updated_at = ? WHERE daemon_agent_did = ?",
            (scope["controller_did"], now_iso(), daemon_agent_did),
        ).rowcount
    return {**scope, "updated_count": updated}


def agent_inventory_verify_controller_sender(params: dict[str, Any], request: Request) -> dict[str, Any]:
    daemon_agent_did = str(params.get("daemon_agent_did") or "")
    sender_did = str(params.get("sender_did") or "")
    if not daemon_agent_did or not sender_did:
        raise InvalidParams("daemon_agent_did_and_sender_did_required")
    scope = _controller_scope_for_daemon(request, daemon_agent_did)
    if sender_did != scope["controller_did"]:
        with get_store(request).connect() as conn:
            if not _user_exists(conn, sender_did):
                raise Unauthorized("sender_not_controller", data={"controller_did": scope["controller_did"], "sender_did": sender_did})
    return {**scope, "sender_did": sender_did}


def _sender_identity(request: Request, sender_did: str) -> tuple[str | None, str | None]:
    try:
        profile = _profile_from_did(request, sender_did)
    except NotFound:
        return None, None
    _, _, _, full_handle = _split_handle(profile["handle"], get_settings(request).did_domain)
    return sender_did, full_handle


def agent_inventory_authorize_invocation(params: dict[str, Any], request: Request) -> dict[str, Any]:
    daemon_agent_did = str(params.get("daemon_agent_did") or "")
    agent_did = str(params.get("agent_did") or "")
    sender_did = str(params.get("sender_did") or "")
    if not daemon_agent_did or not agent_did or not sender_did:
        raise InvalidParams("daemon_agent_did_agent_did_sender_did_required")
    scope = _controller_scope_for_daemon(request, daemon_agent_did)
    sender_user_id, sender_full_handle = _sender_identity(request, sender_did)
    allowed = sender_did == scope["controller_did"] or sender_user_id is not None
    reason = "allowed" if allowed else "sender_not_known"
    return {
        "allowed": allowed,
        "reason": reason,
        "agent_did": agent_did,
        "sender_did": sender_did,
        "sender_user_id": sender_user_id if allowed else None,
        "sender_full_handle": sender_full_handle if allowed else None,
        "active_mode": "controller_only" if sender_did == scope["controller_did"] else "known_local_user",
    }


def agent_inventory_archive_agent(params: dict[str, Any], request: Request) -> dict[str, Any]:
    daemon_agent_did = str(params.get("daemon_agent_did") or "")
    agent_did = str(params.get("agent_did") or "")
    if not daemon_agent_did or not agent_did:
        raise InvalidParams("daemon_agent_did_and_agent_did_required")
    archived_at = now_iso()
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
        if row:
            conn.execute(
                "UPDATE agent_inventory_statuses SET status = 'archived', archived_at = ?, updated_at = ? WHERE agent_did = ?",
                (archived_at, archived_at, agent_did),
            )
            row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
            archived = [_agent_inventory_row_payload(dict(row), request)]
        else:
            scope = _controller_scope_for_daemon(request, daemon_agent_did)
            archived = [
                {
                    "agent_did": agent_did,
                    "daemon_agent_did": daemon_agent_did,
                    "controller_did": scope["controller_did"],
                    "status": "archived",
                    "archived_at": archived_at,
                    "updated_at": archived_at,
                }
            ]
    return {"archived": archived}


def agent_inventory_list_agents(params: dict[str, Any], request: Request) -> dict[str, Any]:
    controller = current_did(request, required=False)
    include_inactive = bool(params.get("include_inactive", False))
    with get_store(request).connect() as conn:
        if controller:
            if include_inactive:
                rows = conn.execute("SELECT * FROM agent_inventory_statuses WHERE controller_did = ? ORDER BY updated_at DESC", (controller,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_inventory_statuses WHERE controller_did = ? AND archived_at IS NULL ORDER BY updated_at DESC",
                    (controller,),
                ).fetchall()
        else:
            if include_inactive:
                rows = conn.execute("SELECT * FROM agent_inventory_statuses ORDER BY updated_at DESC").fetchall()
            else:
                rows = conn.execute("SELECT * FROM agent_inventory_statuses WHERE archived_at IS NULL ORDER BY updated_at DESC").fetchall()
    agents = [_agent_inventory_row_payload(dict(row), request) for row in rows]
    return {"agents": agents, "count": len(agents)}


def agent_inventory_update_display_name(params: dict[str, Any], request: Request) -> dict[str, Any]:
    agent_did = str(params.get("agent_did") or "")
    display_name = params.get("display_name")
    if not agent_did:
        raise InvalidParams("agent_did_required")
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
        if not row:
            raise NotFound("agent_not_found")
        conn.execute("UPDATE agent_inventory_statuses SET display_name = ?, updated_at = ? WHERE agent_did = ?", (display_name, now_iso(), agent_did))
        row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
    return {"agent": _agent_inventory_row_payload(dict(row), request)}


def agent_inventory_get_invocation_policy(params: dict[str, Any], request: Request) -> dict[str, Any]:
    agent_did = str(params.get("agent_did") or "")
    if not agent_did:
        raise InvalidParams("agent_did_required")
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT invocation_policy_json FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
    if not row:
        raise NotFound("agent_not_found")
    return {"agent_did": agent_did, **_load(row["invocation_policy_json"])}


def agent_inventory_update_invocation_policy(params: dict[str, Any], request: Request) -> dict[str, Any]:
    agent_did = str(params.get("agent_did") or "")
    if not agent_did:
        raise InvalidParams("agent_did_required")
    policy = _default_invocation_policy()
    for key in ["active_mode", "whitelist_handles", "blacklist_handles"]:
        if key in params:
            policy[key] = params[key]
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM agent_inventory_statuses WHERE agent_did = ?", (agent_did,)).fetchone()
        if not row:
            raise NotFound("agent_not_found")
        conn.execute("UPDATE agent_inventory_statuses SET invocation_policy_json = ?, updated_at = ? WHERE agent_did = ?", (_json(policy), now_iso(), agent_did))
    return {"agent_did": agent_did, **policy}


def agent_inventory_unbind_agent(params: dict[str, Any], request: Request) -> dict[str, Any]:
    agent_did = str(params.get("agent_did") or "")
    if not agent_did:
        raise InvalidParams("agent_did_required")
    now = now_iso()
    with get_store(request).connect() as conn:
        conn.execute("UPDATE agent_inventory_statuses SET status = 'unbound', archived_at = ?, updated_at = ? WHERE agent_did = ?", (now, now, agent_did))
    return {"ok": True}


def send_otp(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    phone = str(params.get("phone") or "").strip()
    if not phone:
        raise InvalidParams("phone_required")
    purpose = str(params.get("purpose") or "").strip()
    if purpose == "awiki.identity.register.v1":
        handle = str(params.get("handle") or "").strip() or None
        otp = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = _future_iso(600)
        with get_store(request).connect() as conn:
            conn.execute(
                """
                INSERT INTO local_registration_otps(phone, purpose, handle, otp_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone, purpose) DO UPDATE SET
                  handle=excluded.handle, otp_hash=excluded.otp_hash,
                  expires_at=excluded.expires_at, created_at=excluded.created_at
                """,
                (phone, purpose, handle, _otp_hash(otp), expires_at, now_iso()),
            )
        otp_dir = settings.data_dir / "local-registration-otp"
        otp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = otp_dir / re.sub(r"[^0-9A-Za-z]+", "_", phone)
        path.write_text(otp + "\n")
        os.chmod(path, 0o600)
        return {
            "ok": True,
            "sent": True,
            "delivery": "local_operator",
            "phone": phone,
            "handle": handle,
            "expires_in": 600,
        }
    if not settings.enable_contact_verification_compat:
        raise NotSupported(
            "contact_verification_not_enabled",
            data={
                "feature": "contact_verification",
                "reason": "email_or_phone_verification_is_not_part_of_open_server_mvp",
            },
        )
    return {
        "ok": True,
        "sent": True,
        "message": "验证码已发送",
        "phone": phone,
        "provider": "dev",
        "dev_otp": settings.contact_verification_dev_otp,
    }


IDENTITY_HANDLERS = {
    "register": register,
    "update_document": update_document,
    "verify": verify,
    "verify_http_request": verify_http_request,
    "get_me": get_me,
    "revoke": revoke,
    "replace_did": not_supported,
    "recover_handle": not_supported,
}

DID_VERIFY_HANDLERS = {
    "send_code": did_verify_send_code,
    "login": did_verify_login,
    "refresh": did_verify_refresh,
}

PROFILE_HANDLERS = {
    "get_me": get_me,
    "update_me": update_me,
    "get_public_profile": public_profile,
    "resolve": resolve_profile,
}

ME_HANDLERS = {
    "get_me": legacy_me_profile,
    "update_me": legacy_update_me,
    "get_public_profile": legacy_public_profile,
    "delete_me": not_supported,
}

HANDLE_HANDLERS = {
    "registration_check": registration_check,
    "lookup": handle_lookup,
    "send_otp": send_otp,
    "get_my_handle": get_my_handle,
    "get_my_handles": get_my_handles,
    "get_quota": get_quota,
    "request_revoke": not_supported,
    "confirm_revoke": not_supported,
    "update_wallet": not_supported,
}

USERS_HANDLERS = {
    "get_me": users_get_me,
    "get_by_did": users_get_by_did,
    "get_by_dids": users_get_by_dids,
    "get_by_handle": users_get_by_handle,
}

AGENT_REGISTRATION_HANDLERS = {
    "issue_token": issue_agent_token,
    "verify_token": verify_agent_token,
    "exchange_token": exchange_agent_token,
    "revoke_token": revoke_agent_token,
}

MESSAGE_AGENT_HANDLERS = {
    "ensure_binding": ensure_agent_binding,
    "get_active_binding": get_active_binding,
    "list_bindings": list_bindings,
    "disable_binding": disable_binding,
    "mark_seen": mark_binding_seen,
    "revoke_binding": revoke_binding,
}

AGENT_INVENTORY_HANDLERS = {
    "list_agents": agent_inventory_list_agents,
    "update_display_name": agent_inventory_update_display_name,
    "get_invocation_policy": agent_inventory_get_invocation_policy,
    "update_invocation_policy": agent_inventory_update_invocation_policy,
    "unbind_agent": agent_inventory_unbind_agent,
    "archive_agent": agent_inventory_archive_agent,
    "update_latest_status": agent_inventory_update_latest_status,
    "authorize_agent_invocation": agent_inventory_authorize_invocation,
    "sync_controller_scope": agent_inventory_sync_controller_scope,
    "verify_controller_sender": agent_inventory_verify_controller_sender,
}
