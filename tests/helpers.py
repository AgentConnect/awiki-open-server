from __future__ import annotations

import base64
from datetime import datetime, timezone
import time
import urllib.parse

import jcs
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from awiki_open_server.service_identity import content_digest
from tests.conftest import rpc


async def register(client, handle: str):
    data = await rpc(client, "/did-auth/rpc", "register", {"handle": handle})
    return data["result"]["did"], data["result"]["token"]


async def register_with_key(client, handle: str):
    did = f"did:wba:testserver:users:{handle}"
    private_key, document = did_keypair_document(did)
    data = await rpc(client, "/did-auth/rpc", "register", {"handle": handle, "did_document": document})
    return data["result"]["did"], data["result"]["token"], private_key, document


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _multikey(public_key: ed25519.Ed25519PublicKey) -> str:
    import base58

    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def did_keypair_document(did: str) -> tuple[ed25519.Ed25519PrivateKey, dict]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    key_id = f"{did}#key-1"
    return private_key, {
        "id": did,
        "verificationMethod": [
            {
                "id": key_id,
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": _multikey(private_key.public_key()),
            }
        ],
        "authentication": [key_id],
        "service": [
            {
                "id": f"{did}#anp-message",
                "type": "ANPMessageService",
                "serviceEndpoint": "https://awiki.info/anp-im/rpc",
                "serviceDid": "did:wba:awiki.info",
                "profiles": ["anp.direct.base.v1"],
                "securityProfiles": ["transport-protected"],
            }
        ],
    }


def origin_proof(meta: dict, body: dict, private_key: ed25519.Ed25519PrivateKey | None = None, method: str = "direct.send") -> dict:
    private_key = private_key or ed25519.Ed25519PrivateKey.generate()
    key_id = f"{meta['sender_did']}#key-1"
    digest = content_digest(jcs.canonicalize({"method": method, "meta": meta, "body": body}))
    created = int(time.time())
    signature_input = (
        'sig1=("@method" "@target-uri" "content-digest");'
        f'created={created};expires={created + 300};keyid="{key_id}"'
    )
    target = meta["target"]
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


def remote_direct_result(payload: dict, *, target_did: str | None = None, overrides: dict | None = None) -> dict:
    meta = payload["params"]["meta"]
    result = {
        "accepted": True,
        "delivery_state": "accepted",
        "final_acceptance": True,
        "message_id": meta["message_id"],
        "operation_id": meta["operation_id"],
        "target_did": target_did or meta["target"]["did"],
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }
    if overrides:
        result.update(overrides)
    return {"jsonrpc": "2.0", "result": result, "id": payload["id"]}
