from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from awiki_open_server.shared.errors import AwikiError, InvalidRequest, MethodNotFound


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


Handler = Callable[[dict[str, Any], Request], Any]


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Accept ANP meta/auth/body envelopes while keeping local flat RPC params."""
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


async def dispatch(payload: dict[str, Any], request: Request, handlers: dict[str, Handler]) -> dict[str, Any]:
    request_id = payload.get("id")
    try:
        rpc = JsonRpcRequest.model_validate(payload)
        if rpc.jsonrpc != "2.0":
            raise InvalidRequest("jsonrpc_must_be_2_0")
        handler = handlers.get(rpc.method)
        if handler is None:
            raise MethodNotFound("method_not_found", data={"method": rpc.method})
        result = await run_in_threadpool(handler, normalize_params(rpc.params), request)
        return ok(result, rpc.id)
    except AwikiError as exc:
        return err(exc, request_id)
    except Exception as exc:  # pragma: no cover - last line of defense
        return err(AwikiError("server_error", data={"detail": str(exc)}), request_id)
