from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any

import jcs
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from awiki_open_server.protocol.anp_adapter import (
    AnpProtocolError,
    build_content_digest as anp_build_content_digest,
    find_verification_method,
    generate_service_http_signature_headers,
    has_verification_method,
    is_verification_method_authorized,
    verify_origin_proof,
    verify_service_http_signature,
)
from awiki_open_server.shared.errors import InvalidParams, Unauthorized


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode((value + padding).encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise InvalidParams("did_document_proof_value_invalid") from exc


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _canonical_json(value: Any) -> bytes:
    return jcs.canonicalize(value)


def _multikey_ed25519(public_key: ed25519.Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    # multicodec ed25519-pub varint prefix: 0xed 0x01
    import base58

    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def _ed25519_public_key_from_multikey(value: Any) -> ed25519.Ed25519PublicKey:
    if not isinstance(value, str) or not value.startswith("z"):
        raise InvalidParams("did_document_proof_public_key_not_supported")
    import base58

    try:
        decoded = base58.b58decode(value[1:])
    except Exception as exc:
        raise InvalidParams("did_document_proof_public_key_invalid") from exc
    if len(decoded) != 34 or decoded[:2] != b"\xed\x01":
        raise InvalidParams("did_document_proof_public_key_not_supported")
    return ed25519.Ed25519PublicKey.from_public_bytes(decoded[2:])


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
    if not has_verification_method(document, key_id):
        raise InvalidParams("service_did_document_verification_method_missing")
    if not is_verification_method_authorized(document, key_id, "authentication"):
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


def verify_did_document_data_integrity_proof(
    document: dict[str, Any],
    *,
    expected_did: str | None = None,
) -> None:
    did = document.get("id")
    if not isinstance(did, str) or not did:
        raise InvalidParams("did_document_id_required")
    if expected_did is not None and did != expected_did:
        raise InvalidParams("did_document_id_mismatch", data={"did": expected_did, "document_id": did})

    proof = document.get("proof")
    if not isinstance(proof, dict):
        raise InvalidParams("did_document_proof_required")
    if proof.get("type") != "DataIntegrityProof":
        raise InvalidParams("did_document_proof_type_not_supported")
    if proof.get("cryptosuite") != "eddsa-jcs-2022":
        raise InvalidParams("did_document_proof_cryptosuite_not_supported")
    if proof.get("proofPurpose") != "assertionMethod":
        raise InvalidParams("did_document_proof_purpose_not_supported")
    if not isinstance(proof.get("created"), str) or not proof.get("created"):
        raise InvalidParams("did_document_proof_created_required")

    verification_method = proof.get("verificationMethod")
    if not isinstance(verification_method, str) or not verification_method.startswith(f"{did}#"):
        raise InvalidParams("did_document_proof_verification_method_mismatch")
    method = find_verification_method(document, verification_method)
    if method is None:
        raise InvalidParams("did_document_proof_verification_method_missing")
    if method.get("controller") not in (None, did):
        raise InvalidParams("did_document_proof_verification_method_controller_mismatch")
    if not is_verification_method_authorized(document, verification_method, "assertionMethod"):
        raise InvalidParams("did_document_proof_verification_method_unauthorized")
    if method.get("type") != "Multikey":
        raise InvalidParams("did_document_proof_public_key_not_supported")

    public_key = _ed25519_public_key_from_multikey(method.get("publicKeyMultibase"))
    proof_value = proof.get("proofValue")
    if not isinstance(proof_value, str) or not proof_value:
        raise InvalidParams("did_document_proof_value_required")
    signature = _b64u_decode(proof_value)
    if len(signature) != 64:
        raise InvalidParams("did_document_proof_value_invalid")
    proof_options = {k: v for k, v in proof.items() if k != "proofValue"}
    unsigned = {k: v for k, v in document.items() if k != "proof"}
    signing_input = _sha256(_canonical_json(proof_options)) + _sha256(_canonical_json(unsigned))
    try:
        public_key.verify(signature, signing_input)
    except InvalidSignature as exc:
        raise InvalidParams("did_document_proof_invalid") from exc


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
    return anp_build_content_digest(body)


def _header_value(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def verify_peer_http_signature(
    *,
    service_did_document: dict[str, Any],
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
) -> str:
    try:
        verified = verify_service_http_signature(
            did_document=service_did_document,
            request_method=method,
            request_url=url,
            headers=headers,
            body=body,
        )
    except AnpProtocolError as exc:
        raise Unauthorized(exc.code, data={"detail": exc.detail}) from exc
    return verified.keyid


@dataclass(frozen=True)
class ServiceIdentity:
    did: str
    did_document: dict[str, Any]
    private_key_pem: str
    verification_method_id: str

    def sign_headers(self, url: str, method: str, base_headers: dict[str, str], body: bytes) -> dict[str, str]:
        key = _load_ed25519_private_key(self.private_key_pem)

        def sign_callback(signature_base_bytes: bytes, _: str) -> bytes:
            return key.sign(signature_base_bytes)

        try:
            return generate_service_http_signature_headers(
                did_document=self.did_document,
                request_url=url,
                request_method=method,
                sign_callback=sign_callback,
                headers=base_headers,
                body=body,
                keyid=self.verification_method_id,
            )
        except AnpProtocolError as exc:
            raise Unauthorized(exc.code, data={"detail": exc.detail}) from exc


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
    sender_did = meta.get("sender_did")
    if not isinstance(sender_did, str) or not sender_did:
        raise Unauthorized("origin_proof_sender_did_required")
    try:
        verify_origin_proof(
            origin_proof=proof,
            method=method,
            meta=meta,
            body=body,
            did_document=sender_did_document,
            expected_signer_did=sender_did,
        )
    except AnpProtocolError as exc:
        raise Unauthorized(exc.code, data={"detail": exc.detail}) from exc


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
