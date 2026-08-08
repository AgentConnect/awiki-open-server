from __future__ import annotations

import json
from pathlib import Path
import asyncio
from contextlib import suppress
import secrets

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response

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
from awiki_open_server.messaging.groups.outbox import group_operations_status
from awiki_open_server.protocol.registry import PUBLIC_ANP_METHODS, PUBLIC_NOTIFICATION_METHODS, STANDARD_PROFILES
from awiki_open_server.shared.errors import AwikiError, InvalidParams, NotFound, Unauthorized, UserServiceNotFound
from awiki_open_server.shared.ids import now_iso
from awiki_open_server.shared.jsonrpc import dispatch, parse_error
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
from awiki_open_server.user_compat.groups import GROUP_COMPAT_HANDLERS


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


def mount_routes(app: FastAPI) -> None:
    settings = app.state.settings

    @app.get("/healthz")
    @app.get("/health")
    @app.get("/user-service/health")
    @app.get("/im/healthz")
    async def healthz():
        return {"status": "ok", "edition": "community"}

    @app.get("/operations/status")
    async def operations_status(request: Request):
        configured = settings.operations_token
        if not configured:
            raise HTTPException(status_code=404, detail="not_found")
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not supplied or not secrets.compare_digest(supplied, configured):
            raise HTTPException(status_code=401, detail="unauthorized")
        return group_operations_status(app)

    @app.post("/user-service/v1/did-auth/rpc")
    @app.post("/user-service/did-auth/rpc", include_in_schema=False)
    @app.post("/did-auth/rpc", include_in_schema=False)
    async def did_auth_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, IDENTITY_HANDLERS)

    @app.post("/user-service/v1/did-verify/rpc")
    @app.post("/user-service/did-verify/rpc", include_in_schema=False)
    @app.post("/did-verify/rpc", include_in_schema=False)
    async def did_verify_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, DID_VERIFY_HANDLERS)

    @app.post("/user-service/v1/did/profile/rpc")
    @app.post("/user-service/did/profile/rpc", include_in_schema=False)
    @app.post("/did/profile/rpc", include_in_schema=False)
    async def did_profile_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, PROFILE_HANDLERS)

    @app.post("/user-service/v1/me/rpc")
    @app.post("/user-service/me/rpc", include_in_schema=False)
    @app.post("/me/rpc", include_in_schema=False)
    async def me_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, ME_HANDLERS)

    @app.get("/user-service/v1/me")
    @app.get("/user-service/me", include_in_schema=False)
    @app.get("/me", include_in_schema=False)
    async def me_rest(request: Request):
        try:
            return legacy_me_profile({}, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.patch("/user-service/v1/me")
    @app.patch("/user-service/me", include_in_schema=False)
    @app.patch("/me", include_in_schema=False)
    async def me_update_rest(request: Request):
        payload = await request.json()
        try:
            return legacy_update_me(payload, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/user-service/v1/users/{user_id}/profile")
    @app.get("/user-service/users/{user_id}/profile", include_in_schema=False)
    @app.get("/users/{user_id}/profile", include_in_schema=False)
    async def user_public_profile(user_id: str, request: Request):
        try:
            return legacy_public_profile({"user_id": user_id}, request)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/user-service/v1/profiles/{user_id}")
    @app.get("/user-service/profiles/{user_id}", include_in_schema=False)
    @app.get("/profiles/{user_id}", include_in_schema=False)
    async def user_profile_markdown(user_id: str, request: Request):
        try:
            markdown = profile_markdown(user_id, request)
        except Exception as exc:
            raise _http_error(exc) from exc
        return PlainTextResponse(markdown, media_type="text/markdown")

    @app.post("/user-service/v1/handle/rpc")
    @app.post("/user-service/handle/rpc", include_in_schema=False)
    @app.post("/handle/rpc", include_in_schema=False)
    async def handle_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, HANDLE_HANDLERS)

    @app.post("/user-service/v1/content/rpc")
    @app.post("/user-service/content/rpc", include_in_schema=False)
    @app.post("/content/rpc", include_in_schema=False)
    async def content_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, CONTENT_HANDLERS)

    @app.post("/user-service/v1/did/relationships/rpc")
    @app.post("/user-service/did/relationships/rpc", include_in_schema=False)
    @app.post("/did/relationships/rpc", include_in_schema=False)
    async def did_relationships_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, DID_RELATIONSHIP_HANDLERS)

    @app.post("/user-service/v1/users/rpc")
    @app.post("/user-service/users/rpc", include_in_schema=False)
    @app.post("/users/rpc", include_in_schema=False)
    async def users_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, USERS_HANDLERS)

    @app.post("/user-service/v1/site/rpc")
    @app.post("/user-service/site/rpc", include_in_schema=False)
    @app.post("/site/rpc", include_in_schema=False)
    async def site_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, SITE_HANDLERS)

    @app.post("/user-service/v1/agent-registration/rpc")
    @app.post("/user-service/agent-registration/rpc", include_in_schema=False)
    async def agent_registration_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, AGENT_REGISTRATION_HANDLERS)

    @app.post("/user-service/v1/agent-inventory/rpc")
    @app.post("/user-service/agent-inventory/rpc", include_in_schema=False)
    async def agent_inventory_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, AGENT_INVENTORY_HANDLERS)

    @app.post("/user-service/v1/personal-agent/rpc")
    @app.post("/user-service/personal-agent/rpc", include_in_schema=False)
    @app.post("/user-service/message-agent/rpc", include_in_schema=False)
    async def personal_agent_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, MESSAGE_AGENT_HANDLERS)

    async def im_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, MESSAGE_HANDLERS)
    app.add_api_route(settings.im_rpc_path, im_rpc, methods=["POST"])

    @app.post("/user-service/v1/group/rpc")
    @app.post("/user-service/group/rpc", include_in_schema=False)
    @app.post("/group/rpc", include_in_schema=False)
    async def group_compat_rpc(payload: dict, request: Request):
        return await dispatch(payload, request, GROUP_COMPAT_HANDLERS)

    async def anp_im_rpc(request: Request):
        raw_body = await request.body()
        request.state.raw_body = raw_body
        try:
            payload = json.loads(raw_body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(parse_error())
        public_handlers = {
            name: MESSAGE_HANDLERS[name]
            for name in PUBLIC_ANP_METHODS
            if name in MESSAGE_HANDLERS
        }
        result = await dispatch(
            payload,
            request,
            public_handlers,
            strict_anp=True,
            surface="public",
        )
        method = payload.get("method") if isinstance(payload, dict) else None
        if method in PUBLIC_NOTIFICATION_METHODS and "id" not in payload:
            return Response(status_code=204)
        if result is None:
            return Response(status_code=204)
        error = result.get("error")
        if isinstance(error, dict) and error.get("code") == 1005:
            return JSONResponse(result, status_code=401)
        return result
    app.add_api_route(settings.anp_public_rpc_path, anp_im_rpc, methods=["POST"])

    @app.post("/user-service/v1/auth/sms-codes")
    @app.post("/user-service/auth/sms-codes", include_in_schema=False)
    @app.post("/auth/sms-codes", include_in_schema=False)
    async def sms_codes(request: Request):
        return await user_compat_sms_codes(request)

    @app.post("/user-service/v1/auth/sms")
    @app.post("/user-service/auth/sms", include_in_schema=False)
    @app.post("/auth/sms", include_in_schema=False)
    async def sms_login(request: Request):
        return await user_compat_sms_login(request)

    @app.post("/user-service/v1/auth/email-send")
    @app.post("/user-service/auth/email-send", include_in_schema=False)
    @app.post("/auth/email-send", include_in_schema=False)
    async def email_send(request: Request):
        return await user_compat_email_send(request)

    @app.get("/user-service/v1/auth/email-status")
    @app.get("/user-service/auth/email-status", include_in_schema=False)
    @app.get("/auth/email-status", include_in_schema=False)
    async def email_status(request: Request):
        return await user_compat_email_status(request)

    @app.post("/user-service/v1/auth/phone-bind-send")
    @app.post("/user-service/auth/phone-bind-send", include_in_schema=False)
    @app.post("/auth/phone-bind-send", include_in_schema=False)
    async def phone_bind_send(request: Request):
        return await user_compat_phone_bind_send(request)

    @app.post("/user-service/v1/auth/phone-bind-verify")
    @app.post("/user-service/auth/phone-bind-verify", include_in_schema=False)
    @app.post("/auth/phone-bind-verify", include_in_schema=False)
    async def phone_bind_verify(request: Request):
        return await user_compat_phone_bind_verify(request)

    @app.post("/user-service/v1/auth/token-refresh")
    @app.post("/user-service/auth/token-refresh", include_in_schema=False)
    @app.post("/auth/token-refresh", include_in_schema=False)
    async def token_refresh(request: Request):
        return await user_compat_token_refresh(request)

    @app.get("/user-service/v1/auth/token-verify")
    @app.get("/user-service/v1/auth/verify")
    @app.get("/user-service/v1/sessions/verify")
    @app.get("/auth/token-verify", include_in_schema=False)
    @app.get("/user-service/auth/token-verify", include_in_schema=False)
    @app.get("/auth/verify", include_in_schema=False)
    @app.get("/user-service/auth/verify", include_in_schema=False)
    @app.get("/sessions/verify", include_in_schema=False)
    @app.get("/user-service/sessions/verify", include_in_schema=False)
    async def token_verify(request: Request, token: str | None = None):
        return await user_compat_token_verify(request, token=token)

    @app.post("/user-service/v1/ws/tickets")
    @app.post("/user-service/ws/tickets", include_in_schema=False)
    @app.post("/ws/tickets", include_in_schema=False)
    async def ws_tickets(request: Request):
        return await user_compat_ws_tickets(request)

    @app.get("/user-service/v1/ws/tickets/verify")
    @app.get("/user-service/v1/auth/ws-ticket/verify")
    @app.get("/ws/tickets/verify", include_in_schema=False)
    @app.get("/user-service/ws/tickets/verify", include_in_schema=False)
    @app.get("/auth/ws-ticket/verify", include_in_schema=False)
    @app.get("/user-service/auth/ws-ticket/verify", include_in_schema=False)
    async def ws_ticket_verify(request: Request, ticket: str | None = None, token: str | None = None):
        return await user_compat_ws_ticket_verify(request, ticket=ticket, token=token)

    async def im_ws(websocket: WebSocket):
        token = websocket.query_params.get("token") or websocket.query_params.get("ticket")
        if not token:
            authorization = websocket.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
        did = did_for_token(websocket, token) if token else None
        if not did:
            await websocket.close(code=4401)
            return
        offered_subprotocols = {
            value.strip()
            for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if value.strip()
        }
        sync_changed_v2 = "awiki.sync.changed.v2" in offered_subprotocols
        await websocket.accept(subprotocol="awiki.sync.changed.v2" if sync_changed_v2 else None)
        hub = websocket.app.state.realtime_hub
        queue = hub.subscribe(did)
        if sync_changed_v2:
            await websocket.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "sync.changed",
                    "params": {"domains": ["message"], "reason": "reconnected"},
                    "sync": {
                        "schema_version": 2,
                        "account_scan_seq_hint": None,
                        "domain_versions": {},
                    },
                }
            )
        else:
            await websocket.send_json({
                "jsonrpc": "2.0",
                "method": "sync",
                "params": {
                    "owner_did": did,
                    "reason": "connected",
                    "source": "awiki-open-server",
                    "meta": {
                        "profile": "anp.sync.local.v1",
                        "security_profile": "transport-protected",
                        "sender_did": did,
                    },
                    "body": {
                        "owner_did": did,
                        "reason": "connected",
                        "source": "awiki-open-server",
                        "recovery": "call sync.delta and sync.thread_after",
                    },
                },
            })
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
                    notification = notify_task.result()
                    if sync_changed_v2:
                        raw_sync = notification.get("sync") if isinstance(notification.get("sync"), dict) else {}
                        event_seq = raw_sync.get("event_seq")
                        account_hint = str(event_seq) if event_seq is not None and str(event_seq).isdigit() else None
                        await websocket.send_json(
                            {
                                "jsonrpc": "2.0",
                                "method": "sync.changed",
                                "params": {"domains": ["message"], "reason": "message_available"},
                                "sync": {
                                    "schema_version": 2,
                                    "account_scan_seq_hint": account_hint,
                                    "domain_versions": {},
                                },
                            }
                        )
                    else:
                        await websocket.send_json(notification)
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
    @app.get("/user-service/.well-known/handle/by-did", include_in_schema=False)
    async def handle_by_did(did: str, request: Request):
        try:
            document = handle_confirmation_document(did, request)
            return JSONResponse(
                status_code=410 if document.get("status") == "revoked" else 200,
                content=document,
            )
        except (NotFound, UserServiceNotFound):
            return JSONResponse(status_code=404, content={"error": "did_not_found", "did": did})

    @app.get("/.well-known/handle/{local_part}")
    @app.get("/user-service/.well-known/handle/{local_part}", include_in_schema=False)
    async def handle_document(local_part: str, request: Request):
        try:
            document = handle_resolution_document(local_part, request)
            return JSONResponse(
                status_code=410 if document.get("status") == "revoked" else 200,
                content=document,
            )
        except (NotFound, UserServiceNotFound):
            return JSONResponse(
                status_code=404,
                content={
                    "error": "handle_not_found",
                    "handle": f"{local_part}.{request.app.state.settings.did_domain}",
                },
            )

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
                    "profiles": list(STANDARD_PROFILES),
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
