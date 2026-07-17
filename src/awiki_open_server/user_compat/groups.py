from __future__ import annotations

from typing import Any, Callable

from fastapi import Request

from awiki_open_server.messaging.groups import (
    hosted_group_create,
    hosted_group_get_info,
    hosted_group_join,
    hosted_group_leave,
    hosted_group_list_members,
    hosted_group_list_messages,
    hosted_group_remove,
    hosted_group_send,
    hosted_group_update_policy,
    hosted_group_update_profile,
)
from awiki_open_server.shared.errors import InvalidParams, NotSupported


def _group_id(params: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(params)
    if "group_did" not in mapped and isinstance(mapped.get("group_id"), str):
        mapped["group_did"] = mapped["group_id"]
    return mapped


def group_get(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return hosted_group_get_info(_group_id(params), request)


def group_update(params: dict[str, Any], request: Request) -> dict[str, Any]:
    body = params.get("_anp_body")
    if not isinstance(body, dict):
        raise NotSupported("legacy_group_write_requires_standard_origin_proof")
    has_profile = isinstance(body.get("group_profile_patch"), dict)
    has_policy = isinstance(body.get("group_policy_patch"), dict)
    if has_profile == has_policy:
        raise InvalidParams("legacy_group_update_requires_one_standard_patch")
    if has_profile:
        return hosted_group_update_profile(params, request)
    return hosted_group_update_policy(params, request)


def group_set_join_enabled(params: dict[str, Any], request: Request) -> dict[str, Any]:
    body = params.get("_anp_body")
    if not isinstance(body, dict) or not isinstance(body.get("group_policy_patch"), dict):
        raise NotSupported("legacy_group_write_requires_standard_origin_proof")
    return hosted_group_update_policy(params, request)


def group_join(params: dict[str, Any], request: Request) -> dict[str, Any]:
    if any(key in params for key in ("passcode", "join_code", "join_token", "invite_token")):
        raise NotSupported("legacy_group_join_code_not_supported")
    return hosted_group_join(_group_id(params), request)


def group_leave(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return hosted_group_leave(_group_id(params), request)


def group_remove(params: dict[str, Any], request: Request) -> dict[str, Any]:
    mapped = _group_id(params)
    if "member_did" not in mapped and isinstance(mapped.get("user_did"), str):
        mapped["member_did"] = mapped["user_did"]
    return hosted_group_remove(mapped, request)


def group_list_members(params: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    return hosted_group_list_members(_group_id(params), request)


def group_post_message(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return hosted_group_send(_group_id(params), request)


def group_list_messages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    return hosted_group_list_messages(_group_id(params), request)


def join_code_not_supported(_: dict[str, Any], __: Request) -> None:
    raise NotSupported("group_join_code_not_supported")


GROUP_COMPAT_HANDLERS: dict[str, Callable[[dict[str, Any], Request], Any]] = {
    "create": hosted_group_create,
    "get": group_get,
    "update": group_update,
    "refresh_join_code": join_code_not_supported,
    "get_join_code": join_code_not_supported,
    "set_join_enabled": group_set_join_enabled,
    "join": group_join,
    "leave": group_leave,
    "kick_member": group_remove,
    "list_members": group_list_members,
    "post_message": group_post_message,
    "list_messages": group_list_messages,
}


__all__ = ["GROUP_COMPAT_HANDLERS"]
