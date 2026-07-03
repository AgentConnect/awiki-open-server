from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import json

from awiki_open_server.service_identity import load_private_key_setting


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_base_url: str
    service_did: str
    did_domain: str
    service_private_key_pem: str | None = None
    service_did_document_json: str | None = None
    allow_unsigned_peer_dev: bool = False
    im_rpc_path: str = "/im/rpc"
    anp_public_rpc_path: str = "/anp-im/rpc"
    ws_path: str = "/im/ws"
    object_upload_path: str = "/objects/upload"
    object_download_path: str = "/objects"
    did_resolver_base_urls: dict[str, str] | None = None
    did_verify_dev_code: str = "666666"
    enable_contact_verification_compat: bool = False
    contact_verification_dev_otp: str = "123456"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "awiki-open-server.sqlite3"

    @property
    def object_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def anp_service_endpoint(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.anp_public_rpc_path}"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("AWIKI_DATA_DIR", ".awiki-open-server")).resolve()
    public_base_url = os.environ.get("AWIKI_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    did_domain = os.environ.get("AWIKI_DID_DOMAIN", "localhost")
    service_did = os.environ.get("AWIKI_SERVICE_DID", f"did:wba:{did_domain}")
    service_private_key_pem = load_private_key_setting(
        os.environ.get("AWIKI_SERVICE_PRIVATE_KEY_PEM"),
        os.environ.get("AWIKI_SERVICE_PRIVATE_KEY_PATH"),
    )
    resolver_base_urls = _load_resolver_base_urls(os.environ.get("AWIKI_DID_RESOLVER_BASE_URLS"))
    return Settings(
        data_dir=data_dir,
        public_base_url=public_base_url,
        service_did=service_did,
        did_domain=did_domain,
        service_private_key_pem=service_private_key_pem,
        service_did_document_json=os.environ.get("AWIKI_SERVICE_DID_DOCUMENT_JSON"),
        allow_unsigned_peer_dev=os.environ.get("AWIKI_ALLOW_UNSIGNED_PEER_DEV", "").lower() in {"1", "true", "yes"},
        im_rpc_path=os.environ.get("AWIKI_IM_RPC_PATH", "/im/rpc"),
        anp_public_rpc_path=os.environ.get("AWIKI_ANP_PUBLIC_RPC_PATH", "/anp-im/rpc"),
        did_resolver_base_urls=resolver_base_urls,
        did_verify_dev_code=os.environ.get("AWIKI_DID_VERIFY_DEV_CODE") or os.environ.get("DEV_BYPASS_CODE") or "666666",
        enable_contact_verification_compat=os.environ.get("AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT", "").lower() in {"1", "true", "yes"},
        contact_verification_dev_otp=os.environ.get("AWIKI_CONTACT_VERIFICATION_DEV_OTP", "123456"),
    )


def _load_resolver_base_urls(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith("{"):
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("AWIKI_DID_RESOLVER_BASE_URLS must be an object")
        return {str(domain).lower(): str(base).rstrip("/") for domain, base in data.items()}
    mapping: dict[str, str] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError("AWIKI_DID_RESOLVER_BASE_URLS entries must be domain=base_url")
        domain, base_url = item.split("=", 1)
        mapping[domain.strip().lower()] = base_url.strip().rstrip("/")
    return mapping or None
