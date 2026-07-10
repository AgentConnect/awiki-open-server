from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_server_info_declares_open_server_onboarding(client):
    response = await client.get("/user-service/server-info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["service"]["kind"] == "awiki-open-server"
    assert payload["identity"]["handle_registration"] == {
        "enabled": True,
        "default_method": "phone",
        "availability": "open",
        "methods": [
            {
                "id": "phone",
                "enabled": True,
                "verification": {
                    "required": False,
                    "type": "none",
                },
            }
        ],
    }
    assert payload["identity"]["handle_recovery"]["methods"] == []
    assert payload["deployment"]["did_domain"] == "testserver"


@pytest.mark.asyncio
async def test_server_info_root_alias_matches_user_service_path(client):
    prefixed = await client.get("/user-service/server-info")
    root = await client.get("/server-info")

    assert root.status_code == 200
    assert root.json() == prefixed.json()
