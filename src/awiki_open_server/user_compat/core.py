from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any

from fastapi import Request

from awiki_open_server.app.settings import Settings
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


def register(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    raw_handle = params.get("handle") or f"user-{new_id('h')[2:8]}"
    local_handle, domain, stored_handle, full_handle = _split_handle(str(raw_handle), settings.did_domain)
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
            """
            INSERT INTO profiles(
                did, handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                did,
                stored_handle,
                display_name,
                params.get("avatar_uri"),
                params.get("profile_uri"),
                params.get("description"),
                "human",
                params.get("profile_md"),
            ),
        )
        conn.execute(
            """
            INSERT INTO did_documents(did, document_json, updated_at, status, revoked_at)
            VALUES (?, ?, ?, 'active', NULL)
            """,
            (did, _json(doc), now_iso()),
        )
    return {
        "did": did,
        "user_id": did,
        "message": "Registration successful",
        "handle": local_handle,
        "domain": domain,
        "full_handle": full_handle,
        "token": token,
        "access_token": token,
        "document": doc,
    }


def recover_handle(params: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    raw_handle = params.get("handle")
    if not isinstance(raw_handle, str) or not raw_handle.strip():
        raise InvalidParams("handle_required")
    local_handle, domain, stored_handle, full_handle = _split_handle(
        raw_handle,
        settings.did_domain,
    )
    uploaded_doc = params.get("did_document") if isinstance(params.get("did_document"), dict) else None
    did = params.get("did") or (uploaded_doc or {}).get("id")
    if not did:
        did = f"did:wba:{settings.did_domain}:users:{local_handle}"
    did = str(did)
    token = new_id("tok")
    now = now_iso()
    doc = _ensure_anp_message_service(uploaded_doc or did_document(settings, did, stored_handle), settings, did)
    doc["id"] = did

    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT u.did, u.handle, u.created_at,
                   p.display_name, p.avatar_uri, p.profile_uri, p.description, p.subject_type, p.profile_md
            FROM users u
            JOIN profiles p ON p.did = u.did
            LEFT JOIN did_documents d ON d.did = u.did
            WHERE u.handle = ?
              AND u.revoked_at IS NULL
              AND COALESCE(d.status, 'active') = 'active'
              AND d.revoked_at IS NULL
            """,
            (stored_handle,),
        ).fetchone()
        if not row:
            raise NotFound("handle_not_found")

        old_did = str(row["did"])
        did_owner = conn.execute("SELECT did, handle FROM users WHERE did = ?", (did,)).fetchone()
        if did_owner and old_did != did:
            raise Conflict("did_already_registered")

        display_name = params.get("display_name") or row["display_name"] or local_handle
        avatar_uri = params.get("avatar_uri") if "avatar_uri" in params else row["avatar_uri"]
        profile_uri = params.get("profile_uri") if "profile_uri" in params else row["profile_uri"]
        description = params.get("description") if "description" in params else row["description"]
        subject_type = params.get("subject_type") or row["subject_type"] or "human"
        profile_md = params.get("profile_md") if "profile_md" in params else row["profile_md"]

        if old_did == did:
            conn.execute(
                "UPDATE users SET token = ?, handle = ?, revoked_at = NULL WHERE did = ?",
                (token, stored_handle, did),
            )
            conn.execute(
                """
                UPDATE profiles
                SET handle = ?, display_name = ?, avatar_uri = ?, profile_uri = ?, description = ?,
                    subject_type = ?, profile_md = ?
                WHERE did = ?
                """,
                (stored_handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md, did),
            )
        else:
            archived_handle = f"{local_handle}+recovered-{_sha256_hex(old_did)[:12]}@{domain}"
            conn.execute("UPDATE users SET handle = ?, revoked_at = ? WHERE did = ?", (archived_handle, now, old_did))
            conn.execute("UPDATE profiles SET handle = ? WHERE did = ?", (archived_handle, old_did))
            conn.execute(
                """
                UPDATE did_documents
                SET status = 'revoked', revoked_at = ?, updated_at = ?
                WHERE did = ?
                """,
                (now, now, old_did),
            )
            conn.execute(
                "INSERT INTO users(did, handle, token, created_at) VALUES (?, ?, ?, ?)",
                (did, stored_handle, token, now),
            )
            conn.execute(
                """
                INSERT INTO profiles(
                    did, handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (did, stored_handle, display_name, avatar_uri, profile_uri, description, subject_type, profile_md),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO did_documents(did, document_json, updated_at, status, revoked_at)
            VALUES (?, ?, ?, 'active', NULL)
            """,
            (did, _json(doc), now),
        )

    return {
        "did": did,
        "user_id": did,
        "message": "Recovery successful",
        "handle": local_handle,
        "domain": domain,
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
    settings = get_settings(request)
    did = params.get("did") or params.get("user_id")
    handle = params.get("handle")
    with get_store(request).connect() as conn:
        if did:
            row = conn.execute("SELECT * FROM profiles WHERE did = ?", (did,)).fetchone()
        elif handle:
            _, _, stored_handle, _ = _split_handle(str(handle), settings.did_domain)
            row = conn.execute("SELECT * FROM profiles WHERE handle = ?", (stored_handle,)).fetchone()
        else:
            raise InvalidParams("did_or_handle_required")
    if not row:
        if handle:
            from awiki_open_server.user_compat.wns import resolve_handle_anywhere

            resolution = resolve_handle_anywhere(str(handle), request)
            return resolution.public_profile_view(settings)
        if did:
            from awiki_open_server.user_compat.wns import resolve_did_anywhere

            resolved = resolve_did_anywhere(str(did), request)
            display_name = str(resolved["did"]).split(":")[-1]
            domain = str(resolved["did"]).split(":")[2] if str(resolved["did"]).startswith("did:wba:") else None
            return {
                "did": resolved["did"],
                "user_id": resolved["did"],
                "user_name": display_name,
                "nick_name": display_name,
                "nickName": display_name,
                "display_name": display_name,
                "avatar_url": None,
                "avatarUrl": None,
                "avatar_uri": None,
                "bio": None,
                "description": None,
                "profile_md": None,
                "profile_url": None,
                "profileUrl": None,
                "profile_uri": None,
                "handle": None,
                "domain": domain,
                "subject_type": "unknown",
                "status": "active",
                "service_endpoints": resolved["service_endpoints"],
                "did_document": resolved["document"],
                "verification_level": resolved["verification_level"],
                "resolver_source": resolved["resolver_source"],
                "warnings": resolved["warnings"],
            }
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
        from awiki_open_server.user_compat.wns import resolve_handle_anywhere

        return resolve_handle_anywhere(str(handle), request).public_profile_view(settings)
    return _users_profile_view(dict(row), request)


def resolve_profile(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = params.get("did")
    if not did:
        raise InvalidParams("did_required")
    from awiki_open_server.user_compat.wns import resolve_did_anywhere

    resolved = resolve_did_anywhere(str(did), request)
    return {
        "did": resolved["did"],
        "document": resolved["document"],
        "service_endpoints": resolved["service_endpoints"],
        "verification_level": resolved["verification_level"],
        "resolver_source": resolved["resolver_source"],
        "warnings": resolved["warnings"],
    }


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
        if handle:
            from awiki_open_server.user_compat.wns import resolve_handle_anywhere

            return resolve_handle_anywhere(str(handle), request).lookup_view()
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


IDENTITY_HANDLERS = {
    "register": register,
    "update_document": update_document,
    "verify": verify,
    "verify_http_request": verify_http_request,
    "get_me": get_me,
    "revoke": revoke,
    "replace_did": not_supported,
    "recover_handle": recover_handle,
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
