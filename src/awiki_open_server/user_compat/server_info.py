from __future__ import annotations

from typing import Any

from fastapi import Request


def server_info(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "schema_version": 1,
        "service": {
            "kind": "awiki-open-server",
            "name": "AWiki Open Server",
        },
        "identity": {
            "handle_registration": {
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
            },
            "handle_recovery": {
                "methods": [],
            },
        },
        "deployment": {
            "did_domain": settings.did_domain,
        },
    }
