from __future__ import annotations

from datetime import datetime, timezone
import secrets


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
