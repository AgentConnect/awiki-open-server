from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping


REQUIRED_ANP_SDK_VERSION = "0.8.9"


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
    verify_handle_binding as _sdk_verify_handle_binding,
)
from anp.proof.im import decode_im_signature as _sdk_decode_im_signature  # noqa: E402
from anp.proof.im import parse_im_signature_input as _sdk_parse_im_signature_input  # noqa: E402
from anp.proof.rfc9421_origin import (  # noqa: E402
    RFC9421_ORIGIN_PROOF_DEFAULT_COMPONENTS,
    RFC9421_ORIGIN_PROOF_DEFAULT_LABEL,
    Rfc9421OriginProofVerificationOptions,
    verify_rfc9421_origin_proof as _sdk_verify_origin_proof,
)


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


def create_group_did_identity(
    *,
    hostname: str,
    group_id: str,
    service_endpoint: str,
    service_did: str,
) -> tuple[dict[str, Any], str]:
    """Create an e1 Group DID document and its PKCS#8 Ed25519 private key."""
    service = _sdk_build_group_message_service(
        did="did:wba:placeholder",
        service_endpoint=service_endpoint,
        fragment="anp-message",
        service_did=service_did,
        profiles=["anp.group.base.v1"],
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
    return bool(_sdk_verify_group_receipt_proof(dict(receipt), dict(issuer_did_document)))


def normalize_wns_handle(handle: str) -> str:
    try:
        return str(_sdk_normalize_handle(handle))
    except Exception as exc:
        raise AnpProtocolError("group_handle_invalid", str(exc)) from exc


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


def find_verification_method(document: Mapping[str, Any], key_id: str) -> dict[str, Any] | None:
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
            dict(did_document),
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
            dict(did_document),
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
    _validate_signature_time({"created": parsed.created, "expires": parsed.expires, "nonce": parsed.nonce})
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
        result = _sdk_verify_origin_proof(
            {str(key): str(value) for key, value in origin_proof.items()},
            method,
            dict(meta),
            dict(body),
            did_document=dict(did_document),
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
) -> None:
    created = params.get("created")
    if not isinstance(created, int):
        raise AnpProtocolError("signature_created_required")
    expires = params.get("expires")
    if expires is not None and not isinstance(expires, int):
        raise AnpProtocolError("signature_expires_invalid")
    if expires is not None and expires < created:
        raise AnpProtocolError("signature_expires_before_created")
    now = int(datetime.now(timezone.utc).timestamp())
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
