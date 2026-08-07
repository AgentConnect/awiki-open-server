from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Surface = Literal["local", "public"]
RpcKind = Literal["request", "notification"]

STANDARD_PROFILES = (
    "anp.core.binding.v1",
    "anp.identity.discovery.v1",
    "anp.direct.base.v1",
    "anp.group.base.v1",
    "anp.attachment.v1",
    "anp.federation.relay.v1",
)
LOCAL_PROFILES = (
    "anp.inbox.local.v1",
    "anp.direct.local.v1",
    "anp.group.local.v1",
    "anp.sync.local.v1",
    "anp.sync.local.v2",
    "anp.read_state.local.v1",
)


@dataclass(frozen=True)
class MethodContract:
    method: str
    profile: str
    surfaces: frozenset[Surface]
    rpc_kind: RpcKind = "request"
    target_kind: Literal["agent", "group", "service"] | None = None
    sender_required: bool = True
    operation_required: bool = True
    message_required: bool = False
    content_type_required: bool = False
    principal: Literal["anonymous_or_peer", "local_bearer", "local_bearer_or_verified_peer"] = "local_bearer_or_verified_peer"
    origin_proof_required: bool = False
    receipt_proof_required: bool = False
    wns_binding_required: bool = False
    alternate_profiles: tuple[str, ...] = ()
    advertised: bool = True


def _contract(
    method: str,
    profile: str,
    *,
    surfaces: tuple[Surface, ...] = ("local", "public"),
    rpc_kind: RpcKind = "request",
    target_kind: Literal["agent", "group", "service"] | None = None,
    sender_required: bool = True,
    operation_required: bool = True,
    message_required: bool = False,
    content_type_required: bool = False,
    principal: Literal["anonymous_or_peer", "local_bearer", "local_bearer_or_verified_peer"] = "local_bearer_or_verified_peer",
    origin_proof_required: bool = False,
    receipt_proof_required: bool = False,
    wns_binding_required: bool = False,
    alternate_profiles: tuple[str, ...] = (),
    advertised: bool = True,
) -> MethodContract:
    return MethodContract(
        method=method,
        profile=profile,
        surfaces=frozenset(surfaces),
        rpc_kind=rpc_kind,
        target_kind=target_kind,
        sender_required=sender_required,
        operation_required=operation_required,
        message_required=message_required,
        content_type_required=content_type_required,
        principal=principal,
        origin_proof_required=origin_proof_required,
        receipt_proof_required=receipt_proof_required,
        wns_binding_required=wns_binding_required,
        alternate_profiles=alternate_profiles,
        advertised=advertised,
    )


METHOD_CONTRACTS = {
    item.method: item
    for item in [
        _contract(
            "anp.get_capabilities",
            "anp.core.binding.v1",
            target_kind=None,
            sender_required=False,
            principal="anonymous_or_peer",
        ),
        _contract(
            "direct.send",
            "anp.direct.base.v1",
            target_kind="agent",
            message_required=True,
            content_type_required=True,
            origin_proof_required=True,
        ),
        *[
            _contract(
                method,
                "anp.group.base.v1",
                target_kind=target,
                sender_required=method != "group.get_info",
                principal="anonymous_or_peer" if method == "group.get_info" else "local_bearer_or_verified_peer",
                origin_proof_required=method != "group.get_info",
                wns_binding_required=method == "group.rebind_member",
            )
            for method, target in [
                ("group.create", "service"),
                ("group.get_info", "group"),
                ("group.join", "group"),
                ("group.add", "group"),
                ("group.remove", "group"),
                ("group.rebind_member", "group"),
                ("group.leave", "group"),
                ("group.update_profile", "group"),
                ("group.update_policy", "group"),
            ]
        ],
        _contract(
            "group.send",
            "anp.group.base.v1",
            target_kind="group",
            message_required=True,
            content_type_required=True,
            origin_proof_required=True,
        ),
        _contract(
            "group.incoming",
            "anp.group.base.v1",
            rpc_kind="notification",
            target_kind="agent",
            message_required=True,
            content_type_required=True,
            receipt_proof_required=True,
        ),
        _contract(
            "group.state_changed",
            "anp.group.base.v1",
            rpc_kind="notification",
            target_kind="agent",
            message_required=False,
            content_type_required=False,
            receipt_proof_required=True,
        ),
        _contract(
            "attachment.get_download_ticket",
            "anp.attachment.v1",
            target_kind="service",
        ),
        *[
            _contract(
                method,
                "anp.attachment.v1",
                surfaces=("local",),
                target_kind="service",
                principal="local_bearer",
            )
            for method in [
                "attachment.create_slot",
                "attachment.commit_object",
                "attachment.abort_object",
            ]
        ],
        _contract(
            "inbox.get",
            "anp.inbox.local.v1",
            surfaces=("local",),
            target_kind=None,
            principal="local_bearer",
        ),
        _contract(
            "inbox.mark_read",
            "anp.inbox.local.v1",
            surfaces=("local",),
            target_kind=None,
            principal="local_bearer",
        ),
        _contract(
            "direct.get_history",
            "anp.direct.local.v1",
            surfaces=("local",),
            target_kind=None,
            principal="local_bearer",
        ),
        *[
            _contract(method, "anp.group.local.v1", surfaces=("local",), target_kind=None, principal="local_bearer")
            for method in [
                "group.get",
                "group.list",
                "group.list_members",
                "group.list_messages",
            ]
        ],
        *[
            _contract(
                method,
                "anp.sync.local.v1",
                surfaces=("local",),
                target_kind=None,
                principal="local_bearer",
                alternate_profiles=("anp.sync.local.v2",),
            )
            for method in ["sync.delta", "sync.thread_after"]
        ],
        *[
            _contract(
                method,
                "anp.sync.local.v2",
                surfaces=("local",),
                target_kind=None,
                principal="local_bearer",
            )
            for method in ["sync.bootstrap", "message.get_batch"]
        ],
        _contract(
            "read_state.mark_read",
            "anp.read_state.local.v1",
            surfaces=("local",),
            target_kind=None,
            principal="local_bearer",
        ),
        *[
            _contract(
                method,
                profile,
                target_kind="service",
                advertised=False,
            )
            for method, profile in [
                ("direct.e2ee.publish_prekey_bundle", "anp.direct.e2ee.v2"),
                ("direct.e2ee.get_prekey_bundle", "anp.direct.e2ee.v2"),
                ("group.e2ee.publish_key_package", "anp.group.e2ee.v2"),
            ]
        ],
    ]
}


def methods_for_surface(surface: Surface, *, advertised_only: bool = False) -> tuple[str, ...]:
    return tuple(
        contract.method
        for contract in METHOD_CONTRACTS.values()
        if surface in contract.surfaces and (contract.advertised or not advertised_only)
    )


PUBLIC_ANP_METHODS = methods_for_surface("public")
PUBLIC_NOTIFICATION_METHODS = frozenset(
    contract.method
    for contract in METHOD_CONTRACTS.values()
    if "public" in contract.surfaces and contract.rpc_kind == "notification"
)


__all__ = [
    "METHOD_CONTRACTS",
    "STANDARD_PROFILES",
    "LOCAL_PROFILES",
    "PUBLIC_ANP_METHODS",
    "PUBLIC_NOTIFICATION_METHODS",
    "MethodContract",
    "methods_for_surface",
]
