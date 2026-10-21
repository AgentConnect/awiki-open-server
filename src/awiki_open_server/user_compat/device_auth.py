"""Local single-device authentication; no device enrollment or recovery API."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sqlite3
import tempfile
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from awiki_open_server.protocol.anp_adapter import SingleDeviceManifest
from awiki_open_server.service_identity import generate_ed25519_private_key_pem
from awiki_open_server.shared.errors import Unauthorized
from awiki_open_server.shared.ids import new_id


@dataclass(frozen=True)
class DeviceAccount:
    did: str
    account_id: str
    device_id: str
    signing_key_id: str
    root_key_id: str
    key_fingerprint: str
    auth_generation: int = 1


def device_account(did: str, manifest: SingleDeviceManifest) -> DeviceAccount:
    return DeviceAccount(
        did=did, account_id=f"user-{hashlib.sha256(did.encode()).hexdigest()[:24]}",
        device_id=manifest.device_id, signing_key_id=manifest.signing_key_id,
        root_key_id=manifest.root_key_id, key_fingerprint=manifest.key_fingerprint,
    )


def bind_device_account(conn, account: DeviceAccount, *, create: bool = False) -> DeviceAccount:
    if create:
        conn.execute(
            """INSERT OR IGNORE INTO single_device_accounts(
                owner_did, account_id, device_id, signing_key_id, root_key_id,
                key_fingerprint, auth_generation
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (account.did, account.account_id, account.device_id, account.signing_key_id,
             account.root_key_id, account.key_fingerprint, account.auth_generation),
        )
    row = conn.execute("SELECT * FROM single_device_accounts WHERE owner_did = ?", (account.did,)).fetchone()
    if row is None or any(row[column] != value for column, value in (
        ("account_id", account.account_id), ("device_id", account.device_id),
        ("signing_key_id", account.signing_key_id), ("root_key_id", account.root_key_id),
        ("key_fingerprint", account.key_fingerprint), ("auth_generation", account.auth_generation),
    )):
        raise Unauthorized("device_authorization_invalid")
    return account


def consume_auth_nonce(conn, key_id: str, signature_metadata: dict[str, Any]) -> None:
    params = signature_metadata.get("params")
    if not isinstance(params, dict):
        raise Unauthorized("invalid_http_signature")
    nonce, created, expires = params.get("nonce"), params.get("created"), params.get("expires")
    now = int(datetime.now(timezone.utc).timestamp())
    if (
        not isinstance(nonce, str) or not nonce.strip() or len(nonce) > 256
        or type(created) is not int or type(expires) is not int
        or expires < created or expires > created + 600
        or created > now + 30 or now > expires + 30
    ):
        raise Unauthorized("invalid_http_signature")
    digest = hashlib.sha256(json.dumps([key_id, nonce], separators=(",", ":")).encode()).hexdigest()
    conn.execute("DELETE FROM single_device_auth_nonces WHERE expires_at < ?", (now,))
    try:
        conn.execute("INSERT INTO single_device_auth_nonces(nonce_hash, expires_at) VALUES (?, ?)", (digest, expires + 30))
    except sqlite3.IntegrityError as exc:
        raise Unauthorized("signature_replayed") from exc


def load_token_signing_key(data_dir: Path, service_private_key_pem: str | None) -> Ed25519PrivateKey:
    if service_private_key_pem:
        pem = service_private_key_pem.encode()
    else:
        path = data_dir / "auth-token-key.pem"
        if not path.exists():
            # Publish a completely written file atomically; never replace an
            # existing key when two startup attempts share the same data dir.
            with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".auth-key-", delete=False) as tmp:
                temporary = Path(tmp.name)
                try:
                    os.fchmod(tmp.fileno(), 0o600)
                    tmp.write(generate_ed25519_private_key_pem().encode())
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    try:
                        os.link(temporary, path)
                    except FileExistsError:
                        pass
                finally:
                    temporary.unlink(missing_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError("auth token key must be a protected regular file")
            pem = handle.read()
    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("auth token key must be Ed25519")
    return key


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(raw) != value:
        raise ValueError("non-canonical token encoding")
    return raw


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate token claim")
        result[key] = value
    return result


def _binding_claims(account: DeviceAccount) -> dict[str, Any]:
    return {
        "iss": "user-service", "aud": ["awiki-user-service", "awiki-message-service"],
        "sub": account.did, "type": "access", "purpose": "awiki.device.access.v1",
        "did": account.did, "user_id": account.account_id, "device_id": account.device_id,
        "key_id": account.signing_key_id, "auth_generation": account.auth_generation,
        "scopes": ["device:manage", "device:read", "message:connect"],
    }


def issue_device_token(account: DeviceAccount, key: Ed25519PrivateKey, ttl_seconds: int) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {**_binding_claims(account), "iat": now, "nbf": now, "exp": now + ttl_seconds, "jti": new_id("jti")}
    header = _b64(b'{"alg":"EdDSA","typ":"JWT"}')
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signed = f"{header}.{payload}"
    return f"{signed}.{_b64(key.sign(signed.encode()))}"


def verified_device_token_subject(token: str, key: Ed25519PrivateKey) -> str:
    try:
        header, payload, signature = token.split(".")
        if json.loads(_decode(header), object_pairs_hook=_unique_members) != {"alg": "EdDSA", "typ": "JWT"}:
            raise ValueError("wrong token algorithm")
        key.public_key().verify(_decode(signature), f"{header}.{payload}".encode())
        claims = json.loads(_decode(payload), object_pairs_hook=_unique_members)
        if not isinstance(claims, dict) or not isinstance(claims.get("did"), str) or not claims["did"]:
            raise ValueError("missing token subject")
        return claims["did"]
    except (ValueError, TypeError, UnicodeError, InvalidSignature) as exc:
        raise Unauthorized("device_authorization_invalid") from exc


def validate_device_token(token: str, account: DeviceAccount, key: Ed25519PrivateKey) -> None:
    try:
        header, payload, signature = token.split(".")
        if json.loads(_decode(header), object_pairs_hook=_unique_members) != {"alg": "EdDSA", "typ": "JWT"}:
            raise ValueError("wrong token algorithm")
        key.public_key().verify(_decode(signature), f"{header}.{payload}".encode())
        claims = json.loads(_decode(payload), object_pairs_hook=_unique_members)
        expected = _binding_claims(account)
        if not isinstance(claims, dict) or set(claims) != set(expected) | {"iat", "nbf", "exp", "jti"}:
            raise ValueError("wrong token claims")
        if any(claims[field] != value for field, value in expected.items()):
            raise ValueError("wrong token binding")
        if type(claims["auth_generation"]) is not int or any(type(claims[field]) is not int for field in ("iat", "nbf", "exp")):
            raise ValueError("wrong token times or generation")
        now = int(datetime.now(timezone.utc).timestamp())
        if claims["nbf"] != claims["iat"] or claims["iat"] > now + 30 or claims["exp"] <= max(now, claims["iat"]):
            raise ValueError("expired or future token")
        if not isinstance(claims["jti"], str) or not claims["jti"].strip():
            raise ValueError("token identifier required")
    except (ValueError, TypeError, UnicodeError, InvalidSignature) as exc:
        raise Unauthorized("device_authorization_invalid") from exc
