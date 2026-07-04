from __future__ import annotations

import pytest

from tests.conftest import rpc

@pytest.mark.asyncio
async def test_agent_registration_and_message_agent_minimal_compat(client):
    registered = await rpc(client, "/did-auth/rpc", "register", {"handle": "agent-owner"})
    owner_token = registered["result"]["token"]
    owner_did = registered["result"]["did"]

    issued = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "issue_token",
        {"agent_kind": "daemon", "ttl_seconds": 600},
        token=owner_token,
    )
    token = issued["result"]["token"]
    assert issued["result"]["owner_did"] == owner_did
    assert issued["result"]["one_time"] is True

    verified = await rpc(client, "/user-service/agent-registration/rpc", "verify_token", {"token": token})
    assert verified["result"]["active"] is True
    assert verified["result"]["status"] == "active"

    exchanged = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "exchange_token",
        {"token": token, "agent_did": f"{owner_did}:agents:daemon"},
    )
    assert exchanged["result"]["exchanged"] is True
    assert exchanged["result"]["agent_did"].endswith(":agents:daemon")

    used = await rpc(client, "/user-service/agent-registration/rpc", "verify_token", {"token": token})
    assert used["result"]["active"] is False
    assert used["result"]["status"] == "used"

    second = await rpc(client, "/user-service/agent-registration/rpc", "issue_token", token=owner_token)
    revoked = await rpc(
        client,
        "/user-service/agent-registration/rpc",
        "revoke_token",
        {"token": second["result"]["token"]},
    )
    assert revoked["result"]["status"] == "revoked"

    ensured = await rpc(
        client,
        "/user-service/message-agent/rpc",
        "ensure_binding",
        {
            "human_did": owner_did,
            "daemon_did": f"{owner_did}:agents:daemon",
            "runtime_agent_did": f"{owner_did}:agents:runtime",
        },
        token=owner_token,
    )
    binding_id = ensured["result"]["binding_id"]
    assert ensured["result"]["status"] == "active"

    active = await rpc(client, "/user-service/message-agent/rpc", "get_active_binding", token=owner_token)
    assert active["result"]["binding_id"] == binding_id

    listed = await rpc(client, "/user-service/message-agent/rpc", "list_bindings", token=owner_token)
    assert listed["result"]["count"] == 1

    seen = await rpc(client, "/user-service/message-agent/rpc", "mark_seen", {"binding_id": binding_id})
    assert seen["result"]["seen"] is True
    assert seen["result"]["binding"]["last_seen_at"]

    disabled = await rpc(client, "/user-service/message-agent/rpc", "disable_binding", {"binding_id": binding_id})
    assert disabled["result"]["status"] == "disabled"

    active_missing = await rpc(client, "/user-service/message-agent/rpc", "get_active_binding", token=owner_token)
    assert active_missing["error"]["message"] == "active_binding_not_found"

    revoked_binding = await rpc(client, "/user-service/message-agent/rpc", "revoke_binding", {"binding_id": binding_id})
    assert revoked_binding["result"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_agent_inventory_minimal_compat_routes(client):
    owner = await rpc(client, "/did-auth/rpc", "register", {"handle": "inventory-owner", "display_name": "Inventory Owner"})
    sender = await rpc(client, "/did-auth/rpc", "register", {"handle": "inventory-sender", "display_name": "Inventory Sender"})
    owner_token = owner["result"]["token"]
    owner_did = owner["result"]["did"]
    sender_did = sender["result"]["did"]
    daemon_did = f"{owner_did}:agents:daemon"
    runtime_did = f"{owner_did}:agents:runtime"

    await rpc(
        client,
        "/user-service/message-agent/rpc",
        "ensure_binding",
        {
            "human_did": owner_did,
            "daemon_did": daemon_did,
            "runtime_agent_did": runtime_did,
        },
        token=owner_token,
    )

    status = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_latest_status",
        {
            "daemon_agent_did": daemon_did,
            "statuses": [
                {
                    "agent_did": runtime_did,
                    "agent_kind": "runtime",
                    "status": "online",
                    "version": "0.1.0",
                    "needs_upgrade": False,
                    "needs_config": False,
                    "diagnostics_summary": {"ok": True},
                }
            ],
        },
    )
    assert status["result"]["updated"][0]["agent_did"] == runtime_did
    assert status["result"]["updated"][0]["controller_did"] == owner_did

    scope = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "sync_controller_scope",
        {"daemon_agent_did": daemon_did},
    )
    assert scope["result"]["controller_user_id"] == owner_did
    assert scope["result"]["controller_did"] == owner_did
    assert scope["result"]["controller_full_handle"] == "inventory-owner.testserver"
    assert scope["result"]["updated_count"] >= 1

    verified = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "verify_controller_sender",
        {"daemon_agent_did": daemon_did, "sender_did": owner_did},
    )
    assert verified["result"]["sender_did"] == owner_did
    assert verified["result"]["controller_did"] == owner_did

    allowed = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "authorize_agent_invocation",
        {"daemon_agent_did": daemon_did, "agent_did": runtime_did, "sender_did": sender_did},
    )
    assert allowed["result"]["allowed"] is True
    assert allowed["result"]["reason"] == "allowed"
    assert allowed["result"]["agent_did"] == runtime_did
    assert allowed["result"]["sender_did"] == sender_did
    assert allowed["result"]["sender_user_id"] == sender_did
    assert allowed["result"]["sender_full_handle"] == "inventory-sender.testserver"
    assert allowed["result"]["active_mode"] == "known_local_user"

    listed = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", token=owner_token)
    assert listed["result"]["count"] == 1
    assert listed["result"]["agents"][0]["agent_did"] == runtime_did
    assert listed["result"]["agents"][0]["latest_status"]["version"] == "0.1.0"

    renamed = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_display_name",
        {"agent_did": runtime_did, "display_name": "Runtime Agent"},
        token=owner_token,
    )
    assert renamed["result"]["agent"]["display_name"] == "Runtime Agent"

    policy = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "update_invocation_policy",
        {"agent_did": runtime_did, "active_mode": "controller_only", "whitelist_handles": ["inventory-owner.testserver"]},
        token=owner_token,
    )
    assert policy["result"]["active_mode"] == "controller_only"
    assert policy["result"]["whitelist_handles"] == ["inventory-owner.testserver"]

    fetched_policy = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "get_invocation_policy",
        {"agent_did": runtime_did},
        token=owner_token,
    )
    assert fetched_policy["result"]["active_mode"] == "controller_only"

    archived = await rpc(
        client,
        "/user-service/agent-inventory/rpc",
        "archive_agent",
        {"daemon_agent_did": daemon_did, "agent_did": runtime_did},
    )
    assert archived["result"]["archived"][0]["agent_did"] == runtime_did
    assert archived["result"]["archived"][0]["status"] == "archived"

    active_list = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", token=owner_token)
    assert active_list["result"]["count"] == 0

    inactive_list = await rpc(client, "/user-service/agent-inventory/rpc", "list_agents", {"include_inactive": True}, token=owner_token)
    assert inactive_list["result"]["count"] == 1

