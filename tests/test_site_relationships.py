from __future__ import annotations

import pytest

from tests.conftest import rpc

@pytest.mark.asyncio
async def test_did_relationship_phone_bind_and_site_rpc_compat(contact_verification_compat_client):
    client = contact_verification_compat_client
    alice = await rpc(client, "/did-auth/rpc", "register", {"handle": "rel-alice"})
    bob = await rpc(client, "/did-auth/rpc", "register", {"handle": "rel-bob"})
    alice_token = alice["result"]["token"]
    bob_token = bob["result"]["token"]
    alice_did = alice["result"]["did"]
    bob_did = bob["result"]["did"]

    bind_send = await client.post(
        "/user-service/auth/phone-bind-send",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000"},
    )
    assert bind_send.status_code == 200
    assert bind_send.json()["message"] == "Code sent."
    assert bind_send.json()["dev_otp"] == "123456"

    bind_verify = await client.post(
        "/user-service/auth/phone-bind-verify",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000", "code": "123456"},
    )
    assert bind_verify.status_code == 200
    assert bind_verify.json()["success"] is True
    assert bind_verify.json()["did"] == alice_did

    bad_bind = await client.post(
        "/auth/phone-bind-verify",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"phone": "+8613800138000", "code": "000000"},
    )
    assert bad_bind.status_code == 401

    followed = await rpc(
        client,
        "/user-service/did/relationships/rpc",
        "follow",
        {"target_did": bob_did},
        token=alice_token,
    )
    assert followed["result"]["is_friend"] is False

    status = await rpc(
        client,
        "/user-service/did/relationships/rpc",
        "get_status",
        {"target_did": bob_did},
        token=alice_token,
    )
    assert status["result"]["is_following"] is True
    assert status["result"]["is_follower"] is False
    assert status["result"]["is_friend"] is False

    following = await rpc(client, "/did/relationships/rpc", "get_following", {"limit": 10, "offset": 0}, token=alice_token)
    assert following["result"]["items"][0]["from_did"] == alice_did
    assert following["result"]["items"][0]["to_did"] == bob_did
    assert following["result"]["items"][0]["from_user_id"] == alice_did

    followers = await rpc(client, "/user-service/did/relationships/rpc", "get_followers", token=bob_token)
    assert followers["result"]["items"][0]["from_did"] == alice_did
    assert followers["result"]["items"][0]["to_did"] == bob_did

    reciprocal = await rpc(client, "/did/relationships/rpc", "follow", {"target_did": alice_did}, token=bob_token)
    assert reciprocal["result"]["is_friend"] is True

    friend_status = await rpc(client, "/did/relationships/rpc", "get_status", {"target_did": bob_did}, token=alice_token)
    assert friend_status["result"]["is_friend"] is True
    assert friend_status["result"]["is_blocked"] is False

    self_follow = await rpc(client, "/did/relationships/rpc", "follow", {"target_did": alice_did}, token=alice_token)
    assert self_follow["error"]["message"] == "cannot_follow_self"

    external_follow = await rpc(
        client,
        "/did/relationships/rpc",
        "follow",
        {"target_did": "did:wba:awiki.info:users:remote"},
        token=alice_token,
    )
    assert external_follow["error"]["message"] == "target_did_domain_mismatch"

    unfollow = await rpc(client, "/did/relationships/rpc", "unfollow", {"target_did": bob_did}, token=alice_token)
    assert unfollow["result"]["ok"] is True

    root = await rpc(client, "/site/rpc", "get_root", {"domain": "testserver"}, token=alice_token)
    assert root["result"]["kind"] == "root"
    assert root["result"]["domain"] == "testserver"
    assert "Welcome to testserver" in root["result"]["body"]

    updated_root = await rpc(client, "/site/rpc", "set_root", {"domain": "testserver", "body": "# Test Site"}, token=alice_token)
    assert updated_root["result"]["body"] == "# Test Site"

    public_root = await client.get("/")
    assert public_root.status_code == 200
    assert public_root.headers["content-type"].startswith("text/markdown")
    assert public_root.text == "# Test Site"

    created_page = await rpc(
        client,
        "/site/rpc",
        "create_page",
        {"domain": "testserver", "slug": "About-Us", "body": "# About"},
        token=alice_token,
    )
    assert created_page["result"]["slug"] == "about-us"
    assert created_page["result"]["url"] == "https://testserver/pages/about-us.md"

    listed_pages = await rpc(client, "/site/rpc", "list_pages", {"domain": "testserver"}, token=alice_token)
    assert listed_pages["result"]["count"] == 1
    assert listed_pages["result"]["pages"][0]["slug"] == "about-us"
    assert "body" not in listed_pages["result"]["pages"][0]

    public_page = await client.get("/pages/about-us.md")
    assert public_page.status_code == 200
    assert public_page.text == "# About"

    renamed_page = await rpc(
        client,
        "/site/rpc",
        "rename_page",
        {"domain": "testserver", "old_slug": "about-us", "new_slug": "team"},
        token=alice_token,
    )
    assert renamed_page["result"]["slug"] == "team"

    updated_page = await rpc(
        client,
        "/site/rpc",
        "update_page",
        {"domain": "testserver", "slug": "team", "body": "# Team"},
        token=alice_token,
    )
    assert updated_page["result"]["body"] == "# Team"

    fetched_page = await rpc(client, "/site/rpc", "get_page", {"domain": "testserver", "slug": "team"}, token=alice_token)
    assert fetched_page["result"]["body"] == "# Team"

    deleted_page = await rpc(client, "/site/rpc", "delete_page", {"domain": "testserver", "slug": "team"}, token=alice_token)
    assert deleted_page["result"]["ok"] is True

    missing_page = await client.get("/pages/team.md")
    assert missing_page.status_code == 404

    foreign_site = await rpc(client, "/site/rpc", "get_root", {"domain": "awiki.info"}, token=alice_token)
    assert foreign_site["error"]["message"] == "site_domain_not_managed_by_this_server"

