from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from awiki_open_server.protocol.registry import METHOD_CONTRACTS, MethodContract
from awiki_open_server.shared.errors import (
    AwikiError,
    Conflict,
    InvalidParams,
    InvalidRequest,
    MethodNotFound,
    NotFound,
    NotSupported,
    Unauthorized,
)


class JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


Handler = Callable[[dict[str, Any], Request], Any]
Surface = Literal["local", "public"]

_LOGGER = logging.getLogger("awiki_open_server.jsonrpc")
_ANP_PARAM_KEYS = frozenset({"meta", "auth", "body"})
_ANP_META_KEYS = frozenset(
    {
        "anp_version",
        "profile",
        "security_profile",
        "sender_did",
        "target",
        "operation_id",
        "message_id",
        "created_at",
        "content_type",
        "trace",
    }
)


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Translate one canonical envelope into the existing domain command shape."""

    meta = params.get("meta")
    body = params.get("body")
    if not isinstance(body, dict):
        return params

    normalized = dict(body)
    if isinstance(meta, dict):
        normalized["_anp_meta"] = meta
    normalized["_anp_body"] = body
    if isinstance(params.get("auth"), dict):
        normalized["_anp_auth"] = params["auth"]
    if isinstance(params.get("client"), dict):
        normalized["_anp_client"] = params["client"]

    for key, value in params.items():
        if key not in {"meta", "auth", "body", "client"} and key not in normalized:
            normalized[key] = value

    if not isinstance(meta, dict):
        return normalized

    for key in ["sender_did", "message_id", "operation_id", "content_type"]:
        if key in meta and key not in normalized:
            normalized[key] = meta[key]

    target = meta.get("target")
    if isinstance(target, dict):
        target_did = target.get("did")
        if target_did:
            if target.get("kind") == "group" and "group_did" not in normalized:
                normalized["group_did"] = target_did
            elif "recipient_did" not in normalized:
                normalized["recipient_did"] = target_did

    return normalized


def ok(result: Any, request_id: str | int | None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "result": result, "id": request_id}


def err(exc: AwikiError, request_id: str | int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": exc.code, "message": exc.error_message}
    if exc.data:
        payload["data"] = exc.data
    return {"jsonrpc": "2.0", "error": payload, "id": request_id}


def standard_error(
    code: int,
    message: str,
    request_id: str | None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "error": error, "id": request_id}


def anp_error(
    code: int,
    anp_code: str,
    request_id: str | None,
    *,
    message: str | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return standard_error(
        code,
        message or anp_code,
        request_id,
        data={
            "anp_code": anp_code,
            "retryable": retryable,
            "details": details or {},
        },
    )


def parse_error() -> dict[str, Any]:
    return standard_error(-32700, "Parse error", None)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_request_id(payload: Mapping[str, Any], contract: MethodContract | None) -> tuple[str | None, dict[str, Any] | None]:
    has_id = "id" in payload
    request_id = payload.get("id")
    if contract is not None and contract.rpc_kind == "notification":
        if has_id:
            return None, standard_error(
                -32600,
                "Invalid Request",
                request_id if isinstance(request_id, str) else None,
                data={"reason": "anp.notification_must_not_have_id"},
            )
        return None, None
    if not _nonempty_string(request_id):
        return None, anp_error(
            1000,
            "anp.invalid_request_id",
            None,
            details={"expected": "non-empty string"},
        )
    return str(request_id), None


def _strict_envelope(
    method: str,
    params: Any,
    contract: MethodContract,
    request_id: str | None,
    *,
    surface: Surface,
) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"expected": "object"},
        )
    allowed_param_keys = _ANP_PARAM_KEYS | ({"client"} if surface == "local" else set())
    extra = set(params) - allowed_param_keys
    if extra:
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"unexpected_fields": sorted(extra)},
        )

    meta = params.get("meta")
    body = params.get("body")
    auth = params.get("auth")
    if not isinstance(meta, dict) or not isinstance(body, dict):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"required": ["meta", "body"]},
        )
    if auth is not None and not isinstance(auth, dict):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "auth", "expected": "object"},
        )
    if "client" in params and not isinstance(params.get("client"), dict):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "client", "expected": "object"},
        )
    extra_meta = set(meta) - _ANP_META_KEYS
    if extra_meta:
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "meta", "unexpected_fields": sorted(extra_meta)},
        )

    profile = meta.get("profile")
    accepted_profiles = (contract.profile, *contract.alternate_profiles)
    if profile not in accepted_profiles:
        return anp_error(
            1001,
            "anp.unsupported_profile",
            request_id,
            details={"method": method, "expected": list(accepted_profiles), "actual": profile},
        )
    security_profile = meta.get("security_profile")
    if security_profile != "transport-protected":
        return anp_error(
            1002,
            "anp.unsupported_security_profile",
            request_id,
            details={"actual": security_profile},
        )
    if contract.sender_required and not _nonempty_string(meta.get("sender_did")):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "meta.sender_did"},
        )
    if contract.operation_required and not _nonempty_string(meta.get("operation_id")):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "meta.operation_id"},
        )
    if contract.message_required and not _nonempty_string(meta.get("message_id")):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "meta.message_id"},
        )
    if contract.content_type_required and not _nonempty_string(meta.get("content_type")):
        return anp_error(
            1003,
            "anp.invalid_params_shape",
            request_id,
            details={"field": "meta.content_type"},
        )

    target = meta.get("target")
    if contract.target_kind is None:
        if target is not None:
            return anp_error(
                1014,
                "anp.invalid_target_binding",
                request_id,
                details={"expected": "endpoint-local"},
            )
    elif (
        not isinstance(target, dict)
        or target.get("kind") != contract.target_kind
        or not _nonempty_string(target.get("did"))
    ):
        return anp_error(
            1014,
            "anp.invalid_target_binding",
            request_id,
            details={"expected_kind": contract.target_kind},
        )
    return None


def _strict_business_error(exc: AwikiError, request_id: str | None) -> dict[str, Any]:
    details = dict(exc.data)
    if isinstance(exc, Unauthorized):
        return anp_error(1005, "anp.unauthorized", request_id, message=exc.error_message, details=details)
    if isinstance(exc, Conflict):
        return anp_error(1008, "anp.idempotency_conflict", request_id, message=exc.error_message, details=details)
    if isinstance(exc, NotFound):
        return anp_error(1007, "anp.target_not_found", request_id, message=exc.error_message, details=details)
    if isinstance(exc, NotSupported):
        return anp_error(1001, "anp.not_supported", request_id, message=exc.error_message, details=details)
    if isinstance(exc, InvalidParams):
        message = exc.error_message
        if "not_local" in message or "not_found" in message:
            return anp_error(1007, "anp.target_not_found", request_id, message=message, details=details)
        if "profile" in message:
            return anp_error(1001, "anp.unsupported_profile", request_id, message=message, details=details)
        if "security" in message or "proof" in message:
            return anp_error(1013, "anp.invalid_security_binding", request_id, message=message, details=details)
        if "target" in message:
            return anp_error(1014, "anp.invalid_target_binding", request_id, message=message, details=details)
        if "content_type" in message:
            return anp_error(1009, "anp.unsupported_content_type", request_id, message=message, details=details)
        return standard_error(-32602, message, request_id, data={"reason": message, "details": details})
    return anp_error(1010, "anp.delivery_rejected", request_id, message=exc.error_message, details=details)


async def dispatch(
    payload: Any,
    request: Request,
    handlers: dict[str, Handler],
    *,
    strict_anp: bool = False,
    surface: Surface = "local",
) -> dict[str, Any] | None:
    if not strict_anp:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        try:
            rpc = JsonRpcRequest.model_validate(payload)
            if rpc.jsonrpc != "2.0":
                raise InvalidRequest("jsonrpc_must_be_2_0")
            handler = handlers.get(rpc.method)
            if handler is None:
                raise MethodNotFound("method_not_found", data={"method": rpc.method})
            result = await run_in_threadpool(handler, normalize_params(rpc.params), request)
            return ok(result, rpc.id)
        except ValidationError:
            return err(InvalidRequest("invalid_request"), request_id)
        except AwikiError as exc:
            return err(exc, request_id)
        except Exception as exc:  # pragma: no cover - last line of defense
            return err(AwikiError("server_error", data={"detail": str(exc)}), request_id)

    if isinstance(payload, list):
        return anp_error(1004, "anp.batch_not_supported", None)
    if not isinstance(payload, dict):
        return standard_error(-32600, "Invalid Request", None)
    if set(payload) - {"jsonrpc", "method", "params", "id"}:
        request_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        return standard_error(-32600, "Invalid Request", request_id)
    if payload.get("jsonrpc") != "2.0" or not _nonempty_string(payload.get("method")):
        request_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        return standard_error(-32600, "Invalid Request", request_id)

    method = str(payload["method"])
    contract = METHOD_CONTRACTS.get(method)
    if contract is None or surface not in contract.surfaces or method not in handlers:
        request_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        return standard_error(-32601, "method_not_found", request_id)

    request_id, id_error = _strict_request_id(payload, contract)
    if id_error is not None:
        return id_error
    if not contract.advertised:
        return anp_error(
            1001,
            "anp.not_supported",
            request_id,
            message="not_supported",
            details={"method": method, "profile": contract.profile},
        )
    envelope_error = _strict_envelope(method, payload.get("params"), contract, request_id, surface=surface)
    if envelope_error is not None:
        return envelope_error

    is_notification = contract.rpc_kind == "notification"
    try:
        params = normalize_params(payload["params"])
        result = await run_in_threadpool(handlers[method], params, request)
        if is_notification:
            return None
        return ok(result, request_id)
    except AwikiError as exc:
        if is_notification:
            _LOGGER.warning("ANP notification rejected method=%s reason=%s", method, exc.error_message)
            return None
        return _strict_business_error(exc, request_id)
    except Exception:
        _LOGGER.exception("ANP handler failed method=%s", method)
        if is_notification:
            return None
        return standard_error(-32603, "Internal error", request_id)


__all__ = [
    "JsonRpcRequest",
    "anp_error",
    "dispatch",
    "err",
    "normalize_params",
    "ok",
    "parse_error",
    "standard_error",
]
