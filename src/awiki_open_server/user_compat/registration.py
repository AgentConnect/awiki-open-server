from __future__ import annotations

from collections import OrderedDict
import hashlib
import math
import threading
import time
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from awiki_open_server.protocol.anp_adapter import valid_handle_local_part
from awiki_open_server.shared.errors import AwikiError, InvalidParams


class RegistrationCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)

    handle: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=253)
    check_invite: bool = False
    invite_code: str | None = Field(default=None, max_length=256, repr=False)
    phone: str | None = Field(default=None, max_length=32, repr=False)
    email: str | None = Field(default=None, max_length=254, repr=False)


class RegistrationCheckRateLimited(AwikiError):
    code = -32005


class RegistrationCheckLimiter:
    """Bound public name checks using the trusted ASGI peer, never forwarded headers."""

    def __init__(self) -> None:
        self._clients: OrderedDict[str, tuple[float, int, float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, peer: str) -> None:
        now = time.monotonic()
        key = hashlib.sha256(peer.encode()).hexdigest()
        with self._lock:
            while self._clients and next(iter(self._clients.values()))[2] <= now - 60:
                self._clients.popitem(last=False)
            previous = self._clients.pop(key, None)
            start, count, _ = previous or (now, 0, now)
            if now >= start + 60:
                start, count = now, 0
            if count >= 20 or (previous is None and len(self._clients) >= 10_000):
                if previous is not None:
                    self._clients[key] = (start, count, now)
                raise RegistrationCheckRateLimited(
                    "registration_check_rate_limited",
                    data={"code": "registration_check_rate_limited", "retry_after_seconds": max(1, math.ceil(start + 60 - now))},
                )
            self._clients[key] = (start, count + 1, now)


def registration_check(params: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        check = RegistrationCheckRequest.model_validate(params)
    except ValidationError:
        raise InvalidParams("registration_check_invalid_params") from None
    request.app.state.registration_check_limiter.check(request.client.host if request.client else "unknown")
    handle = check.handle.strip().removeprefix("@").lower()
    domain = check.domain.strip().rstrip(".").lower()
    result = {
        "handle": handle, "domain": domain, "full_handle": f"{handle}.{domain}",
        "decision": "unavailable", "invite_required": False, "invite_kind": None,
        "invite_status": "not_required", "reason": None,
    }
    if domain != request.app.state.settings.did_domain.lower():
        result["reason"] = "domain_not_supported"
        return result
    if not valid_handle_local_part(handle):
        result["reason"] = "handle_invalid"
        return result
    with request.app.state.store.connect() as conn:
        row = conn.execute(
            """SELECT u.revoked_at, d.status AS document_status, d.revoked_at AS document_revoked_at
               FROM users u LEFT JOIN did_documents d ON d.did=u.did WHERE lower(u.handle)=?""",
            (f"{handle}@{domain}",),
        ).fetchone()
    if row is None:
        result["decision"] = "register"
    elif row["revoked_at"] is None and row["document_revoked_at"] is None and row["document_status"] == "active":
        result["decision"] = "existing"
    else:
        result["reason"] = "handle_unavailable"
    return result


def server_info(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    registration_domain = request.query_params.get("registration_domain", settings.did_domain).strip().lower().rstrip(".")
    local = registration_domain == settings.did_domain.lower()
    return {
        "schema_version": 1,
        "service": {"kind": "awiki-open-server", "name": "AWiki Open Server"},
        "services": {
            "model_proxy": {"enabled": False, "base_url": None},
            "guest_gateway": {"enabled": False, "base_url": None},
        },
        "identity": {
            "did_methods": [{"id": "wba", "create": local}, {"id": "web", "create": False}],
            "handle_registration": {
                "enabled": local, "default_method": "phone" if local else None,
                "availability": "open" if local else "disabled",
                "methods": [{"id": "phone", "enabled": True, "verification": {"required": False, "type": "none"}}] if local else [],
            },
            "handle_recovery": {"enabled": False, "methods": []},
        },
        "agents": {
            "skill_onboarding": {"enabled": False, "protocol_version": 1},
            "skill_group_membership": {"enabled": False, "protocol_version": 1, "required_capability": "group_membership_v1"},
        },
        "deployment": {"did_domain": settings.did_domain},
    }
