from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
from typing import Any
import urllib.parse
import re

import jcs
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from awiki_open_server.shared.errors import InvalidParams, Unauthorized


_SIGNATURE_INPUT_RE = re.compile(r'^\s*(?P<label>[A-Za-z0-9_-]+)=\((?P<components>[^)]*)\)(?P<params>.*)$')
_SIGNATURE_RE = re.compile(r"^\s*(?P<label>[A-Za-z0-9_-]+)=:(?P<value>[A-Za-z0-9+/=]+):\s*$")
_PROOF_SIGNATURE_RE = re.compile(r"^\s*(?:(?P<label>[A-Za-z0-9_-]+)=)?:(?P<value>[A-Za-z0-9+/=_-]+):\s*$")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _canonical_json(value: Any) -> bytes:
    return jcs.canonicalize(value)


def _multikey_ed25519(public_key: ed25519.Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    # multicodec ed25519-pub varint prefix: 0xed 0x01
    import base58

    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def _load_ed25519_private_key(pem: str) -> ed25519.Ed25519PrivateKey:
    key = load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise InvalidParams("service_private_key_must_be_ed25519")
    return key


def generate_ed25519_private_key_pem() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def _service_did_domain(service_did: str) -> str:
    parts = service_did.split(":")
    if len(parts) != 3 or parts[0] != "did" or parts[1] != "wba" or not parts[2]:
        raise InvalidParams("service_did_must_be_bare_wba_domain")
    return parts[2]


def _service_entry(did: str, endpoint: str) -> dict[str, Any]:
    return {
        "id": f"{did}#anp-message",
        "type": "ANPMessageService",
        "serviceEndpoint": endpoint,
        "serviceDid": did,
        "profiles": [
            "anp.core.binding.v1",
            "anp.direct.base.v1",
            "anp.group.base.v1",
            "anp.attachment.v1",
        ],
        "securityProfiles": ["transport-protected"],
        "authSchemes": ["bearer", "didwba"],
    }


def _anp_message_services(document: dict[str, Any]) -> list[dict[str, Any]]:
    services = document.get("service")
    if not isinstance(services, list):
        return []
    return [
        service
        for service in services
        if isinstance(service, dict) and service.get("type") == "ANPMessageService"
    ]


def _validate_service_did_document(document: dict[str, Any], service_did: str, endpoint: str, key_id: str) -> None:
    if document.get("id") != service_did:
        raise InvalidParams("service_did_document_id_mismatch")
    services = _anp_message_services(document)
    if len(services) != 1:
        raise InvalidParams("service_did_document_requires_single_anp_message_service")
    service = services[0]
    if service.get("serviceEndpoint") != endpoint:
        raise InvalidParams(
            "service_did_document_endpoint_mismatch",
            data={"actual": service.get("serviceEndpoint"), "expected": endpoint},
        )
    if service.get("serviceDid") != service_did:
        raise InvalidParams(
            "service_did_document_service_did_mismatch",
            data={"actual": service.get("serviceDid"), "expected": service_did},
        )
    if service.get("authSchemes") != ["bearer", "didwba"]:
        raise InvalidParams(
            "service_did_document_auth_schemes_mismatch",
            data={"actual": service.get("authSchemes"), "expected": ["bearer", "didwba"]},
        )
    if not _has_verification_method(document, key_id):
        raise InvalidParams("service_did_document_verification_method_missing")
    if not _verification_method_authorized(document, key_id, "authentication"):
        raise InvalidParams("service_did_document_authentication_missing")


def _sign_did_document(document: dict[str, Any], key: ed25519.Ed25519PrivateKey, key_id: str) -> dict[str, Any]:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proof = {
        "type": "DataIntegrityProof",
        "created": created,
        "verificationMethod": key_id,
        "proofPurpose": "assertionMethod",
        "cryptosuite": "eddsa-jcs-2022",
    }
    unsigned = {k: v for k, v in document.items() if k != "proof"}
    signing_input = _sha256(_canonical_json(proof)) + _sha256(_canonical_json(unsigned))
    signed = dict(document)
    signed["proof"] = {**proof, "proofValue": _b64u(key.sign(signing_input))}
    return signed


def build_service_did_document(service_did: str, endpoint: str, private_key_pem: str) -> dict[str, Any]:
    _service_did_domain(service_did)
    key = _load_ed25519_private_key(private_key_pem)
    key_id = f"{service_did}#key-1"
    public_key = key.public_key()
    document = {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/data-integrity/v2",
            "https://w3id.org/security/multikey/v1",
        ],
        "id": service_did,
        "verificationMethod": [
            {
                "id": key_id,
                "type": "Multikey",
                "controller": service_did,
                "publicKeyMultibase": _multikey_ed25519(public_key),
            }
        ],
        "authentication": [key_id],
        "assertionMethod": [key_id],
        "service": [_service_entry(service_did, endpoint)],
    }
    return _sign_did_document(document, key, key_id)


def content_digest(body: bytes) -> str:
    return f"sha-256=:{_b64(_sha256(body))}:"


def _header_value(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _authority(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc or "@" in parsed.netloc:
        raise InvalidParams("invalid_signature_url")
    return parsed.netloc


def _serialize_signature_params(
    components: list[str],
    created: int,
    expires: int | None,
    nonce: str | None,
    key_id: str,
) -> str:
    quoted = " ".join(f'"{component}"' for component in components)
    params = [f"created={created}"]
    if expires is not None:
        params.append(f"expires={expires}")
    if nonce:
        params.append(f'nonce="{nonce}"')
    params.append(f'keyid="{key_id}"')
    return f"({quoted});" + ";".join(params)


def _signature_component_value(component: str, method: str, url: str, headers: dict[str, str]) -> str:
    if component == "@method":
        return method.upper()
    if component == "@target-uri":
        return url
    if component == "@authority":
        return _authority(url)
    value = _header_value(headers, component)
    if value is None:
        raise InvalidParams("missing_signature_component", data={"component": component})
    return value


def signature_base(
    components: list[str],
    method: str,
    url: str,
    headers: dict[str, str],
    created: int,
    expires: int | None,
    nonce: str | None,
    key_id: str,
) -> bytes:
    lines = [
        f'"{component}": {_signature_component_value(component, method, url, headers)}'
        for component in components
    ]
    lines.append(f'"@signature-params": {_serialize_signature_params(components, created, expires, nonce, key_id)}')
    return "\n".join(lines).encode()


def _parse_signature_input(value: str) -> tuple[str, list[str], dict[str, str]]:
    match = _SIGNATURE_INPUT_RE.match(value.strip())
    if not match:
        raise Unauthorized("invalid_signature_input")
    components = re.findall(r'"([^"]+)"', match.group("components"))
    params: dict[str, str] = {}
    for raw in match.group("params").split(";"):
        raw = raw.strip()
        if not raw or "=" not in raw:
            continue
        name, param_value = raw.split("=", 1)
        params[name.strip()] = param_value.strip().strip('"')
    return match.group("label"), components, params


def _timestamp_param(params: dict[str, str], name: str) -> int:
    raw = params.get(name)
    if raw is None:
        raise Unauthorized(f"signature_{name}_required")
    try:
        return int(raw)
    except ValueError as exc:
        raise Unauthorized(f"signature_{name}_invalid") from exc


def _validate_signature_time(params: dict[str, str], *, max_age_seconds: int = 600, skew_seconds: int = 60) -> tuple[int, int | None]:
    created = _timestamp_param(params, "created")
    expires = None
    if params.get("expires"):
        try:
            expires = int(params["expires"])
        except ValueError as exc:
            raise Unauthorized("signature_expires_invalid") from exc
        if expires < created:
            raise Unauthorized("signature_expires_before_created")
    now = int(datetime.now(timezone.utc).timestamp())
    if created > now + skew_seconds:
        raise Unauthorized("signature_created_in_future")
    effective_expires = expires if expires is not None else created + max_age_seconds
    if now > effective_expires + skew_seconds:
        raise Unauthorized("signature_expired")
    return created, expires


def _parse_signature(value: str) -> tuple[str, bytes]:
    match = _SIGNATURE_RE.match(value.strip())
    if not match:
        raise Unauthorized("invalid_signature_header")
    return match.group("label"), base64.b64decode(match.group("value"))


def _parse_proof_signature(value: str) -> tuple[str | None, bytes]:
    match = _PROOF_SIGNATURE_RE.match(value.strip())
    if not match:
        raise Unauthorized("invalid_origin_proof_signature")
    encoded = match.group("value")
    try:
        return match.group("label"), base64.b64decode(encoded, validate=True)
    except Exception:
        padding = "=" * (-len(encoded) % 4)
        return match.group("label"), base64.urlsafe_b64decode(encoded + padding)


def _find_verification_method(document: dict[str, Any], key_id: str) -> dict[str, Any]:
    for method in document.get("verificationMethod", []):
        if isinstance(method, dict) and method.get("id") == key_id:
            return method
    for method in document.get("authentication", []):
        if isinstance(method, dict) and method.get("id") == key_id:
            return method
    raise Unauthorized("verification_method_not_found")


def _has_verification_method(document: dict[str, Any], key_id: str) -> bool:
    try:
        _find_verification_method(document, key_id)
    except Unauthorized:
        return False
    return True


def _verification_method_authorized(document: dict[str, Any], key_id: str, relationship: str) -> bool:
    for entry in document.get(relationship, []):
        if isinstance(entry, str) and entry == key_id:
            return True
        if isinstance(entry, dict) and entry.get("id") == key_id:
            return True
    return False


def _ed25519_public_key_from_method(method: dict[str, Any]) -> ed25519.Ed25519PublicKey:
    if method.get("type") not in {"Multikey", "Ed25519VerificationKey2018", "Ed25519VerificationKey2020"}:
        raise Unauthorized("unsupported_peer_verification_method")
    if isinstance(method.get("publicKeyJwk"), dict):
        jwk = method["publicKeyJwk"]
        if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
            raise Unauthorized("invalid_ed25519_jwk")
        raw = base64.urlsafe_b64decode(jwk["x"] + "=" * (-len(jwk["x"]) % 4))
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)
    multikey = method.get("publicKeyMultibase")
    if isinstance(multikey, str) and multikey.startswith("z"):
        import base58

        raw = base58.b58decode(multikey[1:])
        if len(raw) == 34 and raw[:2] == b"\xed\x01":
            raw = raw[2:]
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)
    raise Unauthorized("missing_ed25519_key_material")


def verify_peer_http_signature(
    *,
    service_did_document: dict[str, Any],
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
) -> str:
    signature_input_header = _header_value(headers, "Signature-Input")
    signature_header = _header_value(headers, "Signature")
    if not signature_input_header or not signature_header:
        raise Unauthorized("missing_peer_http_signature")
    label_input, components, params = _parse_signature_input(signature_input_header)
    label_signature, signature_bytes = _parse_signature(signature_header)
    if label_input != label_signature:
        raise Unauthorized("signature_label_mismatch")
    key_id = params.get("keyid")
    if not key_id:
        raise Unauthorized("signature_keyid_required")
    service_did = service_did_document.get("id")
    if not isinstance(service_did, str) or key_id.split("#", 1)[0] != service_did:
        raise Unauthorized("signature_keyid_did_mismatch")
    if "content-digest" in [component.lower() for component in components] or body:
        digest = _header_value(headers, "Content-Digest")
        if not digest:
            raise Unauthorized("missing_content_digest")
        if digest.strip() != content_digest(body):
            raise Unauthorized("content_digest_mismatch")
    created, expires = _validate_signature_time(params)
    base = signature_base(
        components,
        method,
        url,
        headers,
        created,
        expires,
        params.get("nonce"),
        key_id,
    )
    public_key = _ed25519_public_key_from_method(_find_verification_method(service_did_document, key_id))
    public_key.verify(signature_bytes, base)
    return key_id


@dataclass(frozen=True)
class ServiceIdentity:
    did: str
    did_document: dict[str, Any]
    private_key_pem: str
    verification_method_id: str

    def sign_headers(self, url: str, method: str, base_headers: dict[str, str], body: bytes) -> dict[str, str]:
        key = _load_ed25519_private_key(self.private_key_pem)
        headers = dict(base_headers)
        components = ["@method", "@target-uri", "@authority"]
        if body:
            headers.setdefault("Content-Digest", content_digest(body))
            headers.setdefault("Content-Length", str(len(body)))
            components.append("content-digest")
        created = int(datetime.now(timezone.utc).timestamp())
        expires = created + 300
        nonce = _b64u(secrets.token_bytes(16))
        base = signature_base(
            components,
            method,
            url,
            headers,
            created,
            expires,
            nonce,
            self.verification_method_id,
        )
        return {
            "Signature-Input": f"sig1={_serialize_signature_params(components, created, expires, nonce, self.verification_method_id)}",
            "Signature": f"sig1=:{_b64(key.sign(base))}:",
            **({"Content-Digest": headers["Content-Digest"]} if body else {}),
        }


def service_identity_from_settings(
    *,
    service_did: str,
    endpoint: str,
    private_key_pem: str | None,
    document_json: str | None = None,
) -> ServiceIdentity | None:
    if not private_key_pem:
        return None
    document = json.loads(document_json) if document_json else build_service_did_document(service_did, endpoint, private_key_pem)
    key_id = f"{service_did}#key-1"
    _validate_service_did_document(document, service_did, endpoint, key_id)
    return ServiceIdentity(
        did=service_did,
        did_document=document,
        private_key_pem=private_key_pem,
        verification_method_id=key_id,
    )


def require_origin_proof(auth: dict[str, Any] | None) -> None:
    if not isinstance(auth, dict) or not isinstance(auth.get("origin_proof"), dict):
        raise Unauthorized("missing_origin_proof")


def _origin_logical_target_uri(meta: dict[str, Any]) -> str:
    target = meta.get("target")
    if not isinstance(target, dict):
        raise Unauthorized("origin_proof_target_required")
    kind = target.get("kind")
    did = target.get("did")
    if kind not in {"agent", "group", "service"} or not isinstance(did, str) or not did:
        raise Unauthorized("origin_proof_target_invalid")
    return f"anp://{kind}/{urllib.parse.quote(did, safe='-._~')}"


def validate_origin_proof_structure(
    auth: dict[str, Any] | None,
    *,
    method: str,
    meta: dict[str, Any],
    body: dict[str, Any],
    sender_did_document: dict[str, Any] | None = None,
) -> None:
    require_origin_proof(auth)
    proof = auth["origin_proof"]
    digest = proof.get("contentDigest")
    signature_input = proof.get("signatureInput")
    signature = proof.get("signature")
    if not all(isinstance(value, str) and value for value in [digest, signature_input, signature]):
        raise Unauthorized("invalid_origin_proof")
    signed_object = {"method": method, "meta": dict(meta), "body": dict(body)}
    canonical_request = _canonical_json(signed_object)
    if digest != content_digest(canonical_request):
        raise Unauthorized("origin_proof_content_digest_mismatch")
    label, components, params = _parse_signature_input(signature_input)
    if label != "sig1" or components != ["@method", "@target-uri", "content-digest"]:
        raise Unauthorized("invalid_origin_proof_signature_input")
    key_id = params.get("keyid")
    sender_did = meta.get("sender_did")
    if not isinstance(sender_did, str) or not sender_did:
        raise Unauthorized("origin_proof_sender_did_required")
    if not isinstance(key_id, str) or not key_id:
        raise Unauthorized("origin_proof_keyid_required")
    if key_id.split("#", 1)[0] != sender_did:
        raise Unauthorized("origin_proof_keyid_sender_mismatch")
    _validate_signature_time(params)
    if sender_did_document is None:
        raise Unauthorized("origin_proof_did_document_required")
    if sender_did_document.get("id") != sender_did:
        raise Unauthorized("origin_proof_did_document_mismatch")
    if not _verification_method_authorized(sender_did_document, key_id, "authentication"):
        raise Unauthorized("origin_proof_key_not_authorized")
    signature_label, signature_bytes = _parse_proof_signature(signature)
    if signature_label not in {None, label}:
        raise Unauthorized("origin_proof_signature_label_mismatch")
    proof_base = "\n".join(
        [
            f'"@method": {method}',
            f'"@target-uri": {_origin_logical_target_uri(meta)}',
            f'"content-digest": {digest}',
            f'"@signature-params": {signature_input.split("=", 1)[1].strip()}',
        ]
    ).encode()
    public_key = _ed25519_public_key_from_method(_find_verification_method(sender_did_document, key_id))
    try:
        public_key.verify(signature_bytes, proof_base)
    except Exception as exc:
        raise Unauthorized("invalid_origin_proof_signature") from exc


def require_signed_peer_request(headers: dict[str, str], *, allow_unsigned_dev: bool) -> None:
    if allow_unsigned_dev:
        return
    if not _header_value(headers, "Signature-Input") or not _header_value(headers, "Signature"):
        raise Unauthorized("missing_peer_http_signature")
    if not _header_value(headers, "x-anp-source-service-did"):
        raise Unauthorized("missing_source_service_did")


def load_private_key_setting(value: str | None, path: str | None) -> str | None:
    if value:
        return value.replace("\\n", "\n")
    if path:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            return handle.read()
    return None
