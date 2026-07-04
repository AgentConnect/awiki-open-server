from __future__ import annotations

import re
from typing import Any
import urllib.parse

from fastapi import Request

from awiki_open_server.attachments.core import (
    ATTACHMENT_HANDLERS,
    attachment_abort,
    attachment_commit,
    attachment_create_slot,
    attachment_ticket,
    upload_slot,
)
from awiki_open_server.messaging.core import (
    MESSAGE_HANDLERS,
    add_sync_event,
    capabilities,
    direct_history,
    direct_send,
    group_get_info,
    group_join,
    group_leave,
    group_list,
    group_members,
    group_messages,
    group_send,
    inbox_get,
    inbox_mark_read,
    mark_read,
    not_supported,
    sync_delta,
    thread_after,
)
from awiki_open_server.shared import runtime
from awiki_open_server.shared.errors import Conflict, InvalidParams, NotFound, Unauthorized
from awiki_open_server.shared.ids import new_id, now_iso
from awiki_open_server.user_compat.core import (
    AGENT_INVENTORY_HANDLERS,
    AGENT_REGISTRATION_HANDLERS,
    DID_VERIFY_HANDLERS,
    HANDLE_HANDLERS,
    IDENTITY_HANDLERS,
    ME_HANDLERS,
    MESSAGE_AGENT_HANDLERS,
    PROFILE_HANDLERS,
    USERS_HANDLERS,
    bearer_token,
    current_did,
    did_document,
    did_for_token,
    get_settings,
    get_store,
    get_me,
    handle_confirmation_document,
    handle_resolution_document,
    legacy_me_profile,
    legacy_public_profile,
    legacy_update_me,
    profile_markdown,
    public_profile,
    register,
    update_document,
)

_json = runtime._json
_load = runtime._load
_did_belongs_to_domain = runtime._did_belongs_to_domain
_http_get_json = runtime._http_get_json
_http_post_json = runtime._http_post_json
_object_download_uri = runtime._object_download_uri
_object_upload_uri = runtime._object_upload_uri
_resolve_did_document_for_proof = runtime._resolve_did_document_for_proof
_verify_peer_request_signature = runtime._verify_peer_request_signature
_user_exists = runtime._user_exists


def _normalize_domain(raw: Any) -> str:
    domain = str(raw or "").strip().lower()
    if domain.startswith("http://") or domain.startswith("https://") or "/" in domain:
        raise InvalidParams("bare_domain_required")
    if not domain or len(domain) > 255:
        raise InvalidParams("valid_domain_required")
    if not re.fullmatch(r"[a-z0-9.-]+", domain):
        raise InvalidParams("valid_domain_required")
    if any(not part for part in domain.split(".")):
        raise InvalidParams("valid_domain_required")
    return domain


def _normalize_site_slug(raw: Any) -> str:
    slug = str(raw or "").strip().lower()
    if not slug or len(slug) > 100 or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", slug):
        raise InvalidParams("valid_slug_required")
    return slug

def content_create(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    body = params.get("body", "")
    title = params.get("title") or slug
    if not slug:
        raise InvalidParams("slug_required")
    page_id = new_id("page")
    with get_store(request).connect() as conn:
        conn.execute(
            "INSERT INTO content_pages(id, handle, slug, title, body, visibility, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (page_id, profile["handle"], slug, title, body, params.get("visibility", "public"), now_iso()),
        )
    return content_get({"slug": slug, "handle": profile["handle"]}, request)


def content_get(params: dict[str, Any], request: Request) -> dict[str, Any]:
    handle = params.get("handle")
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    with get_store(request).connect() as conn:
        if handle:
            row = conn.execute("SELECT * FROM content_pages WHERE handle = ? AND slug = ?", (handle, slug)).fetchone()
        else:
            row = conn.execute("SELECT * FROM content_pages WHERE slug = ? ORDER BY updated_at DESC LIMIT 1", (slug,)).fetchone()
    if not row:
        raise NotFound("page_not_found")
    return dict(row)


def content_list(_: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    with get_store(request).connect() as conn:
        rows = conn.execute("SELECT id, handle, slug, title, visibility, updated_at FROM content_pages WHERE handle = ? ORDER BY updated_at DESC", (profile["handle"],)).fetchall()
    pages = [dict(row) for row in rows]
    return {"pages": pages, "count": len(pages), "has_more": False}


def content_update(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    allowed = {k: params[k] for k in ["title", "body", "visibility"] if k in params}
    if not allowed:
        return content_get(params, request)
    with get_store(request).connect() as conn:
        for field, value in allowed.items():
            conn.execute(
                f"UPDATE content_pages SET {field} = ?, updated_at = ? WHERE handle = ? AND slug = ?",
                (value, now_iso(), profile["handle"], slug),
            )
    return content_get({"handle": profile["handle"], "slug": slug}, request)


def content_rename(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug") or params.get("old_slug")
    new_slug = params.get("new_slug")
    if not slug or not new_slug:
        raise InvalidParams("slug_and_new_slug_required")
    with get_store(request).connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM content_pages WHERE handle = ? AND slug = ?",
            (profile["handle"], new_slug),
        ).fetchone()
        if existing:
            raise Conflict("slug_already_exists")
        cursor = conn.execute(
            "UPDATE content_pages SET slug = ?, updated_at = ? WHERE handle = ? AND slug = ?",
            (new_slug, now_iso(), profile["handle"], slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("page_not_found")
    return content_get({"handle": profile["handle"], "slug": new_slug}, request)


def content_delete(params: dict[str, Any], request: Request) -> dict[str, Any]:
    did = current_did(request)
    profile = public_profile({"did": did}, request)
    slug = params.get("slug")
    if not slug:
        raise InvalidParams("slug_required")
    with get_store(request).connect() as conn:
        conn.execute("DELETE FROM content_pages WHERE handle = ? AND slug = ?", (profile["handle"], slug))
    return {"deleted": True, "slug": slug}


def _relationship_target(params: dict[str, Any], request: Request) -> str:
    settings = get_settings(request)
    target_did = str(params.get("target_did") or "").strip()
    if not target_did:
        raise InvalidParams("target_did_required")
    target_did = urllib.parse.unquote(target_did)
    if not _did_belongs_to_domain(target_did, settings.did_domain):
        raise InvalidParams("target_did_domain_mismatch")
    with get_store(request).connect() as conn:
        if not _user_exists(conn, target_did):
            raise NotFound("target_did_not_found")
    return target_did


def did_relationship_follow(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    if actor == target:
        raise InvalidParams("cannot_follow_self")
    now = now_iso()
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        conn.execute(
            "INSERT OR IGNORE INTO did_relationships(from_did, to_did, created_at) VALUES (?, ?, ?)",
            (actor, target, now),
        )
        reciprocal = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (target, actor),
        ).fetchone()
    return {"is_friend": reciprocal is not None}


def did_relationship_unfollow(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        conn.execute("DELETE FROM did_relationships WHERE from_did = ? AND to_did = ?", (actor, target))
    return {"ok": True}


def _relationship_item(row: Any) -> dict[str, Any]:
    return {
        "from_did": row["from_did"],
        "to_did": row["to_did"],
        "from_user_id": row["from_did"],
        "to_user_id": row["to_did"],
        "created_at": row["created_at"],
    }


def did_relationship_following(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    limit = max(1, min(int(params.get("limit", 50) or 50), 100))
    offset = max(0, int(params.get("offset", 0) or 0))
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        rows = conn.execute(
            """
            SELECT from_did, to_did, created_at FROM did_relationships
            WHERE from_did = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (actor, limit, offset),
        ).fetchall()
    return {"items": [_relationship_item(row) for row in rows], "count": len(rows), "has_more": len(rows) >= limit}


def did_relationship_followers(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    limit = max(1, min(int(params.get("limit", 50) or 50), 100))
    offset = max(0, int(params.get("offset", 0) or 0))
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        rows = conn.execute(
            """
            SELECT from_did, to_did, created_at FROM did_relationships
            WHERE to_did = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (actor, limit, offset),
        ).fetchall()
    return {"items": [_relationship_item(row) for row in rows], "count": len(rows), "has_more": len(rows) >= limit}


def did_relationship_status(params: dict[str, Any], request: Request) -> dict[str, Any]:
    actor = current_did(request)
    target = _relationship_target(params, request)
    with get_store(request).connect() as conn:
        if not _user_exists(conn, actor):
            raise Unauthorized("actor_not_local")
        following = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (actor, target),
        ).fetchone()
        follower = conn.execute(
            "SELECT 1 FROM did_relationships WHERE from_did = ? AND to_did = ?",
            (target, actor),
        ).fetchone()
    is_following = following is not None
    is_follower = follower is not None
    return {
        "is_following": is_following,
        "is_follower": is_follower,
        "is_friend": is_following and is_follower,
        "is_blocked": False,
        "is_blocked_by": False,
    }


def _site_url(domain: str, page_kind: str, slug: str) -> str:
    if page_kind == "root":
        return f"https://{domain}/"
    return f"https://{domain}/pages/{slug}.md"


def _site_page_view(row: Any, *, include_body: bool = True) -> dict[str, Any]:
    data = dict(row)
    result = {
        "domain": data["domain"],
        "kind": data["page_kind"],
        "slug": data["slug"],
        "url": _site_url(data["domain"], data["page_kind"], data["slug"]),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }
    if include_body:
        result["body"] = data["body"]
    return result


def _ensure_site_root(request: Request, domain: str) -> dict[str, Any]:
    now = now_iso()
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
        if row:
            return dict(row)
        body = f"# {domain}\n\nWelcome to {domain}."
        conn.execute(
            """
            INSERT INTO site_pages(domain, page_kind, slug, body, created_at, updated_at)
            VALUES (?, 'root', '', ?, ?, ?)
            """,
            (domain, body, now, now),
        )
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
    return dict(row)


def _site_require_domain_admin(request: Request, domain: str) -> str:
    did = current_did(request)
    settings = get_settings(request)
    if domain != settings.did_domain:
        raise Unauthorized("site_domain_not_managed_by_this_server")
    return did


def site_get_root(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    return _site_page_view(_ensure_site_root(request, domain))


def site_set_root(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    now = now_iso()
    _ensure_site_root(request, domain)
    with get_store(request).connect() as conn:
        conn.execute(
            """
            UPDATE site_pages SET body = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'root' AND slug = ''
            """,
            (body, now, domain),
        )
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'root' AND slug = ''",
            (domain,),
        ).fetchone()
    return _site_page_view(row)


def site_list_pages(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM site_pages
            WHERE domain = ? AND page_kind = 'page'
            ORDER BY slug ASC
            """,
            (domain,),
        ).fetchall()
    return {"domain": domain, "pages": [_site_page_view(row, include_body=False) for row in rows], "count": len(rows)}


def site_get_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        ).fetchone()
    if not row:
        raise NotFound("site_page_not_found")
    return _site_page_view(row)


def site_create_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    now = now_iso()
    try:
        with get_store(request).connect() as conn:
            conn.execute(
                """
                INSERT INTO site_pages(domain, page_kind, slug, body, created_at, updated_at)
                VALUES (?, 'page', ?, ?, ?, ?)
                """,
                (domain, slug, body, now, now),
            )
            row = conn.execute(
                "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
                (domain, slug),
            ).fetchone()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise Conflict("site_page_slug_exists") from exc
        raise
    return _site_page_view(row)


def site_update_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    body = str(params.get("body") or "")
    with get_store(request).connect() as conn:
        cursor = conn.execute(
            """
            UPDATE site_pages SET body = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'page' AND slug = ?
            """,
            (body, now_iso(), domain, slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("site_page_not_found")
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        ).fetchone()
    return _site_page_view(row)


def site_rename_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    old_slug = _normalize_site_slug(params.get("old_slug"))
    new_slug = _normalize_site_slug(params.get("new_slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        if old_slug != new_slug:
            existing = conn.execute(
                "SELECT 1 FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
                (domain, new_slug),
            ).fetchone()
            if existing:
                raise Conflict("site_page_slug_exists")
        cursor = conn.execute(
            """
            UPDATE site_pages SET slug = ?, updated_at = ?
            WHERE domain = ? AND page_kind = 'page' AND slug = ?
            """,
            (new_slug, now_iso(), domain, old_slug),
        )
        if cursor.rowcount == 0:
            raise NotFound("site_page_not_found")
        row = conn.execute(
            "SELECT * FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, new_slug),
        ).fetchone()
    return _site_page_view(row)


def site_delete_page(params: dict[str, Any], request: Request) -> dict[str, Any]:
    domain = _normalize_domain(params.get("domain"))
    slug = _normalize_site_slug(params.get("slug"))
    _site_require_domain_admin(request, domain)
    with get_store(request).connect() as conn:
        cursor = conn.execute(
            "DELETE FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (domain, slug),
        )
    if cursor.rowcount == 0:
        raise NotFound("site_page_not_found")
    return {"ok": True, "domain": domain, "slug": slug}


def site_public_root(request: Request, domain: str | None = None) -> str:
    settings = get_settings(request)
    normalized = _normalize_domain(domain or settings.did_domain)
    if normalized != settings.did_domain:
        raise NotFound("site_domain_not_found")
    return str(_ensure_site_root(request, normalized)["body"])


def site_public_page(slug: str, request: Request, domain: str | None = None) -> str:
    settings = get_settings(request)
    normalized = _normalize_domain(domain or settings.did_domain)
    if normalized != settings.did_domain:
        raise NotFound("site_domain_not_found")
    normalized_slug = _normalize_site_slug(slug)
    with get_store(request).connect() as conn:
        row = conn.execute(
            "SELECT body FROM site_pages WHERE domain = ? AND page_kind = 'page' AND slug = ?",
            (normalized, normalized_slug),
        ).fetchone()
    if not row:
        raise NotFound("site_page_not_found")
    return str(row["body"])

CONTENT_HANDLERS = {
    "create": content_create,
    "get": content_get,
    "list": content_list,
    "update": content_update,
    "rename": content_rename,
    "delete": content_delete,
}

DID_RELATIONSHIP_HANDLERS = {
    "follow": did_relationship_follow,
    "unfollow": did_relationship_unfollow,
    "get_following": did_relationship_following,
    "get_followers": did_relationship_followers,
    "get_status": did_relationship_status,
}

SITE_HANDLERS = {
    "get_root": site_get_root,
    "set_root": site_set_root,
    "list_pages": site_list_pages,
    "get_page": site_get_page,
    "create_page": site_create_page,
    "update_page": site_update_page,
    "rename_page": site_rename_page,
    "delete_page": site_delete_page,
}
