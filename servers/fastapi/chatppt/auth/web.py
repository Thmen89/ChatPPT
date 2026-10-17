"""Helpers for routes: who is calling, session cookies, exporter tokens, signed links."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException, Request
from starlette.responses import Response

from chatppt.auth import signing, store
from chatppt.auth.middleware import (
    LEGACY_SESSION_COOKIE,
    SESSION_COOKIE,
    Principal,
    auth_disabled,
    principal_from_scope,
)
from chatppt.settings import get_settings


def current_principal(request: Request) -> Principal | None:
    return principal_from_scope(request.scope)


def require_user(request: Request) -> Principal:
    """FastAPI dependency: the signed-in caller (the middleware already refused anonymous
    requests on protected paths; this also covers the public auth router)."""
    principal = current_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal


def require_account(request: Request) -> tuple[Principal, store.User]:
    """The caller and their stored user (not the local admin of ``auth.disabled``, not a
    read-only exporter token)."""
    principal = require_user(request)
    if principal.via in ("disabled", "export"):
        raise HTTPException(status_code=400, detail="Sign-in is turned off, so there is no account to manage")
    user = store.get_user(principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal, user


def require_admin(request: Request) -> Principal:
    principal = require_user(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can do this")
    return principal


def _secure(request: Request) -> bool:
    if get_settings().server.public_url.lower().startswith("https://"):
        return True
    return request.headers.get("x-forwarded-proto", "").lower() == "https" or request.url.scheme == "https"


def set_session_cookie(response: Response, user: store.User, request: Request) -> None:
    ttl = get_settings().auth.session_days * 86400
    response.set_cookie(
        key=SESSION_COOKIE,
        value=signing.issue_session(user, ttl),
        max_age=ttl,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    for key in (SESSION_COOKIE, LEGACY_SESSION_COOKIE):
        response.delete_cookie(key=key, httponly=True, secure=_secure(request), samesite="lax", path="/")


def export_cookie_header(principal: Principal | None) -> str | None:
    """A ``Cookie`` header for the headless exporter: a fresh read-only token valid for a
    few minutes, never the caller's own session. None when sign-in is off."""
    if auth_disabled():
        return None
    user_id = principal.user_id if principal is not None and principal.via != "disabled" else 0
    return f"{SESSION_COOKIE}={signing.issue_export_token(user_id)}"


def internal_auth_headers() -> dict[str, str]:
    """Headers for loopback calls this server makes to itself or to Next.js (read-only)."""
    if auth_disabled():
        return {}
    token = signing.issue_export_token()
    return {"Authorization": f"Bearer {token}", "Cookie": f"{SESSION_COOKIE}={token}"}


def signed_path(path: str) -> str:
    """A signed link to a file under ``/app_data`` (see ``auth.signed_url_minutes``)."""
    return signing.sign_path(path, get_settings().auth.signed_url_minutes * 60)


# A link that already has a query string (``?``) is left alone.
_APP_DATA_URL = re.compile(r"(https?://[^/\s\"'<>]+)?(/app_data/[^\s\"'<>?#)]+)(?=$|[\s\"'<>#)])")


def sign_app_data_urls(value: Any) -> Any:
    """``value`` (deck JSON) with every ``/app_data/...`` link signed, so the exporter's
    converter, which fetches images without a cookie, can still read them. Unchanged when
    sign-in is off."""
    if auth_disabled():
        return value
    ttl = get_settings().auth.signed_url_minutes * 60

    def sign_text(text: str) -> str:
        if "/app_data/" not in text:
            return text
        return _APP_DATA_URL.sub(lambda m: (m.group(1) or "") + signing.sign_path(unquote(m.group(2)), ttl), text)

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return sign_text(node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        return node

    return walk(value)


def download_url(file_path: str) -> str | None:
    """A signed ``/app_data/exports/...`` link for an exported file on disk, or None when it
    is not under the exports folder."""
    from utils.asset_directory_utils import get_exports_directory

    exports = Path(get_exports_directory()).resolve()
    target = Path(file_path).resolve()
    if not target.is_relative_to(exports):
        return None
    path = "/app_data/exports/" + target.relative_to(exports).as_posix()
    if auth_disabled():
        return path
    return signed_path(path)
