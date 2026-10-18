"""Compatibility names for code that predates ``chatppt/auth`` (users, tokens and sessions
live in the database now; see ``chatppt/auth/store.py``)."""

from typing import Optional

from fastapi import Request
from starlette.responses import Response

from chatppt.auth import web
from chatppt.auth.middleware import LEGACY_SESSION_COOKIE, SESSION_COOKIE, principal_from_scope

SESSION_COOKIE_NAME = SESSION_COOKIE
# Deprecated: cookie name used before the ChatPPT rename; still read, cleared on logout.
LEGACY_SESSION_COOKIE_NAME = LEGACY_SESSION_COOKIE


def get_session_token_from_request(request: Request) -> Optional[str]:
    return request.cookies.get(SESSION_COOKIE_NAME) or request.cookies.get(LEGACY_SESSION_COOKIE_NAME)


def clear_session_cookie(response: Response, request: Request) -> None:
    web.clear_session_cookie(response, request)


def get_internal_auth_headers() -> dict[str, str]:
    """Read-only headers for trusted loopback calls (FastAPI to Next.js, and to itself)."""
    return web.internal_auth_headers()


def export_cookie_header_for(request: Request) -> Optional[str]:
    """Cookie header for the headless exporter, as the caller, read-only and short-lived."""
    return web.export_cookie_header(principal_from_scope(request.scope))
