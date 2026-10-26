from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import importlib.util
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping


REQUIRED_ANP_SDK_VERSION = "1.0.7"


def _loaded_anp_version() -> str | None:
    source_version = _source_anp_version()
    if source_version:
        return source_version
    try:
        return metadata.version("anp")
    except metadata.PackageNotFoundError:
        return None


def _source_anp_version() -> str | None:
    spec = importlib.util.find_spec("anp")
    origin = getattr(spec, "origin", None)
    if not origin:
        return None
    try:
        tree = ast.parse(Path(origin).read_text(encoding="utf-8"))
    except OSError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


ANP_SDK_VERSION = _loaded_anp_version()
if ANP_SDK_VERSION != REQUIRED_ANP_SDK_VERSION:
    raise RuntimeError(
        f"ANP Python SDK {REQUIRED_ANP_SDK_VERSION} is required; loaded {ANP_SDK_VERSION or 'unknown'}"
    )

from anp.authentication import (  # noqa: E402
    build_group_message_service as _sdk_build_group_message_service,
    build_content_digest as _sdk_build_content_digest,
    create_did_wba_document as _sdk_create_did_wba_document,
    extract_signature_metadata as _sdk_extract_signature_metadata,
    generate_http_signature_headers as _sdk_generate_http_signature_headers,
    verify_http_message_signature as _sdk_verify_http_message_signature,
)
from anp.proof import generate_group_receipt_proof as _sdk_generate_group_receipt_proof  # noqa: E402
from anp.proof import verify_group_receipt_proof as _sdk_verify_group_receipt_proof  # noqa: E402
from anp.wns import (  # noqa: E402
    canonicalize_binding_generation as _sdk_canonicalize_binding_generation,
    compare_binding_generations as _sdk_compare_binding_generations,
    normalize_handle as _sdk_normalize_handle,
    validate_local_part as _sdk_validate_local_part,
    verify_handle_binding as _sdk_verify_handle_binding,
)
from anp.wns.models import HandleResolutionDocument as _SdkHandleResolutionDocument  # noqa: E402
from anp.proof.im import decode_im_signature as _sdk_decode_im_signature  # noqa: E402
from anp.proof.im import parse_im_signature_input as _sdk_parse_im_signature_input  # noqa: E402
from anp.proof.rfc9421_origin import (  # noqa: E402
    RFC9421_ORIGIN_PROOF_DEFAULT_COMPONENTS,
    RFC9421_ORIGIN_PROOF_DEFAULT_LABEL,
    Rfc9421OriginProofVerificationOptions,
    verify_rfc9421_origin_proof as _sdk_verify_origin_proof,
)
from anp.authentication.device_manifest import (  # noqa: E402
    build_vnext_did_document as _sdk_build_vnext_did_document,
    validate_device_manifest as _sdk_validate_device_manifest,
)
from anp.authentication.did_wba import validate_did_document_binding as _sdk_validate_did_document_binding  # noqa: E402
from anp.authentication.did_wba import compute_multikey_fingerprint as _sdk_compute_multikey_fingerprint  # noqa: E402
from anp.authentication.did_resolver import build_did_resolution_url as _sdk_build_did_resolution_url  # noqa: E402


class AnpProtocolError(ValueError):
    """Local error wrapper that keeps business layers independent of SDK details."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail or code


@dataclass(frozen=True)
class ServiceHttpSignatureVerification:
    keyid: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class OriginProofVerification:
    keyid: str
    verification_method: dict[str, Any]


@dataclass(frozen=True)
class SingleDeviceManifest:
    device_id: str
    signing_key_id: str
    root_key_id: str
    key_fingerprint: str


def require_did_document_binding(document: Mapping[str, Any]) -> None:
    try:
        valid = _sdk_validate_did_document_binding(dict(document))
    except (TypeError, ValueError, KeyError) as exc:
        raise AnpProtocolError("did_document_binding_invalid") from exc
    if not valid:
        raise AnpProtocolError("did_document_binding_invalid")


def ed25519_root_fingerprint(public_key: Any) -> str:
    return _sdk_compute_multikey_fingerprint(public_key)


def valid_handle_local_part(handle: str) -> bool:
    return _sdk_validate_local_part(handle)


def did_resolution_authority(did: str) -> str:
    if not isinstance(did, str) or any(char.isspace() for char in did) or re.search(r"%(?![0-9a-fA-F]{2})", did):
        raise AnpProtocolError("invalid_did")
    parts = did.split(":")
    if len(parts) < 3 or parts[:2] not in (["did", "wba"], ["did", "web"]) or any(not part for part in parts[2:]):
        raise AnpProtocolError("invalid_did")
    try:
        authority = urllib.parse.unquote(parts[2], errors="strict")
    except UnicodeError as exc:
        raise AnpProtocolError("invalid_did_authority") from exc
    if not authority.isascii() or any(char in authority for char in "/\\?#@%") or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in authority):
        raise AnpProtocolError("invalid_did_authority")
    try:
        parsed = urllib.parse.urlsplit(f"https://{authority}")
        if not parsed.hostname or (parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError("invalid authority")
    except ValueError as exc:
        raise AnpProtocolError("invalid_did_authority") from exc
    for part in parts[3:]:
        try:
            value = urllib.parse.unquote(part, errors="strict")
        except UnicodeError as exc:
            raise AnpProtocolError("invalid_did_path") from exc
        if value in {".", ".."} or any(char in value for char in "/\\?#%") or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise AnpProtocolError("invalid_did_path")
    return authority.lower()


def did_resolution_url(did: str, *, base_url_override: str | None = None) -> str:
    did_resolution_authority(did)
    try:
        url = _sdk_build_did_resolution_url(did, base_url_override=base_url_override)
        parsed = urllib.parse.urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("invalid resolver URL")
        if parsed.scheme not in ({"https", "http"} if base_url_override is not None else {"https"}):
            raise ValueError("invalid resolver scheme")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;=-._~"), "", ""))
    except ValueError as exc:
        raise AnpProtocolError("invalid_did_resolution_url") from exc


def validate_single_device_document(document: Mapping[str, Any]) -> SingleDeviceManifest | None:
    """Validate public identity roles without enabling encrypted messaging.

    Validate the original Manifest with the published SDK. Historical draft
    profile bundles are normalized only for the SDK's canonical key-role
    builder; the signed document and stored/wire profiles stay unchanged.
    """
    if "deviceManifest" not in document:
        return None
    pending = [document]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if ("kty" in item and "d" in item) or (item.get("kty") == "oct" and "k" in item):
                raise AnpProtocolError("device_manifest_invalid")
            for name, value in item.items():
                if "privatekey" in str(name).lower().replace("_", "").replace("-", ""):
                    raise AnpProtocolError("device_manifest_invalid")
                pending.append(value)
        elif isinstance(item, list):
            pending.extend(item)
    raw_manifest = document["deviceManifest"]
    if not isinstance(raw_manifest, dict):
        raise AnpProtocolError("device_manifest_invalid")
    devices = raw_manifest.get("devices")
    if not isinstance(devices, list) or not devices:
        raise AnpProtocolError("device_manifest_invalid")
    if len(devices) != 1:
        raise AnpProtocolError("multiple_devices_not_supported")
    try:
        validated = copy.deepcopy(dict(document))
        manifest = _sdk_validate_device_manifest(validated)
        if manifest is None or len(manifest.devices) != 1:
            raise ValueError("single Manifest device required")
        device = manifest.devices[0]
        did = validated["id"]
        if did.startswith("did:wba:") and not did.rsplit(":", 1)[-1].startswith("e1_"):
            raise ValueError("local device identity requires an e1 binding")
        if not _sdk_validate_did_document_binding(dict(document)):
            raise ValueError("DID root fingerprint/proof binding is invalid")
        root_id = validated["proof"]["verificationMethod"]
        if root_id in {device.signing_key_id, device.e2ee_key_id} or device.signing_key_id == f"{did}#key-1":
            raise ValueError("root cannot authorize a device token")
        methods = validated["verificationMethod"]
        if any(not isinstance(method, dict) for method in methods):
            raise ValueError("verification methods must be objects")
        ids = [method.get("id") for method in methods]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate verification method")
        by_id = {method["id"]: method for method in methods}
        managed_fields = {"verificationMethod", "authentication", "assertionMethod", "keyAgreement", "deviceManifest", "proof"}
        base = {key: value for key, value in validated.items() if key not in managed_fields}
        historical_foundations = {
            "anp.core.binding.v2": "anp.core.binding.v1",
            "anp.identity.discovery.v2": "anp.identity.discovery.v1",
            "anp.direct.base.v2": "anp.direct.base.v1",
        }
        role_profiles = tuple(historical_foundations.get(p, p) for p in device.profiles)
        if "anp.group.e2ee.v2" in role_profiles:
            role_profiles = tuple("anp.group.base.v2" if p == "anp.group.base.v1" else p for p in role_profiles)
        role_device = replace(device, profiles=role_profiles)
        rebuilt = _sdk_build_vnext_did_document(
            base, root_id, by_id[root_id], role_device,
            by_id[device.signing_key_id], by_id[device.e2ee_key_id],
        )
        for relation in ("authentication", "assertionMethod", "keyAgreement"):
            values = validated.get(relation)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("verification relationships must be references")
            if len(set(values)) != len(values):
                raise ValueError("duplicate verification relationship")
            managed_ids = {root_id, device.signing_key_id, device.e2ee_key_id}
            if set(values) & managed_ids != set(rebuilt[relation]):
                raise ValueError("root/device verification roles do not match")
        material = [by_id[root_id], by_id[device.signing_key_id], by_id[device.e2ee_key_id]]
        digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return SingleDeviceManifest(device.device_id, device.signing_key_id, root_id, digest)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise AnpProtocolError("device_manifest_invalid") from exc


def signature_keyid(headers: Mapping[str, str]) -> str:
    """Return the RFC 9421 keyid without treating any hint header as identity."""

    try:
        metadata = _sdk_extract_signature_metadata({str(key): str(value) for key, value in headers.items()})
    except Exception as exc:
        raise AnpProtocolError(_map_http_signature_error(str(exc)), str(exc)) from exc
    params = metadata.get("params")
    keyid = params.get("keyid") if isinstance(params, dict) else None
    if not isinstance(keyid, str) or "#" not in keyid:
        raise AnpProtocolError("signature_keyid_required")
    return keyid


def create_group_did_identity(
    *,
    hostname: str,
    group_id: str,
    service_endpoint: str,
    service_did: str,
    profile: str = "anp.group.base.v1",
) -> tuple[dict[str, Any], str]:
    """Create an e1 Group DID document and its PKCS#8 Ed25519 private key."""
    service = _sdk_build_group_message_service(
        did="did:wba:placeholder",
        service_endpoint=service_endpoint,
        fragment="anp-message",
        service_did=service_did,
        profiles=[profile],
        security_profiles=["transport-protected"],
        auth_schemes=["didwba"],
    )
    service["id"] = "#anp-message"
    document, keys = _sdk_create_did_wba_document(
        hostname,
        path_segments=["groups", group_id],
        services=[service],
        enable_e2ee=False,
        did_profile="e1",
    )
    private_key = keys.get("key-1", (None, None))[0]
    if not isinstance(private_key, bytes):
        raise AnpProtocolError("group_identity_key_missing")
    return dict(document), private_key.decode("ascii")


def sign_group_receipt(
    receipt: Mapping[str, Any],
    *,
    private_key: Any,
    verification_method: str,
) -> dict[str, Any]:
    try:
        return _sdk_generate_group_receipt_proof(
            dict(receipt),
            private_key,
            verification_method,
        )
    except Exception as exc:
        raise AnpProtocolError("group_receipt_signing_failed", str(exc)) from exc


def verify_group_receipt(
    receipt: Mapping[str, Any],
    *,
    issuer_did_document: Mapping[str, Any],
) -> bool:
    try:
        return bool(_sdk_verify_group_receipt_proof(dict(receipt), _method_lookup_document(issuer_did_document)))
    except (AnpProtocolError, TypeError, ValueError):
        return False


def normalize_wns_handle(handle: str) -> str:
    try:
        return str(_sdk_normalize_handle(handle))
    except Exception as exc:
        raise AnpProtocolError("group_handle_invalid", str(exc)) from exc


def web_handle_hint(document: Mapping[str, Any]) -> str | None:
    """An exact resolution URI is a name hint, never binding evidence."""
    hints = set()
    for service in document.get("service", []):
        if not isinstance(service, dict) or service.get("type") != "ANPHandleService":
            continue
        endpoint = service.get("serviceEndpoint")
        if not isinstance(endpoint, str):
            continue
        try:
            parsed = urllib.parse.urlsplit(endpoint)
            port = parsed.port
        except ValueError:
            continue
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port or parsed.query or parsed.fragment:
            continue
        prefix = "/.well-known/handle/"
        if not parsed.path.startswith(prefix):
            continue
        local = urllib.parse.unquote(parsed.path[len(prefix):])
        try:
            handle = normalize_wns_handle(f"{local}.{parsed.hostname}")
        except AnpProtocolError:
            continue
        if endpoint == web_handle_resolution_url(handle):
            hints.add(handle)
    return next(iter(hints)) if len(hints) == 1 else None


def web_handle_resolution_url(handle: str) -> str:
    local, domain = normalize_wns_handle(handle).split(".", 1)
    return f"https://{domain}/.well-known/handle/{urllib.parse.quote(local, safe='-._~')}"


def verify_web_handle_documents(handle: str, resolution: Mapping[str, Any], document: Mapping[str, Any]) -> Any:
    """Published native-Web appendix B.4, with guarded I/O owned by the caller.

    The SDK's network WNS verifier is WBA-only. Reuse its DTO/generation and
    DID validators here; Web reverse binding is provider-domain based, not the
    stronger WBA exact-handle/provider-confirmed contract.
    """
    try:
        canonical = normalize_wns_handle(handle)
        value = _SdkHandleResolutionDocument.model_validate(dict(resolution))
        if value.handle != canonical or value.status != "active" or not value.did.startswith("did:web:") or document.get("id") != value.did:
            raise ValueError("binding mismatch")
        # Native Web authority comes from its verified HTTPS resolution, not
        # WBA e1_/k1_ path fingerprints or mandatory WBA document proofs.
        did_resolution_url(value.did)
        domain = canonical.split(".", 1)[1]
        matched = False
        for service in document.get("service", []):
            if isinstance(service, dict) and service.get("type") == "ANPHandleService" and isinstance(service.get("serviceEndpoint"), str):
                endpoint = urllib.parse.urlsplit(service["serviceEndpoint"])
                matched |= endpoint.scheme == "https" and endpoint.hostname == domain and endpoint.username is None and endpoint.password is None and endpoint.port is None
        if not matched:
            raise ValueError("reverse domain mismatch")
        return value
    except Exception as exc:
        raise AnpProtocolError("web_handle_binding_invalid", "Web Handle documents do not form an active bidirectional binding") from exc


def canonicalize_binding_generation(value: Any) -> str:
    try:
        return str(_sdk_canonicalize_binding_generation(value))
    except Exception as exc:
        raise AnpProtocolError("group_binding_generation_invalid", str(exc)) from exc


def compare_binding_generations(left: Any, right: Any) -> int:
    try:
        return int(_sdk_compare_binding_generations(left, right))
    except Exception as exc:
        raise AnpProtocolError("group_binding_generation_invalid", str(exc)) from exc


def verify_wns_handle_binding(
    handle: str,
    *,
    did_document: Mapping[str, Any] | None = None,
    timeout_seconds: float = 10,
    verify_ssl: bool = True,
) -> Any:
    try:
        return asyncio.run(
            _sdk_verify_handle_binding(
                handle,
                did_document=dict(did_document) if did_document is not None else None,
                timeout_seconds=timeout_seconds,
                verify_ssl=verify_ssl,
            )
        )
    except Exception as exc:
        raise AnpProtocolError("group_handle_binding_invalid", str(exc)) from exc


def build_content_digest(body: bytes | bytearray | str) -> str:
    if isinstance(body, bytearray):
        body = bytes(body)
    if isinstance(body, str):
        body = body.encode("utf-8")
    return _sdk_build_content_digest(body)


def _method_lookup_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve same-document fragments for key lookup, without changing wire JSON."""
    value = copy.deepcopy(dict(document))
    did = value.get("id")
    if not isinstance(did, str):
        raise AnpProtocolError("did_document_id_required")
    def reference(item: Any) -> Any:
        return did + item if isinstance(item, str) and item.startswith("#") else item
    seen = {}
    methods = value.get("verificationMethod", [])
    if not isinstance(methods, list):
        raise AnpProtocolError("verification_method_invalid")
    for method in methods:
        if not isinstance(method, dict):
            raise AnpProtocolError("verification_method_invalid")
        method["id"] = reference(method.get("id"))
        if not isinstance(method["id"], str) or method["id"] in seen:
            raise AnpProtocolError("verification_method_ambiguous")
        seen[method["id"]] = method
    for relation in ("authentication", "assertionMethod", "keyAgreement"):
        entries = value.get(relation, [])
        if not isinstance(entries, list):
            raise AnpProtocolError("verification_relationship_invalid")
        normalized = []
        for entry in entries:
            if isinstance(entry, dict):
                entry["id"] = reference(entry.get("id"))
                if not isinstance(entry["id"], str) or (entry["id"] in seen and seen[entry["id"]] != entry):
                    raise AnpProtocolError("verification_method_ambiguous")
                seen[entry["id"]] = entry
            else:
                entry = reference(entry)
            normalized.append(entry)
        if relation in value:
            value[relation] = normalized
    return value


def find_verification_method(document: Mapping[str, Any], key_id: str) -> dict[str, Any] | None:
    document = _method_lookup_document(document)
    methods = document.get("verificationMethod", [])
    if isinstance(methods, list):
        for method in methods:
            if isinstance(method, dict) and method.get("id") == key_id:
                return method
    for relationship in ("authentication", "assertionMethod"):
        entries = document.get(relationship, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == key_id:
                return entry
            if isinstance(entry, str) and entry == key_id and isinstance(methods, list):
                for method in methods:
                    if isinstance(method, dict) and method.get("id") == key_id:
                        return method
    return None


def has_verification_method(document: Mapping[str, Any], key_id: str) -> bool:
    return find_verification_method(document, key_id) is not None


def is_verification_method_authorized(
    document: Mapping[str, Any],
    key_id: str,
    relationship: str,
) -> bool:
    document = _method_lookup_document(document)
    entries = document.get(relationship, [])
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if isinstance(entry, str) and entry == key_id:
            return True
        if isinstance(entry, dict) and entry.get("id") == key_id:
            return True
    return False


def generate_service_http_signature_headers(
    *,
    did_document: Mapping[str, Any],
    request_url: str,
    request_method: str,
    sign_callback: Callable[[bytes, str], bytes],
    headers: Mapping[str, str] | None,
    body: bytes | bytearray | str | None,
    keyid: str,
) -> dict[str, str]:
    try:
        return _sdk_generate_http_signature_headers(
            _method_lookup_document(did_document),
            request_url=request_url,
            request_method=request_method,
            sign_callback=sign_callback,
            headers=dict(headers or {}),
            body=body or b"",
            keyid=keyid,
        )
    except Exception as exc:
        raise AnpProtocolError("signature_generation_failed", str(exc)) from exc


def verify_service_http_signature(
    *,
    did_document: Mapping[str, Any],
    request_method: str,
    request_url: str,
    headers: Mapping[str, str],
    body: bytes | bytearray | str | None,
) -> ServiceHttpSignatureVerification:
    header_map = {str(key): str(value) for key, value in headers.items()}
    if not _header_value(header_map, "Signature-Input") or not _header_value(header_map, "Signature"):
        raise AnpProtocolError("missing_peer_http_signature")
    try:
        metadata = _sdk_extract_signature_metadata(header_map)
    except Exception as exc:
        raise AnpProtocolError(_map_http_signature_error(str(exc)), str(exc)) from exc

    params = metadata.get("params")
    if not isinstance(params, dict):
        raise AnpProtocolError("invalid_signature_input")
    keyid = params.get("keyid")
    if not isinstance(keyid, str) or not keyid:
        raise AnpProtocolError("signature_keyid_required")
    service_did = did_document.get("id")
    if not isinstance(service_did, str) or keyid.split("#", 1)[0] != service_did:
        raise AnpProtocolError("signature_keyid_did_mismatch")
    if not is_verification_method_authorized(did_document, keyid, "authentication"):
        raise AnpProtocolError("verification_method_not_found")

    body_bytes = _ensure_bytes(body)
    components = [str(component).lower() for component in metadata.get("components", [])]
    if body_bytes or "content-digest" in components:
        digest = _header_value(header_map, "Content-Digest")
        if not digest:
            raise AnpProtocolError("missing_content_digest")
        if digest.strip() != build_content_digest(body_bytes):
            raise AnpProtocolError("content_digest_mismatch")

    _validate_signature_time(params)
    try:
        ok, message, sdk_metadata = _sdk_verify_http_message_signature(
            _method_lookup_document(did_document),
            request_method=request_method,
            request_url=request_url,
            headers=header_map,
            body=body_bytes,
        )
    except Exception as exc:
        raise AnpProtocolError(_map_http_signature_error(str(exc)), str(exc)) from exc
    if not ok:
        raise AnpProtocolError(_map_http_signature_error(message), message)
    return ServiceHttpSignatureVerification(
        keyid=keyid,
        metadata={**metadata, **(sdk_metadata or {})},
    )


def verify_origin_proof(
    *,
    origin_proof: Mapping[str, Any],
    method: str,
    meta: Mapping[str, Any],
    body: Mapping[str, Any],
    did_document: Mapping[str, Any] | None,
    expected_signer_did: str,
    verified_at: datetime | None = None,
) -> OriginProofVerification:
    if not isinstance(origin_proof, Mapping):
        raise AnpProtocolError("invalid_origin_proof")
    required_fields = ("contentDigest", "signatureInput", "signature")
    if not all(isinstance(origin_proof.get(field), str) and origin_proof.get(field) for field in required_fields):
        raise AnpProtocolError("invalid_origin_proof")

    try:
        parsed = _sdk_parse_im_signature_input(str(origin_proof["signatureInput"]))
    except Exception as exc:
        code = "origin_proof_keyid_required" if "keyid" in str(exc) else "invalid_origin_proof_signature_input"
        raise AnpProtocolError(code, str(exc)) from exc
    if parsed.label != RFC9421_ORIGIN_PROOF_DEFAULT_LABEL or tuple(parsed.components) != tuple(
        RFC9421_ORIGIN_PROOF_DEFAULT_COMPONENTS
    ):
        raise AnpProtocolError("invalid_origin_proof_signature_input")
    if not parsed.keyid:
        raise AnpProtocolError("origin_proof_keyid_required")
    if parsed.keyid.split("#", 1)[0] != expected_signer_did:
        raise AnpProtocolError("origin_proof_keyid_sender_mismatch")
    _validate_signature_time({"created": parsed.created, "expires": parsed.expires, "nonce": parsed.nonce}, verified_at=verified_at)
    if did_document is None:
        raise AnpProtocolError("origin_proof_did_document_required")
    if did_document.get("id") != expected_signer_did:
        raise AnpProtocolError("origin_proof_did_document_mismatch")

    try:
        signature_label, _ = _sdk_decode_im_signature(str(origin_proof["signature"]))
    except Exception as exc:
        raise AnpProtocolError("invalid_origin_proof_signature", str(exc)) from exc
    if signature_label not in {None, parsed.label}:
        raise AnpProtocolError("origin_proof_signature_label_mismatch")
    if not is_verification_method_authorized(did_document, parsed.keyid, "authentication"):
        raise AnpProtocolError("origin_proof_key_not_authorized")

    try:
        # P1 Appendix A.3 excludes operational tracking from the Signed Request
        # Object. Keep diagnostics on the wire/storage, outside business proof.
        signed_meta = {key: value for key, value in meta.items() if key not in {"trace", "trace_id"}}
        result = _sdk_verify_origin_proof(
            {str(key): str(value) for key, value in origin_proof.items()},
            method,
            signed_meta,
            dict(body),
            did_document=_method_lookup_document(did_document),
            options=Rfc9421OriginProofVerificationOptions(expected_signer_did=expected_signer_did),
        )
    except Exception as exc:
        raise AnpProtocolError(_map_origin_proof_error(str(exc)), str(exc)) from exc
    return OriginProofVerification(
        keyid=parsed.keyid,
        verification_method=dict(result.verification_method),
    )


def _ensure_bytes(body: bytes | bytearray | str | None) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    raise TypeError(f"Unsupported body type: {type(body).__name__}")


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _validate_signature_time(
    params: Mapping[str, Any],
    *,
    max_age_seconds: int = 600,
    skew_seconds: int = 60,
    verified_at: datetime | None = None,
) -> None:
    created = params.get("created")
    if not isinstance(created, int):
        raise AnpProtocolError("signature_created_required")
    expires = params.get("expires")
    if expires is not None and not isinstance(expires, int):
        raise AnpProtocolError("signature_expires_invalid")
    if expires is not None and expires < created:
        raise AnpProtocolError("signature_expires_before_created")
    if verified_at is not None and verified_at.tzinfo is None:
        raise AnpProtocolError("signature_verification_time_invalid")
    now = int((verified_at or datetime.now(timezone.utc)).timestamp())
    if created > now + skew_seconds:
        raise AnpProtocolError("signature_created_in_future")
    effective_expires = expires if expires is not None else created + max_age_seconds
    if now > effective_expires + skew_seconds:
        raise AnpProtocolError("signature_expired")


def _map_http_signature_error(message: str) -> str:
    normalized = message.lower()
    if "missing signature-input" in normalized or "missing signature" in normalized:
        return "missing_peer_http_signature"
    if "label mismatch" in normalized:
        return "signature_label_mismatch"
    if "missing keyid" in normalized:
        return "signature_keyid_required"
    if "verification method" in normalized:
        return "verification_method_not_found"
    if "missing content-digest" in normalized:
        return "missing_content_digest"
    if "content-digest" in normalized:
        return "content_digest_mismatch"
    return "invalid_peer_http_signature"


def _map_origin_proof_error(message: str) -> str:
    normalized = message.lower()
    if "contentdigest" in normalized or "content digest" in normalized:
        return "origin_proof_content_digest_mismatch"
    if "covered components" in normalized or "signatureinput" in normalized:
        return "invalid_origin_proof_signature_input"
    if "expected signer" in normalized or "belong to expected signer" in normalized:
        return "origin_proof_keyid_sender_mismatch"
    if "not authorized" in normalized or "verification method not found" in normalized:
        return "origin_proof_key_not_authorized"
    return "invalid_origin_proof_signature"


__all__ = [
    "ANP_SDK_VERSION",
    "REQUIRED_ANP_SDK_VERSION",
    "AnpProtocolError",
    "OriginProofVerification",
    "ServiceHttpSignatureVerification",
    "build_content_digest",
    "canonicalize_binding_generation",
    "compare_binding_generations",
    "create_group_did_identity",
    "find_verification_method",
    "generate_service_http_signature_headers",
    "has_verification_method",
    "is_verification_method_authorized",
    "normalize_wns_handle",
    "sign_group_receipt",
    "verify_origin_proof",
    "verify_group_receipt",
    "verify_wns_handle_binding",
    "verify_service_http_signature",
]
