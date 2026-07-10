from __future__ import annotations

import json
from pathlib import Path
import asyncio
from contextlib import suppress

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response

from awiki_open_server.services import (
    CONTENT_HANDLERS,
    DID_RELATIONSHIP_HANDLERS,
    MESSAGE_HANDLERS,
    SITE_HANDLERS,
    attachment_ticket,
    content_get,
    did_for_token,
    get_store,
    site_public_page,
    site_public_root,
    upload_slot,
)
from awiki_open_server.shared.errors import AwikiError, InvalidParams, NotFound, Unauthorized
from awiki_open_server.shared.ids import now_iso
from awiki_open_server.shared.jsonrpc import dispatch
from awiki_open_server.user_compat import (
    AGENT_INVENTORY_HANDLERS,
    AGENT_REGISTRATION_HANDLERS,
    DID_VERIFY_HANDLERS,
    HANDLE_HANDLERS,
    IDENTITY_HANDLERS,
    ME_HANDLERS,
    MESSAGE_AGENT_HANDLERS,
    PROFILE_HANDLERS,
    USERS_HANDLERS,
    email_send as user_compat_email_send,
    email_status as user_compat_email_status,
    handle_confirmation_document,
    handle_resolution_document,
    legacy_me_profile,
    legacy_public_profile,
    legacy_update_me,
    phone_bind_send as user_compat_phone_bind_send,
    phone_bind_verify as user_compat_phone_bind_verify,
    profile_markdown,
    sms_codes as user_compat_sms_codes,
    sms_login as user_compat_sms_login,
    token_refresh as user_compat_token_refresh,
    token_verify as user_compat_token_verify,
    ws_ticket_verify as user_compat_ws_ticket_verify,
    ws_tickets as user_compat_ws_tickets,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, Unauthorized):
        return HTTPException(status_code=401, detail=exc.error_message)
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=exc.error_message)
    if isinstance(exc, InvalidParams):
        return HTTPException(status_code=400, detail=exc.error_message)
    if isinstance(exc, AwikiError):
        return HTTPException(status_code=400, detail=exc.error_message)
    return HTTPException(status_code=500, detail=str(exc))


PUBLIC_ANP_METHODS = [
    "anp.get_capabilities",
    "direct.send",
    "group.get_info",
    "group.join",
    "attachment.get_download_ticket",
]


def mount_routes(app: FastAPI) -> None:
    settings = app.state.settings

    @app.get("/healthz")
    @app.get("/health")
    @app.get("/user-service/health")
    @app.get("/im/healthz")
    async def healthz():
        return {"status": "ok", "edition": "community"}

    @app.post("/did-auth/rpc")
    async def did_auth_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, IDENTITY_HANDLERS)

    @app.post("/user-service/did-auth/rpc")
    async def did_auth_rpc_compat(payload: dict, request: Request):
        return await dispatch(payload, request, IDENTITY_HANDLERS)

    @app.post("/did-verify/rpc")
    @app.post("/user-service/did-verify/rpc")
    async def did_verify_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, DID_VERIFY_HANDLERS)

    @app.post("/did/profile/rpc")
    async def did_profile_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, PROFILE_HANDLERS)

    @app.post("/user-service/did/profile/rpc")
    async def did_profile_rpc_compat(payload: dict, request: Request):
        return await dispatch(payload, request, PROFILE_HANDLERS)

    @app.post("/me/rpc")
    @app.post("/user-service/me/rpc")
    async def me_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, ME_HANDLERS)

    @app.get("/me")
    @app.get("/user-service/me")
    async def me_rest(request: Request):
        try:
            return legacy_me_profile({}, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.patch("/me")
    @app.patch("/user-service/me")
    async def me_update_rest(request: Request):
        payload = await request.json()
        try:
            return legacy_update_me(payload, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/users/{user_id}/profile")
    @app.get("/user-service/users/{user_id}/profile")
    async def user_public_profile(user_id: str, request: Request):
        try:
            return legacy_public_profile({"user_id": user_id}, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/profiles/{user_id}")
    @app.get("/user-service/profiles/{user_id}")
    async def user_profile_markdown(user_id: str, request: Request):
        try:
            markdown = profile_markdown(user_id, request)
        except Exception as exc:
            raise _http_error(exc) from exc
        return PlainTextResponse(markdown, media_type="text/markdown")

    @app.post("/user-service/handle/rpc")
    async def handle_rpc_compat(payload: dict, request: Request):
        return await dispatch(payload, request, HANDLE_HANDLERS)

    @app.post("/handle/rpc")
    async def handle_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, HANDLE_HANDLERS)

    @app.post("/content/rpc")
    async def content_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, CONTENT_HANDLERS)

    @app.post("/user-service/content/rpc")
    async def content_rpc_compat(payload: dict, request: Request):
        return await dispatch(payload, request, CONTENT_HANDLERS)

    @app.post("/did/relationships/rpc")
    @app.post("/user-service/did/relationships/rpc")
    async def did_relationships_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, DID_RELATIONSHIP_HANDLERS)

    @app.post("/users/rpc")
    @app.post("/user-service/users/rpc")
    async def users_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, USERS_HANDLERS)

    @app.post("/site/rpc")
    async def site_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, SITE_HANDLERS)

    @app.post("/user-service/agent-registration/rpc")
    async def agent_registration_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, AGENT_REGISTRATION_HANDLERS)

    @app.post("/user-service/agent-inventory/rpc")
    async def agent_inventory_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, AGENT_INVENTORY_HANDLERS)

    @app.post("/user-service/message-agent/rpc")
    async def message_agent_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, MESSAGE_AGENT_HANDLERS)

    async def im_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, MESSAGE_HANDLERS)
    app.add_api_route(settings.im_rpc_path, im_rpc, methods=["POST"])

    async def anp_im_rpc(request: Request):
        raw_body = await request.body()
        request.state.raw_body = raw_body
        payload = json.loads(raw_body.decode() or "{}")
        public_handlers = {name: MESSAGE_HANDLERS[name] for name in PUBLIC_ANP_METHODS}
        return await dispatch(payload, request, public_handlers)
    app.add_api_route(settings.anp_public_rpc_path, anp_im_rpc, methods=["POST"])

    @app.post("/auth/sms-codes")
    @app.post("/user-service/auth/sms-codes")
    async def sms_codes(request: Request):
        return await user_compat_sms_codes(request)

    @app.post("/auth/sms")
    @app.post("/user-service/auth/sms")
    async def sms_login(request: Request):
        return await user_compat_sms_login(request)

    @app.post("/auth/email-send")
    @app.post("/user-service/auth/email-send")
    async def email_send(request: Request):
        return await user_compat_email_send(request)

    @app.get("/auth/email-status")
    @app.get("/user-service/auth/email-status")
    async def email_status(request: Request):
        return await user_compat_email_status(request)

    @app.post("/auth/phone-bind-send")
    @app.post("/user-service/auth/phone-bind-send")
    async def phone_bind_send(request: Request):
        return await user_compat_phone_bind_send(request)

    @app.post("/auth/phone-bind-verify")
    @app.post("/user-service/auth/phone-bind-verify")
    async def phone_bind_verify(request: Request):
        return await user_compat_phone_bind_verify(request)

    @app.post("/auth/token-refresh")
    @app.post("/user-service/auth/token-refresh")
    async def token_refresh(request: Request):
        return await user_compat_token_refresh(request)

    @app.get("/auth/token-verify")
    @app.get("/user-service/auth/token-verify")
    @app.get("/auth/verify")
    @app.get("/user-service/auth/verify")
    @app.get("/sessions/verify")
    @app.get("/user-service/sessions/verify")
    async def token_verify(request: Request, token: str | None = None):
        return await user_compat_token_verify(request, token=token)

    @app.post("/ws/tickets")
    @app.post("/user-service/ws/tickets")
    async def ws_tickets(request: Request):
        return await user_compat_ws_tickets(request)

    @app.get("/ws/tickets/verify")
    @app.get("/user-service/ws/tickets/verify")
    @app.get("/auth/ws-ticket/verify")
    @app.get("/user-service/auth/ws-ticket/verify")
    async def ws_ticket_verify(request: Request, ticket: str | None = None, token: str | None = None):
        return await user_compat_ws_ticket_verify(request, ticket=ticket, token=token)

    async def im_ws(websocket: WebSocket):
        token = websocket.query_params.get("token") or websocket.query_params.get("ticket")
        did = did_for_token(websocket, token) if token else None
        if not did:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        hub = websocket.app.state.realtime_hub
        queue = hub.subscribe(did)
        await websocket.send_json(
            {
                "jsonrpc": "2.0",
                "method": "sync",
                "params": {"owner_did": did, "event_seq": "0", "source": "awiki-open-server"},
            }
        )
        try:
            while True:
                notify_task = asyncio.create_task(queue.get())
                receive_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait(
                    {notify_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                if notify_task in done:
                    await websocket.send_json(notify_task.result())
                else:
                    receive_task.result()
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(did, queue)
    app.add_api_websocket_route(settings.ws_path, im_ws)

    @app.get("/content/{slug}.md")
    async def public_markdown(slug: str, request: Request):
        try:
            page = content_get({"slug": slug}, request)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if page.get("visibility") != "public":
            raise HTTPException(status_code=404, detail="page_not_found")
        return PlainTextResponse(page["body"], media_type="text/markdown")

    @app.get("/")
    async def public_site_root(request: Request):
        try:
            body = site_public_root(request)
        except Exception as exc:
            raise _http_error(exc) from exc
        return PlainTextResponse(body, media_type="text/markdown")

    @app.get("/pages/{slug}.md")
    async def public_site_page(slug: str, request: Request):
        try:
            body = site_public_page(slug, request)
        except Exception as exc:
            raise _http_error(exc) from exc
        return PlainTextResponse(body, media_type="text/markdown")

    @app.get("/.well-known/handle/by-did")
    async def handle_by_did(did: str, request: Request):
        try:
            return handle_confirmation_document(did, request)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/.well-known/handle/{local_part}")
    async def handle_document(local_part: str, request: Request):
        try:
            return handle_resolution_document(local_part, request)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def upload_object(slot_id: str, request: Request, token: str | None = None):
        upload_token = token or request.headers.get("X-ANP-Upload-Token") or request.headers.get("x-anp-upload-token")
        if not upload_token:
            raise HTTPException(status_code=401, detail="missing_upload_token")
        try:
            return await upload_slot(slot_id, upload_token, await request.body(), request)
        except Exception as exc:
            raise _http_error(exc) from exc
    app.add_api_route(f"{settings.object_upload_path}/{{slot_id}}", upload_object, methods=["PUT"])

    async def download_object(object_id: str, request: Request, ticket: str | None = None):
        download_ticket = ticket
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not download_ticket and auth and auth.lower().startswith("bearer "):
            download_ticket = auth.split(" ", 1)[1]
        if not download_ticket:
            raise HTTPException(status_code=401, detail="missing_download_ticket")
        with get_store(request).connect() as conn:
            row = conn.execute(
                """
                SELECT o.path, o.content_type FROM attachment_objects o
                JOIN download_tickets t ON t.object_id = o.object_id
                WHERE o.object_id = ? AND t.ticket = ? AND t.expires_at > ?
                """,
                (object_id, download_ticket, now_iso()),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="object_not_found")
        path = Path(row["path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="object_missing")
        return Response(path.read_bytes(), media_type=row["content_type"])
    app.add_api_route(f"{settings.object_download_path}/{{object_id}}", download_object, methods=["GET"])

    @app.get("/.well-known/did.json")
    async def service_did(request: Request):
        settings = request.app.state.settings
        service_identity = getattr(request.app.state, "service_identity", None)
        if service_identity is not None:
            return service_identity.did_document
        return {
            "id": settings.service_did,
            "service": [
                {
                    "id": f"{settings.service_did}#anp-message",
                    "type": "ANPMessageService",
                    "serviceEndpoint": settings.anp_service_endpoint,
                    "serviceDid": settings.service_did,
                    "profiles": ["anp.core.binding.v1", "anp.direct.base.v1", "anp.group.base.v1", "anp.attachment.v1"],
                    "securityProfiles": ["transport-protected"],
                    "authSchemes": ["bearer", "didwba"],
                }
            ],
        }

    async def resolve_did_path(sub_path: str, request: Request):
        settings = request.app.state.settings
        did_path = sub_path.strip("/")
        did = f"did:wba:{settings.did_domain}"
        if did_path:
            did = f"{did}:{did_path.replace('/', ':')}"
        with get_store(request).connect() as conn:
            row = conn.execute(
                """
                SELECT document_json FROM did_documents
                WHERE did = ? AND COALESCE(status, 'active') = 'active' AND revoked_at IS NULL
                """,
                (did,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="did_document_not_found")
        return json.loads(row["document_json"])

    @app.get("/dids/resolve/{sub_path:path}/did.json")
    async def did_resolve_compat(sub_path: str, request: Request):
        return await resolve_did_path(sub_path, request)

    @app.get("/{sub_path:path}/did.json")
    async def did_path_document(sub_path: str, request: Request):
        return await resolve_did_path(sub_path, request)
