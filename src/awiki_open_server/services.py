from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any
import urllib.parse
import urllib.request

from fastapi import Request

from awiki_open_server.app.settings import Settings
from awiki_open_server.service_identity import require_origin_proof, require_signed_peer_request, validate_origin_proof_structure, verify_peer_http_signature
from awiki_open_server.shared.errors import Conflict, InvalidParams, NotFound, NotSupported, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.storage.db import Store


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load(raw: str) -> Any:
    return json.loads(raw)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
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
            SELECT u.did
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
        return str(row["did"])
    if token.startswith("did:") and _is_active_did(request, token):
        return token
    return None


def current_did(request: Request, *, required: bool = True) -> str | None:
    token = bearer_token(request)
    if not token:
        if required:
            raise Unauthorized("missing_bearer_token")
        return None
    did = did_for_token(request, token)
    if did:
        return did
    if required:
        raise Unauthorized("invalid_bearer_token")
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
                "profiles": [
                    "anp.core.binding.v1",
                    "anp.direct.base.v1",
                    "anp.group.base.v1",
                    "anp.attachment.v1",
                ],
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


def _did_domain(did: str) -> str:
    parts = did.split(":")
    if len(parts) < 3 or parts[0] != "did" or parts[1] != "wba" or not parts[2]:
        raise InvalidParams("invalid_wba_did")
    return parts[2].lower()


def _did_belongs_to_domain(did: str, domain: str) -> bool:
    try:
        return _did_domain(did) == domain.lower()
    except InvalidParams:
        return False


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


def _normalize_site_slug(raw: Any) -> str:
    slug = str(raw or "").strip().lower()
    if not slug or len(slug) > 100 or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", slug):
        raise InvalidParams("valid_slug_required")
    return slug


def _did_document_url(did: str, resolver_base_urls: dict[str, str] | None = None) -> str:
    parts = did.split(":")
    domain = _did_domain(did)
    base_url = (resolver_base_urls or {}).get(domain.lower())
    if len(parts) == 3:
        if base_url:
            return f"{base_url.rstrip('/')}/.well-known/did.json"
        return f"https://{domain}/.well-known/did.json"
    path = "/".join(urllib.parse.quote(part, safe="") for part in parts[3:] if part)
    if not path:
        if base_url:
            return f"{base_url.rstrip('/')}/.well-known/did.json"
        return f"https://{domain}/.well-known/did.json"
    if base_url:
        return f"{base_url.rstrip('/')}/{path}/did.json"
    return f"https://{domain}/{path}/did.json"


def _http_get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, dict):
        raise InvalidParams("did_document_must_be_object")
    return data


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, body_bytes: bytes | None = None) -> dict[str, Any]:
    body = body_bytes or json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, dict):
        raise InvalidParams("remote_response_must_be_object")
    return data


def _anp_message_service(document: dict[str, Any]) -> dict[str, Any]:
    services = document.get("service")
    if not isinstance(services, list):
        raise NotFound("anp_message_service_not_found")
    matches = [
        service
        for service in services
        if isinstance(service, dict) and service.get("type") == "ANPMessageService"
    ]
    if len(matches) != 1:
        raise NotFound("anp_message_service_not_found")
    endpoint = matches[0].get("serviceEndpoint")
    service_did = matches[0].get("serviceDid")
    if not isinstance(endpoint, str) or not endpoint:
        raise InvalidParams("anp_service_endpoint_required")
    if not isinstance(service_did, str) or not service_did:
        raise InvalidParams("anp_service_did_required")
    return matches[0]


def _discover_anp_service(did: str, settings: Settings) -> dict[str, Any]:
    try:
        document = _http_get_json(_did_document_url(did, settings.did_resolver_base_urls))
    except Exception as exc:
        if isinstance(exc, (InvalidParams, NotFound)):
            raise
        raise NotFound("did_document_not_found", data={"did": did, "detail": str(exc)}) from exc
    if document.get("id") not in (None, did):
        raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": document.get("id")})
    return _anp_message_service(document)


def _public_url(settings: Settings, path: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}{path}"


def _object_upload_uri(settings: Settings, slot_id: str) -> str:
    return _public_url(settings, f"{settings.object_upload_path}/{slot_id}")


def _object_download_uri(settings: Settings, object_id: str, *, ticket: str | None = None) -> str:
    uri = _public_url(settings, f"{settings.object_download_path}/{object_id}")
    if ticket:
        return f"{uri}?ticket={urllib.parse.quote(ticket, safe='')}"
    return uri


def _resolve_did_document_for_proof(request: Request, did: str) -> dict[str, Any]:
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT document_json FROM did_documents
            WHERE did = ? AND COALESCE(status, 'active') = 'active' AND revoked_at IS NULL
            """,
            (did,),
        ).fetchone()
    if row:
        document = _load(row["document_json"])
        if not isinstance(document, dict):
            raise InvalidParams("did_document_must_be_object")
        return document
    try:
        document = _http_get_json(_did_document_url(did, get_settings(request).did_resolver_base_urls))
    except Exception as exc:
        if isinstance(exc, InvalidParams):
            raise
        raise Unauthorized("origin_proof_did_document_not_found", data={"did": did, "detail": str(exc)}) from exc
    if document.get("id") != did:
        raise Unauthorized("origin_proof_did_document_mismatch", data={"did": did, "document_id": document.get("id")})
    return document


def _source_service_did(headers: dict[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "x-anp-source-service-did":
            return value
    return None


def _verify_peer_request_signature(request: Request, settings: Settings) -> None:
    headers = dict(request.headers)
    require_signed_peer_request(headers, allow_unsigned_dev=settings.allow_unsigned_peer_dev)
    if settings.allow_unsigned_peer_dev:
        return
    service_did = _source_service_did(headers)
    if not service_did:
        raise Unauthorized("missing_source_service_did")
    document = _http_get_json(_did_document_url(service_did, settings.did_resolver_base_urls))
    if document.get("id") != service_did:
        raise Unauthorized("source_service_did_document_mismatch")
    public_url = f"{settings.public_base_url.rstrip('/')}{request.url.path}"
    if request.url.query:
        public_url = f"{public_url}?{request.url.query}"
    verify_peer_http_signature(
        service_did_document=document,
        method=request.method,
        url=public_url,
        headers=headers,
        body=getattr(request.state, "raw_body", b""),
    )


def register(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    raw_handle = params.get("handle") or f"user-{new_id('h')[2:8]}"
    local_handle = str(raw_handle).split("@", 1)[0].split(".", 1)[0]
    full_handle = str(raw_handle) if ("@" in str(raw_handle) or "." in str(raw_handle)) else f"{local_handle}.{settings.did_domain}"
    stored_handle = str(raw_handle) if "@" in str(raw_handle) else f"{local_handle}@{settings.did_domain}"
    uploaded_doc = params.get("did_document") if isinstance(params.get("did_document"), dict) else None
    did = params.get("did") or (uploaded_doc or {}).get("id") or f"did:wba:{settings.did_domain}:users:{local_handle}"
    display_name = params.get("display_name") or local_handle
    token = new_id("tok")
    doc = _ensure_anp_message_service(uploaded_doc or did_document(settings, did, stored_handle), settings, did)
    doc["id"] = did
    with get_store(request).connect() as conn:
        conn.execute(
            "INSERT INTO users(did, handle, token, created_at) VALUES (?, ?, ?, ?)",
            (did, stored_handle, token, now_iso()),
        )
        conn.execute(
            "INSERT INTO profiles(did, handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (did, stored_handle, display_name, params.get("avatar_uri"), params.get("profile_uri"), params.get("description"), "human", params.get("profile_md")),
        )
        conn.execute(
            "INSERT INTO did_documents(did, document_json, updated_at, status, revoked_at) VALUES (?, ?, ?, 'active', NULL)",
            (did, _json(doc), now_iso()),
        )
    return {
        "did": did,
        "user_id": did,
        "message": "Registration successful",
        "handle": local_handle,
        "domain": settings.did_domain,
        "full_handle": full_handle,
        "token": token,
        "access_token": token,
        "document": doc,
    }


def verify(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return {"active": True, "did": did}


def verify_http_request(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return {"ok": True, "did": did, "scheme": "bearer-dev"}


def update_document(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    did = current_did(request)
    document = params.get("document") if isinstance(params.get("document"), dict) else params.get("did_document")
    if not isinstance(document, dict):
        raise InvalidParams("did_document_required")
    if document.get("id") not in (None, did):
        raise InvalidParams("document_id_mismatch")
    if isinstance(document.get("proof"), dict) and document.get("id") != did:
        raise InvalidParams("signed_did_document_id_required")
    if document.get("id") is None:
        document["id"] = did
    document = _ensure_anp_message_service(document, settings, did)
    with get_store(request).connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO did_documents(did, document_json, updated_at, status, revoked_at)
            VALUES (?, ?, ?, 'active', NULL)
            """,
            (did, _json(document), now_iso()),
        )
    return {"did": did, "document": document, "did_document": document}


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
            SELECT u.did, u.handle, u.token, d.document_json
            FROM users u
            JOIN did_documents d ON d.did = u.did
            WHERE u.did = ?
              AND u.revoked_at IS NULL
              AND d.status = 'active'
              AND d.revoked_at IS NULL
            """,
            (did,),
        ).fetchone()


def _did_verify_token_result(*, did: str, token: str, refreshed: bool = False) -> dict[str, Any]:
    return {
        "access_token": token,
        "token": token,
        "refresh_token": token,
        "expires_in": 3600,
        "token_type": "Bearer",
        "did": did,
        "user_id": did,
        "refreshed": refreshed,
        "provider": "did_verify_dev",
    }


def did_verify_send_code(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = str(params.get("did") or "").strip()
    if not did:
        raise InvalidParams("did_required")
    if not did.startswith("did:"):
        raise InvalidParams("valid_did_required")
    settings = get_settings(request)
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
    if code != settings.did_verify_dev_code:
        raise Unauthorized("invalid_code")
    row = _did_verify_user_row(did, request)
    if not row:
        raise Unauthorized("did_not_found")
    if not row["document_json"]:
        raise Unauthorized("did_document_not_found")
    return _did_verify_token_result(did=did, token=str(row["token"]))


def did_verify_refresh(params: dict[str, Any], request: Request) -> dict[str, Any]:
    refresh_token = str(params.get("refresh_token") or "").strip()
    if not refresh_token:
        raise InvalidParams("refresh_token_required")
    did = did_for_token(request, refresh_token)
    if not did:
        raise Unauthorized("invalid_refresh_token")
    row = _did_verify_user_row(did, request)
    if not row or not row["document_json"]:
        raise Unauthorized("did_document_not_found")
    return _did_verify_token_result(did=did, token=refresh_token, refreshed=True)


def get_me(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    return public_profile({"did": did}, request)


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
    did = params.get("did") or params.get("user_id")
    handle = params.get("handle")
    with get_store(request).connect() as conn:
        if did:
            row = conn.execute("SELECT * FROM profiles WHERE did = ?", (did,)).fetchone()
        elif handle:
            row = conn.execute("SELECT * FROM profiles WHERE handle = ?", (handle,)).fetchone()
        else:
            raise InvalidParams("did_or_handle_required")
    if not row:
        raise NotFound("profile_not_found")
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
    local, domain, _, _ = _split_handle(str(profile["handle"]), settings.did_domain)
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
        raise NotFound("did_document_not_found")
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
        raise NotFound("handle_not_found")
    profile = dict(row)
    local, domain, _, full = _split_handle(profile["handle"], settings.did_domain)
    return {
        "did": profile["did"],
        "user_id": profile["did"],
        "handle": local,
        "domain": domain,
        "full_handle": full,
        "status": "active",
        "profile": profile,
    }


def _handle_document_from_profile(profile: dict[str, Any], settings: Settings) -> dict[str, Any]:
    local, domain, _, full = _split_handle(profile["handle"], settings.did_domain)
    updated = now_iso()
    display_name = profile.get("display_name")
    description = profile.get("description")
    avatar_uri = profile.get("avatar_uri")
    profile_uri = profile.get("profile_uri") or f"https://{full}/"
    return {
        "handle": full,
        "did": profile["did"],
        "status": "active",
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
    if not row:
        raise NotFound("handle_not_found")
    return _handle_document_from_profile(dict(row), settings)


def handle_confirmation_document(did: str, request: Request) -> dict[str, Any]:
    profile = _profile_from_did(request, did)
    return {
        "did": did,
        "confirmed": True,
        "status": "active",
        "updated": now_iso(),
        "handle": _handle_document_from_profile(profile, get_settings(request))["handle"],
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
        conn.execute(
            "UPDATE agent_registration_tokens SET used_at = ?, agent_did = ? WHERE token_hash = ?",
            (now_iso(), str(agent_did), row["token_hash"]),
        )
        if document:
            conn.execute(
                "INSERT OR REPLACE INTO did_documents(did, document_json, updated_at) VALUES (?, ?, ?)",
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
    if not settings.enable_contact_verification_compat:
        raise NotSupported(
            "contact_verification_not_enabled",
            data={
                "feature": "contact_verification",
                "reason": "email_or_phone_verification_is_not_part_of_open_server_mvp",
            },
        )
    phone = params.get("phone")
    if not phone:
        raise InvalidParams("phone_required")
    return {
        "ok": True,
        "sent": True,
        "message": "验证码已发送",
        "phone": phone,
        "provider": "dev",
        "dev_otp": settings.contact_verification_dev_otp,
    }


def content_create(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    body = params.get("body", "")
    title = params.get("title") or slug
    if not slug:
        raise InvalidParams("slug_required")
    page_id = new_id("page")
    with get_store(request).connect() as conn:
        conn.execute(
            "INSERT INTO content_pages(id, handle, slug, title, body, visibility, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (page_id, profile["handle"], slug, title, body, params.get("visibility", "public"), now_iso()),
        )
    return content_get({"slug": slug, "handle": profile["handle"]}, request)


def content_get(params: dict[str, Any], request: Request) -> dict[str, Any]:
    handle = params.get("handle")
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    with get_store(request).connect() as conn:
        if handle:
            row = conn.execute("SELECT * FROM content_pages WHERE handle = ? AND slug = ?", (handle, slug)).fetchone()
        else:
            row = conn.execute("SELECT * FROM content_pages WHERE slug = ? ORDER BY updated_at DESC LIMIT 1", (slug,)).fetchone()
    if not row:
        raise NotFound("page_not_found")
    return dict(row)


def content_list(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    with get_store(request).connect() as conn:
        rows = conn.execute("SELECT id, handle, slug, title, visibility, updated_at FROM content_pages WHERE handle = ? ORDER BY updated_at DESC", (profile["handle"],)).fetchall()
    pages = [dict(row) for row in rows]
    return {"pages": pages, "count": len(pages), "has_more": False}


def content_update(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    allowed = {k: params[k] for k in ["title", "body", "visibility"] if k in params}
    if not allowed:
        return content_get(params, request)
    with get_store(request).connect() as conn:
        for field, value in allowed.items():
            conn.execute(
                f"UPDATE content_pages SET {field} = ?, updated_at = ? WHERE handle = ? AND slug = ?",
                (value, now_iso(), profile["handle"], slug),
            )
    return content_get({"handle": profile["handle"], "slug": slug}, request)


def content_rename(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug") or params.get("old_slug")
    new_slug = params.get("new_slug")
    if not slug or not new_slug:
        raise InvalidParams("slug_and_new_slug_required")
    with get_store(request).connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM content_pages WHERE handle = ? AND slug = ?",
            (profile["handle"], new_slug),
        ).fetchone()
        if existing:
            raise Conflict("slug_already_exists")
        cursor = conn.execute(
            "UPDATE content_pages SET slug = ?, updated_at = ? WHERE handle = ? AND slug = ?",
            (new_slug, now_iso(), profile["handle"], slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("page_not_found")
    return content_get({"handle": profile["handle"], "slug": new_slug}, request)


def content_delete(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    with get_store(request).connect() as conn:
        conn.execute("DELETE FROM content_pages WHERE handle = ? AND slug = ?", (profile["handle"], slug))
    return {"deleted": True, "slug": slug}


def _relationship_target(params: dict[str, Any], request: Request) -> str:
    settings = get_settings(request)
    target_did = str(params.get("target_did") or "").strip()
    if not target_did:
        raise InvalidParams("target_did_required")
    target_did = urllib.parse.unquote(target_did)
    if not _did_belongs_to_domain(target_did, settings.did_domain):
        raise InvalidParams("target_did_domain_mismatch")
    with get_store(request).connect() as conn:
        if not _user_exists(conn, target_did):
            raise NotFound("target_did_not_found")
    return target_did


def did_relationship_follow(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    if actor == target:
        raise InvalidParams("cannot_follow_self")
    now = now_iso()
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        conn.execute(
            "INSERT OR IGNORE INTO did_relationships(from_did, to_did, created_at) VALUES (?, ?, ?)",
            (actor, target, now),
        )
        reciprocal = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (target, actor),
        ).fetchone()
    return {"is_friend": reciprocal is not None}


def did_relationship_unfollow(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        conn.execute("DELETE FROM did_relationships WHERE from_did = ? AND to_did = ?", (actor, target))
    return {"ok": True}


def _relationship_item(row: Any) -> dict[str, Any]:
    return {
        "from_did": row["from_did"],
        "to_did": row["to_did"],
        "from_user_id": row["from_did"],
        "to_user_id": row["to_did"],
        "created_at": row["created_at"],
    }


def did_relationship_following(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    limit = max(1, min(int(params.get("limit", 50) or 50), 100))
    offset = max(0, int(params.get("offset", 0) or 0))
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        rows = conn.execute(
            """
            SELECT from_did, to_did, created_at FROM did_relationships
            WHERE from_did = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (actor, limit, offset),
        ).fetchall()
    return {"items": [_relationship_item(row) for row in rows], "count": len(rows), "has_more": len(rows) >= limit}


def did_relationship_followers(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    limit = max(1, min(int(params.get("limit", 50) or 50), 100))
    offset = max(0, int(params.get("offset", 0) or 0))
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        rows = conn.execute(
            """
            SELECT from_did, to_did, created_at FROM did_relationships
            WHERE to_did = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (actor, limit, offset),
        ).fetchall()
    return {"items": [_relationship_item(row) for row in rows], "count": len(rows), "has_more": len(rows) >= limit}


def did_relationship_status(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        following = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (actor, target),
        ).fetchone()
        follower = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (target, actor),
        ).fetchone()
    is_following = following is not None
    is_follower = follower is not None
    return {
        "is_following": is_following,
        "is_follower": is_follower,
        "is_friend": is_following and is_follower,
        "is_blocked": False,
        "is_blocked_by": False,
    }


def _site_url(domain: str, page_kind: str, slug: str) -> str:
    if page_kind == "root":
        return f"https://{domain}/"
    return f"https://{domain}/pages/{slug}.md"


def _site_page_view(row: Any, *, include_body: bool = True) -> dict[str, Any]:
    data = dict(row)
    result = {
        "domain": data["domain"],
        "kind": data["page_kind"],
        "slug": data["slug"],
        "url": _site_url(data["domain"], data["page_kind"], data["slug"]),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }
    if include_body:
        result["body"] = data["body"]
    return result


def _ensure_site_root(request: Request, domain: str) -> dict[str, Any]:
    now = now_iso()
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
        if row:
            return dict(row)
        body = f"# {domain}\n\nWelcome to {domain}."
        conn.execute(
            """
            INSERT INTO site_pages(domain, page_kind, slug, body, created_at, updated_at)
            VALUES (?, 'root', '', ?, ?, ?)
            """,
            (domain, body, now, now),
        )
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
    return dict(row)


def _site_require_domain_admin(request: Request, domain: str) -> str:
    did = current_did(request)
    settings = get_settings(request)
    if domain != settings.did_domain:
        raise Unauthorized("site_domain_not_managed_by_this_server")
    return did


def site_get_root(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    return _site_page_view(_ensure_site_root(request, domain))


def site_set_root(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    now = now_iso()
    _ensure_site_root(request, domain)
    with get_store(request).connect() as conn:
        conn.execute(
            """
            UPDATE site_pages SET body = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'root' AND slug = ''
            """,
            (body, now, domain),
        )
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
    return _site_page_view(row)


def site_list_pages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM site_pages
            WHERE domain = ? AND page_kind = 'page'
            ORDER BY slug ASC
            """,
            (domain,),
        ).fetchall()
    return {"domain": domain, "pages": [_site_page_view(row, include_body=False) for row in rows], "count": len(rows)}


def site_get_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        ).fetchone()
    if not row:
        raise NotFound("site_page_not_found")
    return _site_page_view(row)


def site_create_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    now = now_iso()
    try:
        with get_store(request).connect() as conn:
            conn.execute(
                """
                INSERT INTO site_pages(domain, page_kind, slug, body, created_at, updated_at)
                VALUES (?, 'page', ?, ?, ?, ?)
                """,
                (domain, slug, body, now, now),
            )
            row = conn.execute(
                "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
                (domain, slug),
            ).fetchone()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise Conflict("site_page_slug_exists") from exc
        raise
    return _site_page_view(row)


def site_update_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    with get_store(request).connect() as conn:
        cursor = conn.execute(
            """
            UPDATE site_pages SET body = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'page' AND slug = ?
            """,
            (body, now_iso(), domain, slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("site_page_not_found")
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        ).fetchone()
    return _site_page_view(row)


def site_rename_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    old_slug = _normalize_site_slug(params.get("old_slug"))
    new_slug = _normalize_site_slug(params.get("new_slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        if old_slug != new_slug:
            existing = conn.execute(
                "SELECT 1 FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
                (domain, new_slug),
            ).fetchone()
            if existing:
                raise Conflict("site_page_slug_exists")
        cursor = conn.execute(
            """
            UPDATE site_pages SET slug = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'page' AND slug = ?
            """,
            (new_slug, now_iso(), domain, old_slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("site_page_not_found")
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, new_slug),
        ).fetchone()
    return _site_page_view(row)


def site_delete_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        cursor = conn.execute(
            "DELETE FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        )
    if cursor.rowcount == 0:
        raise NotFound("site_page_not_found")
    return {"ok": True, "domain": domain, "slug": slug}


def site_public_root(request: Request, domain: str | None = None) -> str:
    settings = get_settings(request)
    normalized = _normalize_domain(domain or settings.did_domain)
    if normalized != settings.did_domain:
        raise NotFound("site_domain_not_found")
    return str(_ensure_site_root(request, normalized)["body"])


def site_public_page(slug: str, request: Request, domain: str | None = None) -> str:
    settings = get_settings(request)
    normalized = _normalize_domain(domain or settings.did_domain)
    if normalized != settings.did_domain:
        raise NotFound("site_domain_not_found")
    normalized_slug = _normalize_site_slug(slug)
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT body FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (normalized, normalized_slug),
        ).fetchone()
    if not row:
        raise NotFound("site_page_not_found")
    return str(row["body"])


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


def add_sync_event(conn, owner_did: str, event_type: str, payload: dict[str, Any]) -> int:
    row = conn.execute("SELECT COALESCE(MAX(event_seq), 0) + 1 AS seq FROM sync_events WHERE owner_did = ?", (owner_did,)).fetchone()
    seq = int(row["seq"])
    conn.execute(
        "INSERT INTO sync_events(event_id, owner_did, event_seq, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_id("sev"), owner_did, seq, event_type, _json(payload), now_iso()),
    )
    return seq


def _publish_realtime(request: Request, owner_did: str, method: str, params: dict[str, Any], sync: dict[str, Any] | None = None) -> None:
    hub = getattr(request.app.state, "realtime_hub", None)
    if hub is None:
        return
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if sync:
        payload["sync"] = sync
    hub.publish(owner_did, payload)


def _user_exists(conn, did: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM users u
        JOIN did_documents d ON d.did = u.did
        WHERE u.did = ?
          AND u.revoked_at IS NULL
          AND d.status = 'active'
          AND d.revoked_at IS NULL
        """,
        (did,),
    ).fetchone()
    return row is not None


def _store_direct_message(
    request: Request,
    *,
    sender: str,
    recipient: str,
    body: dict[str, Any],
    content_type: str,
    message_id: str,
    operation_id: str | None,
    sender_local: bool,
    recipient_local: bool,
    delivery_state: str = "accepted",
    final_acceptance: bool = True,
) -> dict[str, Any]:
    recipient_event_seq: int | None = None
    with get_store(request).connect() as conn:
        seq = conn.execute("SELECT COALESCE(MAX(server_seq), 0) + 1 AS seq FROM direct_messages").fetchone()["seq"]
        conn.execute(
            "INSERT INTO direct_messages(message_id, sender_did, recipient_did, body_json, content_type, created_at, server_seq) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, sender, recipient, _json(body), content_type, now_iso(), seq),
        )
        if sender_local:
            conn.execute("INSERT OR IGNORE INTO direct_message_views(owner_did, message_id, peer_did) VALUES (?, ?, ?)", (sender, message_id, recipient))
            add_sync_event(conn, sender, "direct.message.created", {"message_id": message_id, "peer_did": recipient, "server_seq": seq})
        if recipient_local:
            conn.execute("INSERT OR IGNORE INTO direct_message_views(owner_did, message_id, peer_did) VALUES (?, ?, ?)", (recipient, message_id, sender))
            recipient_event_seq = add_sync_event(conn, recipient, "direct.message.created", {"message_id": message_id, "peer_did": sender, "server_seq": seq})
    accepted_at = now_iso()
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
                "server_seq": str(seq),
            },
        )
    return result


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
    operation_id = params.get("operation_id") or new_id("op")
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
                operation_id=operation_id,
                recipient_local=True,
            )
        return _store_direct_message(
            request,
            sender=sender,
            recipient=recipient,
            body=proof_body,
            content_type=content_type,
            message_id=message_id,
            operation_id=operation_id,
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
                operation_id=operation_id,
                recipient_local=True,
            )
        return _store_direct_message(
            request,
            sender=sender,
            recipient=recipient,
            body=body,
            content_type=content_type,
            message_id=message_id,
            operation_id=operation_id,
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
    remote = _send_remote_direct(
        settings,
        sender=sender,
        recipient=recipient,
        body=proof_body,
        content_type=content_type,
        message_id=message_id,
        operation_id=operation_id,
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
        operation_id=operation_id,
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
    accepted_at = now_iso()
    member_events: list[tuple[str, int]] = []
    with get_store(request).connect() as conn:
        member = conn.execute("SELECT 1 FROM group_members WHERE group_did = ? AND member_did = ?", (group_did, sender)).fetchone()
        if not member:
            raise Unauthorized("not_group_member")
        seq = conn.execute("SELECT COALESCE(MAX(server_seq), 0) + 1 AS seq FROM group_messages").fetchone()["seq"]
        message_id = params.get("message_id") or new_id("gmsg")
        conn.execute(
            "INSERT INTO group_messages(message_id, group_did, sender_did, body_json, content_type, created_at, server_seq) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, group_did, sender, _json(body), content_type, now_iso(), seq),
        )
        members = conn.execute("SELECT member_did FROM group_members WHERE group_did = ?", (group_did,)).fetchall()
        for member_row in members:
            event_seq = add_sync_event(
                conn,
                member_row["member_did"],
                "group.message.created",
                {"message_id": message_id, "group_did": group_did, "server_seq": seq},
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
                    "created_at": accepted_at,
                }
            },
            {
                "owner_did": owner_did,
                "event_type": "group.message.created",
                "event_seq": str(event_seq),
                "server_seq": str(seq),
            },
        )
    return {
        "accepted": True,
        "delivery_state": "accepted",
        "final_acceptance": True,
        "message_id": message_id,
        "operation_id": params.get("operation_id") or meta.get("operation_id"),
        "group_did": group_did,
        "sender_did": sender,
        "server_seq": seq,
        "group_event_seq": str(seq),
        "group_state_version": str(seq),
        "accepted_at": accepted_at,
        "content_type": content_type,
        "body": body,
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
    advanced = saved_seq > previous_seq
    warnings = [] if advanced or seq == previous_seq else ["read_state.watermark_not_advanced"]
    return {
        "user_did": owner,
        "owner_did": owner,
        "thread": thread,
        "thread_id": thread_id,
        "updated_count": 1 if advanced else 0,
        "remote_acknowledged": True,
        "partial": False,
        "fallback_used": False,
        "pending_remote_ack": False,
        "read_watermark_server_seq": str(saved_seq),
        "previous_read_watermark_server_seq": str(previous_seq) if previous else None,
        "read_watermark_message_id": read_message_id,
        "advanced": advanced,
        "read_at": read_at,
        "unread_count": 0,
        "warnings": warnings,
        "read_up_to_seq": saved_seq,
    }


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
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    with get_store(request).connect() as conn:
        conn.execute(
            "INSERT INTO attachment_slots(slot_id, object_id, attachment_id, object_uri, owner_did, upload_token, commit_token, path, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slot_id, object_id, attachment_id, object_uri, owner, upload_token, commit_token, str(path), "open", now_iso()),
        )
    return {
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


async def upload_slot(slot_id: str, token: str, data: bytes, request: Request) -> dict[str, Any]:
    with get_store(request).connect() as conn:
        row = conn.execute("SELECT * FROM attachment_slots WHERE slot_id = ? AND upload_token = ?", (slot_id, token)).fetchone()
        if not row:
            raise NotFound("slot_not_found")
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
        path = Path(row["path"])
        if not path.exists():
            raise InvalidParams("object_not_uploaded")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        final = path.with_suffix(".bin")
        shutil.move(str(path), str(final))
        object_uri = row["object_uri"] or _object_download_uri(get_settings(request), str(row["object_id"]))
        attachment_id = row["attachment_id"] or params.get("attachment_id")
        conn.execute(
            "INSERT INTO attachment_objects(object_id, source_attachment_id, object_uri, owner_did, path, size, sha256, content_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["object_id"], attachment_id, object_uri, row["owner_did"], str(final), len(data), digest, params.get("content_type", "application/octet-stream"), now_iso()),
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


def sync_delta(params: dict[str, Any], request: Request) -> dict[str, Any]:
    owner = current_did(request)
    user_did = params.get("user_did")
    if user_did and user_did != owner:
        raise Unauthorized("user_did_mismatch")
    after = int(params.get("since_event_seq", params.get("after_event_seq", params.get("after", 0))) or 0)
    limit = int(params.get("limit", 100))
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
            (owner, after, limit),
        ).fetchall()
    events = []
    for row in rows:
        payload = _load(row["payload_json"])
        aggregate_id = payload.get("message_id") or payload.get("group_did") or payload.get("thread_id") or row["event_id"]
        aggregate_kind = "group_message" if str(row["event_type"]).startswith("group.") else "direct_message"
        if str(row["event_type"]).startswith("read_state."):
            aggregate_kind = "read_state"
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
        "has_more": len(events) >= limit,
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
                (group_did, after, limit),
            ).fetchall()
            messages = [_group_message_result(row) for row in rows]
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
                (owner, peer, after, limit),
            ).fetchall()
            messages = [_direct_message_result(row, owner) for row in rows]
    next_seq = messages[-1]["server_seq"] if messages else after
    return {
        "thread_id": thread_id,
        "thread": thread,
        "messages": messages,
        "next_server_seq": next_seq,
        "next_after_server_seq": str(next_seq),
        "has_more": len(messages) >= limit,
        "warnings": [],
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
    "lookup": handle_lookup,
    "send_otp": send_otp,
    "get_my_handle": get_my_handle,
    "get_my_handles": get_my_handles,
    "get_quota": get_quota,
    "request_revoke": not_supported,
    "confirm_revoke": not_supported,
    "update_wallet": not_supported,
}

CONTENT_HANDLERS = {
    "create": content_create,
    "get": content_get,
    "list": content_list,
    "update": content_update,
    "rename": content_rename,
    "delete": content_delete,
}

DID_RELATIONSHIP_HANDLERS = {
    "follow": did_relationship_follow,
    "unfollow": did_relationship_unfollow,
    "get_following": did_relationship_following,
    "get_followers": did_relationship_followers,
    "get_status": did_relationship_status,
}

USERS_HANDLERS = {
    "get_me": users_get_me,
    "get_by_did": users_get_by_did,
    "get_by_dids": users_get_by_dids,
    "get_by_handle": users_get_by_handle,
}

SITE_HANDLERS = {
    "get_root": site_get_root,
    "set_root": site_set_root,
    "list_pages": site_list_pages,
    "get_page": site_get_page,
    "create_page": site_create_page,
    "update_page": site_update_page,
    "rename_page": site_rename_page,
    "delete_page": site_delete_page,
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
    "attachment.create_slot": attachment_create_slot,
    "attachment.commit_object": attachment_commit,
    "attachment.abort_object": attachment_abort,
    "attachment.get_download_ticket": attachment_ticket,
    "direct.e2ee.publish_prekey_bundle": not_supported,
    "direct.e2ee.get_prekey_bundle": not_supported,
    "group.e2ee.publish_key_package": not_supported,
    "group.create": not_supported,
    "group.add": not_supported,
    "group.remove": not_supported,
    "group.update_profile": not_supported,
    "group.update_policy": not_supported,
}
