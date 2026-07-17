from __future__ import annotations

import base64
import time
import urllib.parse

import jcs
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from awiki_open_server.protocol.anp_adapter import ANP_SDK_VERSION, REQUIRED_ANP_SDK_VERSION
from awiki_open_server.service_identity import (
    build_service_did_document,
    content_digest,
    generate_ed25519_private_key_pem,
    service_identity_from_settings,
    validate_origin_proof_structure,
    verify_peer_http_signature,
)
from awiki_open_server.shared.errors import Unauthorized


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _multikey(public_key: ed25519.Ed25519PublicKey) -> str:
    import base58

    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def _did_keypair_document(did: str, *, authorize: bool = True) -> tuple[ed25519.Ed25519PrivateKey, dict]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    key_id = f"{did}#key-1"
    document = {
        "id": did,
        "verificationMethod": [
            {
                "id": key_id,
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": _multikey(private_key.public_key()),
            }
        ],
        "service": [
            {
                "id": f"{did}#anp-message",
                "type": "ANPMessageService",
                "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                "serviceDid": "did:wba:awiki.info",
            }
        ],
    }
    if authorize:
        document["authentication"] = [key_id]
    return private_key, document


def _origin_proof(
    *,
    method: str,
    meta: dict,
    body: dict,
    private_key: ed25519.Ed25519PrivateKey,
    keyid: str | None = None,
) -> dict:
    target = meta["target"]
    keyid = keyid or f"{meta['sender_did']}#key-1"
    digest = content_digest(jcs.canonicalize({"method": method, "meta": meta, "body": body}))
    created = int(time.time())
    signature_input = (
        'sig1=("@method" "@target-uri" "content-digest");'
        f'created={created};expires={created + 300};keyid="{keyid}"'
    )
    proof_base = "\n".join(
        [
            f'"@method": {method}',
            f'"@target-uri": anp://{target["kind"]}/{urllib.parse.quote(target["did"], safe="-._~")}',
            f'"content-digest": {digest}',
            f'"@signature-params": {signature_input.split("=", 1)[1].strip()}',
        ]
    ).encode()
    return {
        "contentDigest": digest,
        "signatureInput": signature_input,
        "signature": f"sig1=:{_b64(private_key.sign(proof_base))}:",
    }


def test_protocol_adapter_requires_anp_sdk_088():
    assert ANP_SDK_VERSION == REQUIRED_ANP_SDK_VERSION == "0.8.9"


def test_service_http_signature_uses_anp_sdk_generation_and_verification():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document(
        "did:wba:rwiki.cn",
        "https://rwiki.cn/anp-im/rpc",
        private_key_pem,
    )
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
    )
    assert identity is not None

    body = b'{"jsonrpc":"2.0","method":"direct.send","params":{},"id":"1"}'
    base_headers = {"Content-Type": "application/json", "x-anp-source-service-did": "did:wba:rwiki.cn"}
    signature_headers = identity.sign_headers(
        "https://awiki.info/anp-im/rpc",
        "POST",
        base_headers,
        body,
    )

    assert signature_headers["Content-Digest"] == content_digest(body)
    assert verify_peer_http_signature(
        service_did_document=document,
        method="POST",
        url="https://awiki.info/anp-im/rpc",
        headers={**base_headers, **signature_headers},
        body=body,
    ) == "did:wba:rwiki.cn#key-1"


def test_service_http_signature_rejects_digest_mismatch():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document(
        "did:wba:rwiki.cn",
        "https://rwiki.cn/anp-im/rpc",
        private_key_pem,
    )
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
    )
    assert identity is not None
    body = b'{"ok":true}'
    headers = identity.sign_headers("https://awiki.info/anp-im/rpc", "POST", {"Content-Type": "application/json"}, body)

    with pytest.raises(Unauthorized) as error:
        verify_peer_http_signature(
            service_did_document=document,
            method="POST",
            url="https://awiki.info/anp-im/rpc",
            headers={**headers, "Content-Digest": content_digest(b"tampered")},
            body=body,
        )
    assert error.value.error_message == "content_digest_mismatch"


def test_service_http_signature_rejects_label_mismatch():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document(
        "did:wba:rwiki.cn",
        "https://rwiki.cn/anp-im/rpc",
        private_key_pem,
    )
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
    )
    assert identity is not None
    body = b'{"ok":true}'
    headers = identity.sign_headers("https://awiki.info/anp-im/rpc", "POST", {"Content-Type": "application/json"}, body)
    headers["Signature"] = headers["Signature"].replace("sig1=:", "sig2=:")

    with pytest.raises(Unauthorized) as error:
        verify_peer_http_signature(
            service_did_document=document,
            method="POST",
            url="https://awiki.info/anp-im/rpc",
            headers=headers,
            body=body,
        )
    assert error.value.error_message == "signature_label_mismatch"


def test_service_http_signature_rejects_malformed_signature_input():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document(
        "did:wba:rwiki.cn",
        "https://rwiki.cn/anp-im/rpc",
        private_key_pem,
    )
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
    )
    assert identity is not None
    body = b'{"ok":true}'
    headers = identity.sign_headers("https://awiki.info/anp-im/rpc", "POST", {"Content-Type": "application/json"}, body)
    headers["Signature-Input"] = "not-a-valid-signature-input"

    with pytest.raises(Unauthorized) as error:
        verify_peer_http_signature(
            service_did_document=document,
            method="POST",
            url="https://awiki.info/anp-im/rpc",
            headers=headers,
            body=body,
        )
    assert error.value.error_message == "invalid_peer_http_signature"


def test_service_http_signature_rejects_key_without_authentication_relationship():
    private_key_pem = generate_ed25519_private_key_pem()
    document = build_service_did_document(
        "did:wba:rwiki.cn",
        "https://rwiki.cn/anp-im/rpc",
        private_key_pem,
    )
    identity = service_identity_from_settings(
        service_did="did:wba:rwiki.cn",
        endpoint="https://rwiki.cn/anp-im/rpc",
        private_key_pem=private_key_pem,
    )
    assert identity is not None
    body = b'{"ok":true}'
    headers = identity.sign_headers("https://awiki.info/anp-im/rpc", "POST", {"Content-Type": "application/json"}, body)
    document_without_auth = {**document, "authentication": []}

    with pytest.raises(Unauthorized) as error:
        verify_peer_http_signature(
            service_did_document=document_without_auth,
            method="POST",
            url="https://awiki.info/anp-im/rpc",
            headers=headers,
            body=body,
        )
    assert error.value.error_message == "verification_method_not_found"


def test_origin_proof_verification_uses_anp_sdk_and_accepts_cli_shape():
    sender_did = "did:wba:awiki.info:users:alice"
    sender_key, sender_doc = _did_keypair_document(sender_did)
    meta = {
        "sender_did": sender_did,
        "target": {"kind": "agent", "did": "did:wba:rwiki.cn:users:bob"},
        "operation_id": "op-sdk",
        "message_id": "msg-sdk",
        "content_type": "text/plain",
    }
    body = {"text": "hello from sdk proof"}

    validate_origin_proof_structure(
        {"origin_proof": _origin_proof(method="direct.send", meta=meta, body=body, private_key=sender_key)},
        method="direct.send",
        meta=meta,
        body=body,
        sender_did_document=sender_doc,
    )


def test_origin_proof_rejects_unauthorized_authentication_method():
    sender_did = "did:wba:awiki.info:users:alice"
    sender_key, sender_doc = _did_keypair_document(sender_did, authorize=False)
    meta = {
        "sender_did": sender_did,
        "target": {"kind": "agent", "did": "did:wba:rwiki.cn:users:bob"},
    }
    body = {"text": "hello"}

    with pytest.raises(Unauthorized) as error:
        validate_origin_proof_structure(
            {"origin_proof": _origin_proof(method="direct.send", meta=meta, body=body, private_key=sender_key)},
            method="direct.send",
            meta=meta,
            body=body,
            sender_did_document=sender_doc,
        )
    assert error.value.error_message == "origin_proof_key_not_authorized"


def test_origin_proof_rejects_tampered_signature():
    sender_did = "did:wba:awiki.info:users:alice"
    sender_key, sender_doc = _did_keypair_document(sender_did)
    meta = {
        "sender_did": sender_did,
        "target": {"kind": "agent", "did": "did:wba:rwiki.cn:users:bob"},
    }
    body = {"text": "hello"}
    proof = _origin_proof(method="direct.send", meta=meta, body=body, private_key=sender_key)
    proof["signature"] = "sig1=:dGFtcGVyZWQ=:"

    with pytest.raises(Unauthorized) as error:
        validate_origin_proof_structure(
            {"origin_proof": proof},
            method="direct.send",
            meta=meta,
            body=body,
            sender_did_document=sender_doc,
        )
    assert error.value.error_message == "invalid_origin_proof_signature"
