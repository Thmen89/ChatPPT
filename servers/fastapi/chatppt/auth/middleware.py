"""One ASGI middleware for sign-in and the security basics, in front of every route.

Per request it

* authenticates: trusted proxy header, session cookie, ``Authorization: Bearer`` (API
  token, session or exporter token) or ``Basic`` (rate-limited), in that order;
* requires a user on ``/api/*`` (except the public sign-in endpoints), ``/mcp``, the API
  docs and ``/app_data/*``, where a signed link (``?exp=&sig=``) also works;
* serves only the media folders of ``/app_data`` (never the database, ``chatppt.toml``,
  ``userConfig.json``, backups or ``hooks.py``);
* keeps provider keys, settings, users and webhooks to admins;
* rejects cross-site state-changing requests that would ride on a cookie (CSRF);
* caps request bodies at ``server.max_upload_mb``;
* adds security headers.

``auth.disabled`` (``DISABLE_AUTH``) skips sign-in only: every caller is the local admin,
and the CSRF, path and header rules still apply.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from chatppt.auth import ratelimit, signing, store
from chatppt.settings import Settings, get_settings

SESSION_COOKIE = "chatppt_session"
LEGACY_SESSION_COOKIE = "presenton_session"  # read for one release after the rename
PROXY_SECRET_HEADER = "x-chatppt-proxy-secret"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

PUBLIC_AUTH_PATHS = frozenset(
    {"/api/v1/auth/status", "/api/v1/auth/login", "/api/v1/auth/setup", "/api/v1/auth/logout", "/api/v1/auth/verify"}
)
PUBLIC_AUTH_PREFIX = "/api/v1/auth/oidc/"
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
APP_DATA_PREFIX = "/app_data/"
APP_DATA_FOLDERS = frozenset({"images", "uploads", "fonts", "exports", "pptx-to-html"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# (methods or None for all, path prefix): only admins.
ADMIN_RULES: tuple[tuple[frozenset[str] | None, str], ...] = (
    (None, "/api/v1/config"),
    (None, "/api/v1/auth/users"),
    (None, "/api/v1/auth/tokens/all"),
    (None, "/api/v1/webhook/"),
    (None, "/api/v1/ppt/openai/models/available"),
    (None, "/api/v1/ppt/anthropic/models/available"),
    (None, "/api/v1/ppt/google/models/available"),
    (None, "/api/v1/ppt/ollama/model/pull"),
    (WRITE_METHODS, "/api/v1/ppt/codex/auth/"),
)

API_CSP = "default-src 'none'; frame-ancestors 'self'"
DOCS_CSP = "frame-ancestors 'self'"  # Swagger UI loads its own scripts and styles
# Files people uploaded or generated: render as images/fonts only, never run as a page.
# Our own PDF/PPTX exports: no sandbox, which would stop browsers' PDF viewers.
EXPORT_CSP = "frame-ancestors 'self'"
FILE_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src 'self' data:; sandbox"


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    is_admin: bool
    # session | token | basic | proxy | export | disabled
    via: str

    @property
    def read_only(self) -> bool:
        return self.via == "export"


LOCAL_ADMIN = Principal(0, "local", True, "disabled")


def auth_disabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.auth.disabled or (os.environ.get("DISABLE_AUTH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def principal_from_scope(scope: Scope) -> Principal | None:
    state = scope.get("state") or {}
    principal = state.get("principal")
    return principal if isinstance(principal, Principal) else None


def client_key(headers: dict[str, str], scope: Scope) -> str:
    """Best guess at the client: the last ``X-Forwarded-For`` hop, else the peer. Spoofable
    without a reverse proxy in front, so it only backs up the per-username limit."""
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:64]
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def public_origin_netloc(settings: Settings) -> str:
    return urlsplit(settings.server.public_url).netloc.lower()


def cors_origins(settings: Settings) -> list[str]:
    """Origins allowed to call the API cross-origin: ChatPPT's own (``server.public_url``,
    which covers the desktop app, whose UI and API ports differ) and the loopback Next.js
    server the headless exporter loads (``CHATPPT_NEXTJS_URL``), whose pages call FastAPI
    on its own port when ``NEXT_PUBLIC_FAST_API`` is set."""
    from utils.internal_urls import nextjs_base_url

    origins: list[str] = []
    for url in (settings.server.public_url, nextjs_base_url()):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        if parts.scheme and parts.netloc and origin not in origins:
            origins.append(origin)
    return origins


def _secure_public_url(settings: Settings) -> bool:
    return settings.server.public_url.lower().startswith("https://")


# --------------------------------------------------------------------------- authentication


def _from_user(user: store.User | None, via: str) -> Principal | None:
    if user is None or not user.is_active:
        return None
    return Principal(user.id, user.username, user.is_admin, via)


def _from_export(user_id: int | None) -> Principal | None:
    if user_id is None:
        return None
    if user_id == signing.INTERNAL_USER_ID:
        return Principal(0, "chatppt-internal", False, "export")
    user = store.get_user(user_id)
    return Principal(user.id, user.username, False, "export") if user and user.is_active else None


def _bearer(token: str) -> Principal | None:
    if token.startswith(store.TOKEN_PREFIX):
        return _from_user(store.resolve_token(token), "token")
    return _from_user(signing.session_user(token), "session") or _from_export(signing.export_token_user_id(token))


def _basic(value: str, client: str) -> Principal | None:
    import base64
    import binascii

    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, sep, password = decoded.partition(":")
    if not sep:
        return None
    user_key = store.normalize_username(username)
    if ratelimit.LOGIN_FAILURES_PER_USER.retry_after(user_key) or ratelimit.LOGIN_FAILURES_PER_CLIENT.retry_after(
        client
    ):
        return None
    user = store.authenticate(username, password)
    if user is None:
        ratelimit.LOGIN_FAILURES_PER_USER.hit(user_key)
        ratelimit.LOGIN_FAILURES_PER_CLIENT.hit(client)
    return _from_user(user, "basic")


def authenticate(headers: dict[str, str], cookies: dict[str, str], settings: Settings, client: str) -> Principal | None:
    """Who is calling, or None. Synchronous (may query the database); run it in a thread."""
    proxy_header = (settings.auth.proxy_header or "").strip().lower()
    if proxy_header and headers.get(proxy_header):
        secret = settings.auth.proxy_secret
        if not secret or _equal(headers.get(PROXY_SECRET_HEADER, ""), secret):
            principal = _from_user(store.ensure_external_user(headers[proxy_header], "proxy"), "proxy")
            if principal is not None:
                return principal

    cookie = cookies.get(SESSION_COOKIE) or cookies.get(LEGACY_SESSION_COOKIE)
    if cookie:
        principal = _from_user(signing.session_user(cookie), "session") or _from_export(
            signing.export_token_user_id(cookie)
        )
        if principal is not None:
            return principal

    scheme, _, value = headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() == "bearer" and value:
        return _bearer(value)
    if scheme.lower() == "basic" and value:
        return _basic(value, client)
    return None


def _equal(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# --------------------------------------------------------------------------- request rules


def is_protected(path: str) -> bool:
    if path in PUBLIC_AUTH_PATHS or path.startswith(PUBLIC_AUTH_PREFIX):
        return False
    return (
        path.startswith("/api/")
        or path == "/mcp"
        or path.startswith("/mcp/")
        or path in DOCS_PATHS
        or path.startswith(APP_DATA_PREFIX)
    )


def admin_only(method: str, path: str) -> bool:
    return any((methods is None or method in methods) and path.startswith(prefix) for methods, prefix in ADMIN_RULES)


def app_data_allowed(path: str) -> bool:
    """Only the media folders, and no traversal (``scope['path']`` is already decoded)."""
    parts = path[len(APP_DATA_PREFIX) :].split("/")
    if len(parts) < 2 or parts[0] not in APP_DATA_FOLDERS:
        return False
    return all(part not in ("", ".", "..") and "\\" not in part and "\x00" not in part for part in parts)


def same_origin(headers: dict[str, str], settings: Settings) -> bool:
    """Whether a state-changing browser request comes from ChatPPT's own pages. Requests
    without ``Origin``/``Referer``/``Sec-Fetch-Site`` are not from a browser and pass."""
    source = headers.get("origin")
    if source is None:
        if headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            return False
        source = headers.get("referer")
        if source is None:
            return True
    if source == "null":
        return False
    netloc = urlsplit(source).netloc.lower()
    allowed = {
        public_origin_netloc(settings),
        headers.get("x-forwarded-host", "").lower(),
        headers.get("host", "").lower(),
    }
    return bool(netloc) and netloc in allowed - {""}


def _csp_for(path: str) -> str:
    if path.startswith(APP_DATA_PREFIX + "exports/"):
        return EXPORT_CSP
    if path.startswith(APP_DATA_PREFIX) or path.startswith("/static/"):
        return FILE_CSP
    if path in DOCS_PATHS:
        return DOCS_CSP
    return API_CSP


class _BodyTooLarge(Exception):
    pass


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
        (b"cache-control", b"no-store"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        send = self._with_headers(send, path, settings)

        limit = settings.server.max_upload_mb * 1024 * 1024
        length = headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            await _send_json(send, 413, {"detail": f"Upload too large (limit {settings.server.max_upload_mb} MB)"})
            return

        disabled = auth_disabled(settings)
        cookies = cookie_parser(headers.get("cookie", ""))
        principal: Principal | None
        if disabled:
            principal = LOCAL_ADMIN
        elif cookies or "authorization" in headers or settings.auth.proxy_header:
            principal = await asyncio.to_thread(authenticate, headers, cookies, settings, client_key(headers, scope))
        else:
            principal = None
        scope.setdefault("state", {})
        scope["state"]["principal"] = principal
        scope["state"]["auth_username"] = principal.username if principal else None

        ambient = disabled or bool(cookies) or (principal is not None and principal.via == "proxy")
        if method not in SAFE_METHODS and (ambient or path in PUBLIC_AUTH_PATHS) and not same_origin(headers, settings):
            await _send_json(send, 403, {"detail": "Cross-site request refused"})
            return

        if path.startswith(APP_DATA_PREFIX):
            if not app_data_allowed(path):
                await _send_json(send, 404, {"detail": "Not Found"})
                return
            if principal is None:
                query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
                exp, sig = query.get("exp", [None])[0], query.get("sig", [None])[0]
                if exp and sig and await asyncio.to_thread(signing.verify_path, path, exp, sig):
                    await self.app(scope, receive, send)
                    return

        if method != "OPTIONS" and is_protected(path):
            if principal is None:
                if not await asyncio.to_thread(store.count_users):
                    await _send_json(send, 428, {"detail": "Login setup is required", "setup_required": True})
                else:
                    await _send_json(send, 401, {"detail": "Unauthorized"})
                return
            if principal.read_only and method not in SAFE_METHODS:
                await _send_json(send, 403, {"detail": "This token is read-only"})
                return
            if admin_only(method, path) and not principal.is_admin:
                await _send_json(send, 403, {"detail": "Only an admin can do this"})
                return

        try:
            await self.app(scope, self._capped(receive, limit), send)
        except _BodyTooLarge:
            await _send_json(send, 413, {"detail": f"Upload too large (limit {settings.server.max_upload_mb} MB)"})

    @staticmethod
    def _capped(receive: Receive, limit: int) -> Receive:
        seen = 0

        async def wrapped() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _BodyTooLarge()
            return message

        return wrapped

    @staticmethod
    def _with_headers(send: Send, path: str, settings: Settings) -> Send:
        extra = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"SAMEORIGIN"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"content-security-policy", _csp_for(path).encode()),
        ]
        if _secure_public_url(settings):
            extra.append((b"strict-transport-security", b"max-age=15552000"))

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = [*message.get("headers", []), *[(k, v) for k, v in extra if k not in present]]
            await send(message)

        return wrapped
