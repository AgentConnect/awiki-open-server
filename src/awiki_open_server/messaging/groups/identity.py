from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from awiki_open_server.protocol.anp_adapter import (
    AnpProtocolError,
    canonicalize_binding_generation,
    compare_binding_generations,
    create_group_did_identity,
    normalize_wns_handle,
    sign_group_receipt,
    verify_wns_handle_binding,
)
from awiki_open_server.shared.errors import InvalidParams


@dataclass(frozen=True)
class VerifiedHandleBinding:
    handle: str
    did: str
    binding_generation: str


def resolve_handle_binding(handle: str) -> VerifiedHandleBinding:
    try:
        normalized = normalize_wns_handle(handle)
        result = verify_wns_handle_binding(normalized)
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code, data={"detail": exc.detail}) from exc
    if not getattr(result, "is_valid", False):
        raise InvalidParams(
            "group_handle_binding_invalid",
            data={"detail": getattr(result, "error_message", None) or "binding verification failed"},
        )
    did = getattr(result, "did", None)
    generation = getattr(result, "binding_generation", None)
    if not isinstance(did, str) or not did:
        raise InvalidParams("group_handle_binding_did_missing")
    try:
        canonical_generation = canonicalize_binding_generation(generation)
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code, data={"detail": exc.detail}) from exc
    return VerifiedHandleBinding(normalized, did, canonical_generation)


def binding_generation_is_newer(candidate: str, previous: str) -> bool:
    try:
        return compare_binding_generations(candidate, previous) > 0
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code, data={"detail": exc.detail}) from exc


def generate_group_identity(
    *,
    hostname: str,
    group_id: str,
    service_endpoint: str,
    service_did: str,
) -> tuple[dict[str, Any], str]:
    try:
        return create_group_did_identity(
            hostname=hostname,
            group_id=group_id,
            service_endpoint=service_endpoint,
            service_did=service_did,
        )
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code, data={"detail": exc.detail}) from exc


def persist_group_private_key(key_dir: Path, group_id: str, private_key_pem: str) -> Path:
    key_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    path = key_dir / f"{group_id}.pem"
    if path.exists():
        raise InvalidParams("group_key_already_exists")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(private_key_pem)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def sign_receipt(receipt: dict[str, Any], key_reference: str) -> dict[str, Any]:
    try:
        pem = Path(key_reference).read_text(encoding="ascii")
        key = load_pem_private_key(pem.encode("ascii"), password=None)
    except Exception as exc:
        raise InvalidParams("group_receipt_key_unavailable") from exc
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise InvalidParams("group_receipt_key_must_be_ed25519")
    try:
        return sign_group_receipt(
            receipt,
            private_key=key,
            verification_method=f"{receipt['group_did']}#key-1",
        )
    except AnpProtocolError as exc:
        raise InvalidParams(exc.code, data={"detail": exc.detail}) from exc
