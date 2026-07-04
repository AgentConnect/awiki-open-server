from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .core import bearer_token, did_for_token, get_store, register


def identity_headers(did: str) -> dict[str, str]:
    return {"X-User-Id": did, "X-DID": did}


def contact_verification_settings(request: Request):
    settings = request.app.state.settings
    if not settings.enable_contact_verification_compat:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "contact_verification_not_enabled",
                "reason": "email_or_phone_verification_is_not_part_of_open_server_mvp",
            },
        )
    return settings


def _contact_handle(payload: dict[str, Any], default: str = "user") -> str:
    raw = str(payload.get("handle") or payload.get("phone") or payload.get("email") or default)
    raw = raw.split("@", 1)[0]
    local = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return local or default


async def sms_codes(request: Request) -> dict[str, Any]:
    settings = contact_verification_settings(request)
    payload = await request.json()
    phone = payload.get("phone")
    return {"ok": True, "sent": True, "phone": phone, "provider": "dev", "dev_otp": settings.contact_verification_dev_otp}


async def sms_login(request: Request) -> dict[str, Any]:
    settings = contact_verification_settings(request)
    payload = await request.json()
    token = payload.get("token") or payload.get("access_token")
    did = did_for_token(request, str(token)) if token else None
    if not did:
        otp = str(payload.get("otp") or payload.get("otp_code") or payload.get("code") or "")
        if otp != settings.contact_verification_dev_otp:
            raise HTTPException(status_code=401, detail="invalid_otp")
        handle = _contact_handle(payload, "dev-user")
        stored_handle = f"{handle}@{settings.did_domain}"
        with get_store(request).connect() as conn:
            revoked_row = conn.execute("SELECT revoked_at FROM users WHERE handle = ?", (stored_handle,)).fetchone()
            row = conn.execute(
                """
                SELECT u.did, u.token
                FROM users u
                LEFT JOIN did_documents d ON d.did = u.did
                WHERE u.handle = ?
                  AND u.revoked_at IS NULL
                  AND COALESCE(d.status, 'active') = 'active'
                  AND d.revoked_at IS NULL
                """,
                (stored_handle,),
            ).fetchone()
        if row:
            did = str(row["did"])
            token = str(row["token"])
        elif revoked_row:
            raise HTTPException(status_code=401, detail="did_revoked")
        else:
            registered = register(
                {
                    "handle": handle,
                    "display_name": payload.get("display_name") or handle,
                },
                request,
            )
            did = registered["did"]
            token = registered["token"]
    return {
        "ok": True,
        "access_token": token,
        "token": token,
        "refresh_token": token,
        "did": did,
        "user_id": did,
        "provider": "dev",
    }


async def email_send(request: Request) -> dict[str, Any]:
    contact_verification_settings(request)
    payload = await request.json()
    return {"ok": True, "sent": True, "email": payload.get("email"), "provider": "dev"}


async def email_status(request: Request) -> dict[str, Any]:
    contact_verification_settings(request)
    return {"ok": True, "verified": True, "provider": "dev", "mock": True, "production_verified": False}


def _required_bearer_did(request: Request) -> str:
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    did = did_for_token(request, token)
    if not did:
        raise HTTPException(status_code=401, detail="invalid_token")
    return did


async def phone_bind_send(request: Request) -> dict[str, Any]:
    settings = contact_verification_settings(request)
    did = _required_bearer_did(request)
    payload = await request.json()
    phone = payload.get("phone")
    return {
        "ok": True,
        "sent": True,
        "message": "Code sent.",
        "phone": phone,
        "provider": "dev",
        "dev_otp": settings.contact_verification_dev_otp,
        "did": did,
        "user_id": did,
    }


async def phone_bind_verify(request: Request) -> dict[str, Any]:
    settings = contact_verification_settings(request)
    did = _required_bearer_did(request)
    payload = await request.json()
    code = str(payload.get("code") or payload.get("otp") or payload.get("otp_code") or "")
    if code != settings.contact_verification_dev_otp:
        raise HTTPException(status_code=401, detail="invalid_otp")
    return {"success": True, "ok": True, "phone": payload.get("phone"), "did": did, "user_id": did, "provider": "dev"}


async def token_refresh(request: Request) -> dict[str, Any]:
    payload = await request.json()
    token = payload.get("refresh_token") or payload.get("token") or payload.get("access_token")
    did = did_for_token(request, str(token)) if token else None
    if not did:
        raise HTTPException(status_code=401, detail="invalid_token")
    return {"ok": True, "access_token": token, "token": token, "refresh_token": token, "did": did}


async def token_verify(request: Request, token: str | None = None) -> JSONResponse:
    bearer = token
    auth_token = bearer_token(request)
    if auth_token:
        bearer = auth_token
    did = did_for_token(request, str(bearer)) if bearer else None
    if not did:
        raise HTTPException(status_code=401, detail="invalid_token")
    return JSONResponse({"ok": True, "active": True, "did": did, "user_id": did}, headers=identity_headers(did))


async def ws_tickets(request: Request) -> dict[str, Any]:
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    did = did_for_token(request, token)
    if not did:
        raise HTTPException(status_code=401, detail="invalid_token")
    return {"ticket": token, "token": token, "expires_in": 3600, "did": did}


async def ws_ticket_verify(
    request: Request,
    ticket: str | None = None,
    token: str | None = None,
) -> JSONResponse:
    raw = ticket or token or request.headers.get("X-WS-Ticket") or request.headers.get("x-ws-ticket")
    did = did_for_token(request, str(raw)) if raw else None
    if not did:
        raise HTTPException(status_code=401, detail="invalid_ticket")
    return JSONResponse({"ok": True, "active": True, "did": did, "user_id": did}, headers=identity_headers(did))
