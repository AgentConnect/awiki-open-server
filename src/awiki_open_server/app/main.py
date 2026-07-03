from __future__ import annotations

from fastapi import FastAPI

from awiki_open_server.app.realtime import RealtimeHub
from awiki_open_server.app.settings import Settings, load_settings
from awiki_open_server.service_identity import service_identity_from_settings
from awiki_open_server.storage.db import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.object_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.db_path, settings.did_domain)

    app = FastAPI(title="Awiki Open Server", version="0.1.0")
    app.state.settings = settings
    app.state.store = store
    app.state.realtime_hub = RealtimeHub()
    app.state.service_identity = service_identity_from_settings(
        service_did=settings.service_did,
        endpoint=settings.anp_service_endpoint,
        private_key_pem=settings.service_private_key_pem,
        document_json=settings.service_did_document_json,
    )

    from awiki_open_server.app.routes import mount_routes

    mount_routes(app)
    return app


app = create_app
