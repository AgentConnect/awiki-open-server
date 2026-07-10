from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import urllib.parse

from fastapi import Request

from awiki_open_server.app.settings import Settings
from awiki_open_server.shared.http_client import OutboundHttpPolicy, allowed_hosts_from_base_urls, http_get_json_limited
from awiki_open_server.shared.errors import InvalidParams, NotFound
from awiki_open_server.shared.runtime import _did_document_url, _did_domain
from awiki_open_server.user_compat.core import _load, _split_handle, get_settings, get_store


MAX_WNS_RESPONSE_BYTES = 128 * 1024
MAX_DID_DOCUMENT_RESPONSE_BYTES = 256 * 1024
REMOTE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class WnsResolution:
    handle: str
    local: str
    domain: str
    stored_handle: str
    did: str
    status: str
    profile: dict[str, Any] | None
    did_document: dict[str, Any] | None
    service_endpoints: list[dict[str, Any]]
    verification_level: str
    resolver_source: str
    warnings: list[str]
    updated: str | None = None
    ttl: int | None = None
    version_id: str | None = None

    def lookup_view(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "handle": self.local,
            "did": self.did,
            "domain": self.domain,
            "status": self.status,
            "full_handle": self.handle,
            "user_id": self.did,
            "verification_level": self.verification_level,
            "resolver_source": self.resolver_source,
            "warnings": self.warnings,
        }
        if self.profile is not None:
            result["profile"] = self.profile
        if self.did_document is not None:
            result["did_document"] = self.did_document
        if self.service_endpoints:
            result["service_endpoints"] = self.service_endpoints
        if self.updated:
            result["updated"] = self.updated
        if self.ttl is not None:
            result["ttl"] = self.ttl
        if self.version_id:
            result["versionId"] = self.version_id
        return result

    def public_profile_view(self, settings: Settings) -> dict[str, Any]:
        profile = self.profile or {}
        display_name = _first_string(profile, ["display_name", "name"]) or self.local
        description = _first_string(profile, ["description", "bio"])
        avatar_uri = _first_string(profile, ["avatar_uri", "avatar_url", "avatarUrl"])
        profile_uri = _first_string(profile, ["profile_uri", "profile_url", "profileUrl"])
        subject_type = _first_string(profile, ["subject_type"]) or "unknown"
        return {
            "did": self.did,
            "user_id": self.did,
            "user_name": self.local,
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
            "profile_uri": profile_uri or f"{settings.public_base_url.rstrip('/')}/profiles/{self.did}",
            "handle": self.handle,
            "domain": self.domain,
            "subject_type": subject_type,
            "status": self.status,
            "service_endpoints": self.service_endpoints,
            "did_document": self.did_document or {},
            "verification_level": self.verification_level,
            "resolver_source": self.resolver_source,
            "warnings": self.warnings,
        }


def publish_local_handle(local_part: str, request: Request) -> dict[str, Any]:
    settings = get_settings(request)
    local = _normalize_local_part(local_part)
    stored_handle = f"{local}@{settings.did_domain}"
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT p.*, d.document_json
            FROM profiles p
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
        raise NotFound(
            "handle_not_found",
            data={
                "code": "handle_not_found",
                "resource": "handle",
                "handle": f"{local}.{settings.did_domain}",
            },
        )
    return local_handle_document(dict(row), settings)


def local_handle_document(profile: dict[str, Any], settings: Settings) -> dict[str, Any]:
    local, domain, _, full_handle = _split_handle(str(profile["handle"]), settings.did_domain)
    document: dict[str, Any] = {
        "handle": full_handle,
        "did": profile["did"],
        "status": "active",
        "profile": _profile_object_from_local(profile, full_handle),
    }
    return document


def resolve_handle_anywhere(handle: str, request: Request) -> WnsResolution:
    settings = get_settings(request)
    local, domain, stored_handle, full_handle = _split_handle(handle, settings.did_domain)
    local = _normalize_local_part(local)
    domain = _normalize_domain(domain)
    stored_handle = f"{local}@{domain}"
    full_handle = f"{local}.{domain}"

    local_resolution = _resolve_local_handle(stored_handle, full_handle, request)
    if local_resolution is not None:
        return local_resolution
    if domain == settings.did_domain.lower():
        raise NotFound(
            "handle_not_found",
            data={
                "code": "handle_not_found",
                "resource": "handle",
                "handle": full_handle,
            },
        )
    return _resolve_remote_handle(local, domain, full_handle, request)


def resolve_did_anywhere(did: str, request: Request) -> dict[str, Any]:
    did = str(did or "").strip()
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
    if row:
        document = _load(row["document_json"])
        if not isinstance(document, dict):
            raise InvalidParams("did_document_must_be_object")
        return {
            "did": did,
            "document": document,
            "service_endpoints": _anp_message_services(document),
            "resolver_source": "local",
            "verification_level": "local",
            "warnings": [],
        }
    settings = get_settings(request)
    if _did_domain(did) == settings.did_domain.lower():
        raise NotFound("did_document_not_found")
    document = _fetch_remote_did_document(did, settings)
    if document.get("id") != did:
        raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": document.get("id")})
    return {
        "did": did,
        "document": document,
        "service_endpoints": _anp_message_services(document),
        "resolver_source": "remote_did",
        "verification_level": "did_document",
        "warnings": [],
    }


def _resolve_local_handle(stored_handle: str, full_handle: str, request: Request) -> WnsResolution | None:
    settings = get_settings(request)
    with get_store(request).connect() as conn:
        row = conn.execute(
            """
            SELECT p.*, d.document_json
            FROM profiles p
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
        return None
    profile = dict(row)
    local, domain, _, _ = _split_handle(str(profile["handle"]), settings.did_domain)
    document = _load(profile["document_json"]) if profile.get("document_json") else {}
    return WnsResolution(
        handle=full_handle,
        local=local,
        domain=domain,
        stored_handle=stored_handle,
        did=str(profile["did"]),
        status="active",
        profile=_profile_object_from_local(profile, full_handle),
        did_document=document if isinstance(document, dict) else {},
        service_endpoints=_anp_message_services(document) if isinstance(document, dict) else [],
        verification_level="local",
        resolver_source="local",
        warnings=[],
    )


def _resolve_remote_handle(local: str, domain: str, full_handle: str, request: Request) -> WnsResolution:
    settings = get_settings(request)
    resolution_url = _wns_resolution_url(local, domain, settings)
    document = _http_get_json_limited(resolution_url, MAX_WNS_RESPONSE_BYTES, settings=settings)
    _validate_handle_resolution_document(document, full_handle)
    did = str(document["did"]).strip()
    if _did_domain(did) != domain:
        raise InvalidParams("handle_did_domain_mismatch", data={"handle": full_handle, "did": did})
    did_document = _fetch_remote_did_document(did, settings)
    if did_document.get("id") != did:
        raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": did_document.get("id")})
    services = _anp_message_services(did_document)
    if not services:
        raise NotFound("anp_message_service_not_found")
    verification_level, warnings = _verify_reverse_binding(
        full_handle=full_handle,
        did=did,
        did_document=did_document,
        settings=settings,
    )
    profile = document.get("profile") if isinstance(document.get("profile"), dict) else None
    if profile is not None:
        profile_warnings = _validate_profile_object(profile, full_handle=full_handle, did=did)
        if profile_warnings:
            warnings.extend(profile_warnings)
            profile = None
    return WnsResolution(
        handle=full_handle,
        local=local,
        domain=domain,
        stored_handle=f"{local}@{domain}",
        did=did,
        status=str(document.get("status") or "active"),
        profile=profile,
        did_document=did_document,
        service_endpoints=services,
        verification_level=verification_level,
        resolver_source="remote_wns",
        warnings=warnings,
        updated=_optional_string(document.get("updated")),
        ttl=_optional_int(document.get("ttl")),
        version_id=_optional_string(document.get("versionId") or document.get("version_id")),
    )


def _verify_reverse_binding(*, full_handle: str, did: str, did_document: dict[str, Any], settings: Settings) -> tuple[str, list[str]]:
    services = [
        service
        for service in did_document.get("service", [])
        if isinstance(service, dict) and service.get("type") == "ANPHandleService"
    ]
    if not services:
        return "forward_only", ["DID document does not declare ANPHandleService; using forward WNS resolution only"]
    warnings: list[str] = []
    local, domain, _, _ = _split_handle(full_handle, settings.did_domain)
    standard_url = _wns_resolution_url(local, domain, settings)
    for service in services:
        endpoint = service.get("serviceEndpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            warnings.append("Ignoring ANPHandleService without serviceEndpoint")
            continue
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "https" and (parsed.hostname or "").lower() not in _allowed_http_hosts(settings):
            warnings.append("Ignoring ANPHandleService endpoint without HTTPS")
            continue
        if parsed.hostname and parsed.hostname.lower() != domain:
            warnings.append("Ignoring ANPHandleService endpoint outside handle domain")
            continue
        try:
            confirmation = _http_get_json_limited(endpoint, MAX_WNS_RESPONSE_BYTES, settings=settings)
        except NotFound:
            warnings.append("ANPHandleService endpoint returned not found")
            continue
        if _urls_equivalent(endpoint, standard_url):
            if confirmation.get("did") == did and str(confirmation.get("handle") or "").lower() == full_handle:
                return "bidirectional_exact", warnings
            warnings.append("ANPHandleService exact endpoint did not confirm this handle")
            continue
        if confirmation.get("did") == did and confirmation.get("confirmed") is True:
            return "provider_confirmed", warnings
        warnings.append("ANPHandleService endpoint did not confirm this DID")
    return "forward_only", warnings or ["ANPHandleService reverse binding could not be verified"]


def _fetch_remote_did_document(did: str, settings: Settings) -> dict[str, Any]:
    url = _did_document_url(did, settings.did_resolver_base_urls)
    return _http_get_json_limited(url, MAX_DID_DOCUMENT_RESPONSE_BYTES, settings=settings)


def _wns_resolution_url(local: str, domain: str, settings: Settings) -> str:
    base_url = (settings.wns_resolver_base_urls or {}).get(domain.lower())
    local = urllib.parse.quote(local, safe="")
    if base_url:
        return f"{base_url.rstrip('/')}/.well-known/handle/{local}"
    return f"https://{domain}/.well-known/handle/{local}"


def _http_get_json_limited(url: str, max_bytes: int, *, settings: Settings | None = None) -> dict[str, Any]:
    return http_get_json_limited(
        url,
        max_bytes,
        policy=OutboundHttpPolicy(
            allowed_http_hosts=_allowed_http_hosts(settings),
            timeout_seconds=REMOTE_TIMEOUT_SECONDS,
            not_found_message="handle_not_found" if "/.well-known/handle/" in url else "did_document_not_found",
        ),
    )


def _allowed_http_hosts(settings: Settings | None) -> frozenset[str]:
    if settings is None:
        return frozenset()
    return allowed_hosts_from_base_urls(settings.wns_resolver_base_urls, settings.did_resolver_base_urls)


def _validate_handle_resolution_document(document: dict[str, Any], full_handle: str) -> None:
    handle = str(document.get("handle") or "").strip().lower()
    if handle != full_handle:
        raise InvalidParams("handle_resolution_mismatch", data={"expected": full_handle, "actual": document.get("handle")})
    did = str(document.get("did") or "").strip()
    if not did:
        raise InvalidParams("handle_resolution_did_required")
    status = str(document.get("status") or "active")
    if status != "active":
        raise NotFound("handle_not_active", data={"handle": full_handle, "status": status})


def _validate_profile_object(profile: dict[str, Any], *, full_handle: str, did: str) -> list[str]:
    warnings: list[str] = []
    subject = _first_string(profile, ["subject_did", "did", "subject", "id"])
    if subject and subject != did:
        warnings.append("Ignoring WNS profile because profile.subject_did does not match resolved did")
    handle = _first_string(profile, ["handle"])
    if handle and handle.lower() != full_handle:
        warnings.append("Ignoring WNS profile because profile.handle does not match resolved handle")
    return warnings


def _profile_object_from_local(profile: dict[str, Any], full_handle: str) -> dict[str, Any]:
    subject_type = profile.get("subject_type") or "human"
    if subject_type == "human":
        subject_type = "person"
    return {
        "type": "DIDSubjectProfile",
        "subject_did": profile["did"],
        "subject_type": subject_type,
        "handle": full_handle,
        "display_name": profile.get("display_name") or full_handle.split(".", 1)[0],
        "description": profile.get("description"),
        "avatar_uri": profile.get("avatar_uri"),
        "profile_uri": profile.get("profile_uri"),
        "updated": profile.get("updated_at"),
    }


def _anp_message_services(document: dict[str, Any]) -> list[dict[str, Any]]:
    services = document.get("service") if isinstance(document, dict) else None
    if not isinstance(services, list):
        return []
    return [
        service
        for service in services
        if isinstance(service, dict) and service.get("type") == "ANPMessageService"
    ]


def _normalize_local_part(value: str) -> str:
    local = str(value or "").strip().lower()
    if not local:
        raise InvalidParams("handle_required")
    if "/" in local or "@" in local or "." in local:
        raise InvalidParams("handle_local_part_invalid")
    return local


def _normalize_domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    if not domain or "/" in domain or "@" in domain or ":" in domain:
        raise InvalidParams("handle_domain_invalid")
    return domain


def _first_string(data: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _urls_equivalent(left: str, right: str) -> bool:
    l = urllib.parse.urlparse(left)
    r = urllib.parse.urlparse(right)
    return (
        l.scheme.lower(),
        (l.hostname or "").lower(),
        l.port,
        l.path.rstrip("/"),
        l.query,
    ) == (
        r.scheme.lower(),
        (r.hostname or "").lower(),
        r.port,
        r.path.rstrip("/"),
        r.query,
    )
