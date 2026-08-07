from __future__ import annotations

import ipaddress
import json
import socket
from threading import Lock
import time
import uuid
from typing import Any
import urllib.parse
import urllib.request

from fastapi import Request

from awiki_open_server.app.settings import Settings
from awiki_open_server.protocol.anp_adapter import AnpProtocolError, signature_keyid
from awiki_open_server.service_identity import require_signed_peer_request, verify_peer_http_signature
from awiki_open_server.shared.errors import InvalidParams, NotFound, Unauthorized
from awiki_open_server.shared.ids import now_iso, new_id
from awiki_open_server.user_compat.core import get_settings, get_store


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load(raw: str) -> Any:
    return json.loads(raw)


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


_MAX_DISCOVERY_RESPONSE_BYTES = 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)
_DISCOVERY_CACHE_TTL_SECONDS = 60
_DISCOVERY_CACHE_LOCK = Lock()
_DISCOVERY_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _read_bounded(response: Any, *, limit: int = _MAX_DISCOVERY_RESPONSE_BYTES) -> bytes:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise InvalidParams("remote_response_too_large", data={"max_bytes": limit})
    return raw


def _validate_outbound_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise InvalidParams("outbound_url_userinfo_not_allowed")
    if parsed.scheme not in ({"http", "https"} if allow_private else {"https"}):
        raise InvalidParams("outbound_url_scheme_not_allowed")
    hostname = parsed.hostname
    if not hostname:
        raise InvalidParams("outbound_url_host_required")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise InvalidParams("outbound_url_host_unresolvable", data={"host": hostname}) from exc
    if not allow_private:
        for address in addresses:
            if not address.is_global:
                raise InvalidParams("outbound_url_private_address_not_allowed", data={"host": hostname})


def _http_get_json(url: str, *, allow_private: bool = False) -> dict[str, Any]:
    _validate_outbound_url(url, allow_private=allow_private)
    with _NO_REDIRECT_OPENER.open(url, timeout=15) as response:
        _validate_outbound_url(response.geturl(), allow_private=allow_private)
        data = json.loads(_read_bounded(response).decode())
    if not isinstance(data, dict):
        raise InvalidParams("did_document_must_be_object")
    return data


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, body_bytes: bytes | None = None) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidParams("outbound_url_invalid")
    body = body_bytes or json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with _NO_REDIRECT_OPENER.open(request, timeout=15) as response:
        raw = _read_bounded(response)
        if not raw:
            return {}
        data = json.loads(raw.decode())
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


def _fetch_did_document(did: str, settings: Settings) -> dict[str, Any]:
    domain = _did_domain(did)
    resolver_map = settings.did_resolver_base_urls or {}
    allow_private = domain in resolver_map
    url = _did_document_url(did, resolver_map)
    if allow_private:
        return _http_get_json(url, allow_private=True)
    return _http_get_json(url)


def _discover_anp_service(did: str, settings: Settings) -> dict[str, Any]:
    cache_key = (str(settings.db_path), did)
    with _DISCOVERY_CACHE_LOCK:
        cached = _DISCOVERY_CACHE.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return dict(cached[1])
    try:
        document = _fetch_did_document(did, settings)
    except Exception as exc:
        if isinstance(exc, (InvalidParams, NotFound)):
            raise
        raise NotFound("did_document_not_found", data={"did": did, "detail": str(exc)}) from exc
    if document.get("id") not in (None, did):
        raise InvalidParams("did_document_id_mismatch", data={"did": did, "document_id": document.get("id")})
    service = _anp_message_service(document)
    endpoint = str(service["serviceEndpoint"])
    allow_private = _did_domain(did) in (settings.did_resolver_base_urls or {})
    _validate_outbound_url(endpoint, allow_private=allow_private)
    capabilities_request = {
        "jsonrpc": "2.0",
        "method": "anp.get_capabilities",
        "params": {
            "meta": {
                "profile": "anp.core.binding.v1",
                "security_profile": "transport-protected",
                "operation_id": f"discover-{uuid.uuid4().hex}",
            },
            "body": {},
        },
        "id": f"discover-{uuid.uuid4().hex}",
    }
    try:
        capabilities_response = _http_post_json(endpoint, capabilities_request)
    except Exception as exc:
        if isinstance(exc, (InvalidParams, NotFound)):
            raise
        raise NotFound("anp_runtime_capabilities_unavailable", data={"did": did, "detail": str(exc)}) from exc
    capabilities = capabilities_response.get("result") if isinstance(capabilities_response, dict) else None
    if not isinstance(capabilities, dict):
        raise InvalidParams("anp_runtime_capabilities_required", data={"did": did})
    runtime_service_did = capabilities.get("service_did")
    if runtime_service_did != service.get("serviceDid"):
        raise InvalidParams(
            "anp_runtime_service_did_mismatch",
            data={"static": service.get("serviceDid"), "runtime": runtime_service_did},
        )
    static_profiles = service.get("profiles")
    runtime_profiles = capabilities.get("profiles") or capabilities.get("supported_profiles")
    if not isinstance(static_profiles, list) or not isinstance(runtime_profiles, list):
        raise InvalidParams("anp_runtime_profiles_required", data={"did": did})
    normalized = dict(service)
    normalized["profiles"] = [profile for profile in static_profiles if profile in runtime_profiles]
    if not normalized["profiles"]:
        raise InvalidParams("anp_runtime_profiles_mismatch", data={"did": did})
    normalized["runtimeCapabilities"] = capabilities
    with _DISCOVERY_CACHE_LOCK:
        _DISCOVERY_CACHE[cache_key] = (time.monotonic() + _DISCOVERY_CACHE_TTL_SECONDS, dict(normalized))
    return normalized


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
        document = _fetch_did_document(did, get_settings(request))
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


def _verified_peer_service_did(request: Request) -> str | None:
    value = getattr(request.state, "peer_service_did", None)
    return value if isinstance(value, str) and value else None


def _verify_peer_request_signature(
    request: Request,
    settings: Settings,
    *,
    caller_anchor: str | None = None,
) -> None:
    headers = dict(request.headers)
    require_signed_peer_request(headers, allow_unsigned_dev=settings.allow_unsigned_peer_dev)
    if settings.allow_unsigned_peer_dev:
        request.state.peer_service_did = _source_service_did(headers)
        return
    try:
        service_did = signature_keyid(headers).split("#", 1)[0]
    except AnpProtocolError as exc:
        raise Unauthorized(exc.code, data={"detail": exc.detail}) from exc
    if caller_anchor:
        caller_service = _discover_anp_service(caller_anchor, settings)
        expected_service_did = caller_service.get("serviceDid")
        if service_did != expected_service_did:
            raise Unauthorized(
                "signature_service_did_caller_anchor_mismatch",
                data={"expected": expected_service_did, "actual": service_did},
            )
    document = _fetch_did_document(service_did, settings)
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
    request.state.peer_service_did = service_did


def _publish_realtime(request: Request, owner_did: str, method: str, params: dict[str, Any], sync: dict[str, Any] | None = None) -> None:
    hub = getattr(request.app.state, "realtime_hub", None)
    if hub is None:
        return
    message = params.get("message") if isinstance(params.get("message"), dict) else {}
    sender_did = message.get("sender_did") or params.get("member_did") or owner_did
    target_kind = "group" if method.startswith("group.") and params.get("group_did") else "agent"
    target_did = params.get("group_did") if target_kind == "group" else owner_did
    profile = "anp.group.local.v1" if method.startswith("group.") else "anp.direct.local.v1"
    meta: dict[str, Any] = {
        "profile": profile,
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "target": {"kind": target_kind, "did": target_did},
    }
    for field in ("operation_id", "message_id", "content_type"):
        value = message.get(field)
        if value is not None:
            meta[field] = value
    canonical_params = {**params, "meta": meta, "body": dict(params)}
    if sync:
        canonical_params["body"]["sync"] = dict(sync)
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": canonical_params}
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


def add_sync_event(conn, owner_did: str, event_type: str, payload: dict[str, Any]) -> int:
    row = conn.execute("SELECT COALESCE(MAX(event_seq), 0) + 1 AS seq FROM sync_events WHERE owner_did = ?", (owner_did,)).fetchone()
    seq = int(row["seq"])
    conn.execute(
        "INSERT INTO sync_events(event_id, owner_did, event_seq, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_id("sev"), owner_did, seq, event_type, _json(payload), now_iso()),
    )
    return seq


def _require_meta_string(meta: dict[str, Any], key: str, error_message: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidParams(error_message)
    return value
