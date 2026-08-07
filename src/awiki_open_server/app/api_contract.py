from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import logging
import re
import threading
from typing import Any, Iterable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


API_CONTRACT_HEADER = "X-API-Contract"
CLIENT_VERSION_HEADER = "X-AWiki-Client-Version"
USER_SERVICE_CONTRACT = "user-service.v1"
USER_SERVICE_V1_PREFIX = "/user-service/v1"

_CLIENT_VERSION_RE = re.compile(
    r"^(?:awiki-me|awiki-cli|awiki-daemon)/"
    r"[0-9]{4}/"
    r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,3}"
    r"(?:\+(?:0|[1-9][0-9]*))?$"
)

_LEGACY_EXACT_PATHS = frozenset(
    {
        "/did-auth/rpc",
        "/user-service/did-auth/rpc",
        "/did-verify/rpc",
        "/user-service/did-verify/rpc",
        "/did/profile/rpc",
        "/user-service/did/profile/rpc",
        "/me/rpc",
        "/user-service/me/rpc",
        "/me",
        "/user-service/me",
        "/handle/rpc",
        "/user-service/handle/rpc",
        "/users/rpc",
        "/user-service/users/rpc",
        "/did/relationships/rpc",
        "/user-service/did/relationships/rpc",
        "/content/rpc",
        "/user-service/content/rpc",
        "/site/rpc",
        "/user-service/site/rpc",
        "/group/rpc",
        "/user-service/group/rpc",
        "/user-service/agent-registration/rpc",
        "/user-service/agent-inventory/rpc",
        "/user-service/personal-agent/rpc",
        "/user-service/message-agent/rpc",
        "/auth/sms-codes",
        "/user-service/auth/sms-codes",
        "/auth/sms",
        "/user-service/auth/sms",
        "/auth/email-send",
        "/user-service/auth/email-send",
        "/auth/email-status",
        "/user-service/auth/email-status",
        "/auth/phone-bind-send",
        "/user-service/auth/phone-bind-send",
        "/auth/phone-bind-verify",
        "/user-service/auth/phone-bind-verify",
        "/auth/token-refresh",
        "/user-service/auth/token-refresh",
        "/auth/token-verify",
        "/user-service/auth/token-verify",
        "/auth/verify",
        "/user-service/auth/verify",
        "/sessions/verify",
        "/user-service/sessions/verify",
        "/ws/tickets",
        "/user-service/ws/tickets",
        "/ws/tickets/verify",
        "/user-service/ws/tickets/verify",
        "/auth/ws-ticket/verify",
        "/user-service/auth/ws-ticket/verify",
    }
)
_LEGACY_PREFIXES = (
    "/profiles/",
    "/user-service/profiles/",
    "/users/",
    "/user-service/users/",
)


class ApiContractEntry(str, Enum):
    CANONICAL = "canonical"
    LEGACY = "legacy"


@dataclass(frozen=True)
class ApiContractRoute:
    contract: str
    entry: ApiContractEntry


def resolve_api_contract_route(method: str, path: str) -> ApiContractRoute | None:
    del method
    normalized = path.rstrip("/") or "/"
    if normalized == USER_SERVICE_V1_PREFIX or normalized.startswith(f"{USER_SERVICE_V1_PREFIX}/"):
        return ApiContractRoute(USER_SERVICE_CONTRACT, ApiContractEntry.CANONICAL)
    if normalized in _LEGACY_EXACT_PATHS or normalized.startswith(_LEGACY_PREFIXES):
        return ApiContractRoute(USER_SERVICE_CONTRACT, ApiContractEntry.LEGACY)
    return None


class ApiContractMetrics:
    def __init__(self) -> None:
        self._contract: Counter[tuple[str, str]] = Counter()
        self._client: Counter[tuple[str, str]] = Counter()
        self._lock = threading.Lock()

    def record_contract(self, route: ApiContractRoute, outcome: str) -> None:
        with self._lock:
            self._contract[(route.entry.value, outcome)] += 1

    def record_client_version(self, surface: str, outcome: str) -> None:
        with self._lock:
            self._client[(surface, outcome)] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                "api_contract": {
                    f"{entry}:{outcome}": count
                    for (entry, outcome), count in sorted(self._contract.items())
                },
                "client_version": {
                    f"{surface}:{outcome}": count
                    for (surface, outcome), count in sorted(self._client.items())
                },
            }


def _client_version_values(request: Request) -> list[str]:
    values: list[str] = []
    for name, value in request.scope.get("headers", []):
        if name.lower() != b"x-awiki-client-version":
            continue
        try:
            values.append(value.decode("ascii"))
        except UnicodeDecodeError:
            values.append("")
    return values


def _client_version_outcome(values: list[str]) -> str:
    if not values:
        return "missing"
    if len(values) != 1:
        return "duplicate"
    return "valid" if _CLIENT_VERSION_RE.fullmatch(values[0]) else "invalid"


class ApiContractMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        metrics: ApiContractMetrics,
        local_message_paths: Iterable[str] = (),
    ) -> None:
        super().__init__(app)
        self._metrics = metrics
        self._local_message_paths = frozenset(local_message_paths)
        self._logger = logging.getLogger("awiki_open_server.api_contract")

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        route = resolve_api_contract_route(request.method, request.url.path)
        normalized_path = request.url.path.rstrip("/") or "/"
        client_surface: str | None = None
        if route is not None:
            client_surface = "user_service"
        elif normalized_path in self._local_message_paths:
            client_surface = "message_service"

        client_outcome: str | None = None
        if client_surface is not None:
            client_outcome = _client_version_outcome(_client_version_values(request))

        response = await call_next(request)

        if route is not None:
            response.headers[API_CONTRACT_HEADER] = route.contract
            outcome = (
                "service_error"
                if response.status_code >= 500
                else "request_error"
                if response.status_code >= 400
                else "success"
            )
            self._metrics.record_contract(route, outcome)

        if client_surface is not None and client_outcome is not None:
            self._metrics.record_client_version(client_surface, client_outcome)
            if client_outcome in {"duplicate", "invalid"}:
                self._logger.warning(
                    "invalid client version metadata surface=%s outcome=%s",
                    client_surface,
                    client_outcome,
                )
        return response


__all__ = [
    "API_CONTRACT_HEADER",
    "CLIENT_VERSION_HEADER",
    "USER_SERVICE_CONTRACT",
    "USER_SERVICE_V1_PREFIX",
    "ApiContractEntry",
    "ApiContractMetrics",
    "ApiContractMiddleware",
    "ApiContractRoute",
    "resolve_api_contract_route",
]
