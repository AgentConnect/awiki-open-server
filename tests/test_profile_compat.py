from __future__ import annotations

import pytest

from tests.conftest import rpc

@pytest.mark.asyncio
async def test_legacy_me_profile_and_message_health_compat_routes(client):
    registered = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {
            "handle": "legacy-profile",
            "display_name": "Legacy Profile",
            "profile_md": "# Legacy Profile\n\nInitial profile.",
        },
    )
    token = registered["result"]["token"]
    did = registered["result"]["did"]

    im_health = await client.get("/im/healthz")
    assert im_health.status_code == 200
    assert im_health.json()["status"] == "ok"

    missing_auth = await client.get("/me")
    assert missing_auth.status_code == 401

    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user_id"] == did
    assert me.json()["nick_name"] == "Legacy Profile"
    assert me.json()["handle"] == "legacy-profile.testserver"

    updated = await client.patch(
        "/user-service/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "nick_name": "Legacy Updated",
            "avatar_url": "https://example.test/avatar.png",
            "bio": "Updated bio",
            "profile_md": "# Updated\n\nMarkdown body.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["nick_name"] == "Legacy Updated"
    assert updated.json()["avatar_url"] == "https://example.test/avatar.png"
    assert updated.json()["bio"] == "Updated bio"

    rpc_me = await rpc(client, "/me/rpc", "get_me", token=token)
    assert rpc_me["result"]["user_id"] == did
    assert rpc_me["result"]["profile_md"].startswith("# Updated")

    rpc_public = await rpc(client, "/me/rpc", "get_public_profile", {"user_id": did})
    assert rpc_public["result"]["user_id"] == did
    assert rpc_public["result"]["nick_name"] == "Legacy Updated"
    assert "phone" not in rpc_public["result"]

    public_rest = await client.get(f"/users/{did}/profile")
    assert public_rest.status_code == 200
    assert public_rest.json()["user_id"] == did
    assert public_rest.json()["profile_md"].startswith("# Updated")

    public_rest_compat = await client.get(f"/user-service/users/{did}/profile")
    assert public_rest_compat.status_code == 200
    assert public_rest_compat.json()["nick_name"] == "Legacy Updated"

    markdown = await client.get(f"/profiles/{did}")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "# Legacy Updated" in markdown.text
    assert "# Updated" in markdown.text
    assert f"DID: `{did}`" in markdown.text

    markdown_compat = await client.get(f"/user-service/profiles/{did}")
    assert markdown_compat.status_code == 200
    assert "legacy-profile.testserver" in markdown_compat.text

    missing_markdown = await client.get("/profiles/did:wba:testserver:users:missing")
    assert missing_markdown.status_code == 404

    deleted = await rpc(client, "/me/rpc", "delete_me", token=token)
    assert deleted["error"]["message"] == "not_supported"


@pytest.mark.asyncio
async def test_users_rpc_compat_routes(client):
    alice = await rpc(
        client,
        "/did-auth/rpc",
        "register",
        {
            "handle": "users-alice",
            "display_name": "Users Alice",
            "description": "Alice bio",
            "avatar_uri": "https://example.test/alice.png",
            "profile_md": "# Users Alice",
        },
    )
    bob = await rpc(client, "/did-auth/rpc", "register", {"handle": "users-bob", "display_name": "Users Bob"})
    alice_token = alice["result"]["token"]
    alice_did = alice["result"]["did"]
    bob_did = bob["result"]["did"]

    me = await rpc(client, "/users/rpc", "get_me", token=alice_token)
    assert me["result"]["did"] == alice_did
    assert me["result"]["user_name"] == "users-alice"
    assert me["result"]["nick_name"] == "Users Alice"
    assert me["result"]["display_name"] == "Users Alice"
    assert me["result"]["avatar_uri"] == "https://example.test/alice.png"
    assert me["result"]["bio"] == "Alice bio"
    assert me["result"]["description"] == "Alice bio"
    assert me["result"]["subject_type"] == "human"
    assert me["result"]["tags"] == []
    assert me["result"]["profile_md"] == "# Users Alice"
    assert me["result"]["profile_uri"].endswith(f"/profiles/{alice_did}")
    assert me["result"]["created_at"]
    assert me["result"]["handle"] == "users-alice"
    assert me["result"]["handle_domain"] == "testserver"

    by_did = await rpc(client, "/user-service/users/rpc", "get_by_did", {"did": bob_did}, token=alice_token)
    assert by_did["result"]["did"] == bob_did
    assert by_did["result"]["handle"] == "users-bob"

    by_dids = await rpc(
        client,
        "/users/rpc",
        "get_by_dids",
        {"dids": [alice_did, "did:wba:testserver:users:missing", bob_did]},
        token=alice_token,
    )
    assert [item["did"] for item in by_dids["result"]["users"]] == [alice_did, bob_did]

    by_handle = await rpc(
        client,
        "/user-service/users/rpc",
        "get_by_handle",
        {"handle": "users-alice.testserver"},
        token=alice_token,
    )
    assert by_handle["result"]["did"] == alice_did

    by_local_handle = await rpc(
        client,
        "/users/rpc",
        "get_by_handle",
        {"handle": "users-bob", "domain": "testserver"},
        token=alice_token,
    )
    assert by_local_handle["result"]["did"] == bob_did

    missing = await rpc(client, "/users/rpc", "get_by_did", {"did": "did:wba:testserver:users:nope"}, token=alice_token)
    assert missing["error"]["message"] == "profile_not_found"

