"""Sign-in, account, API tokens and (admins) users. See SECURITY.md for the model."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from chatppt.auth import oidc, ratelimit, store
from chatppt.auth.middleware import Principal, auth_disabled, client_key
from chatppt.auth.web import (
    clear_session_cookie,
    current_principal,
    export_cookie_header,
    require_account,
    require_admin,
    require_user,
    set_session_cookie,
)
from chatppt.settings import get_settings

LOGGER = logging.getLogger(__name__)

API_V1_AUTH_ROUTER = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class AuthCredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(default="", max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class TokenCreateRequest(BaseModel):
    name: str = Field(default="API token", max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    is_admin: bool = False


class UserUpdateRequest(BaseModel):
    password: Optional[str] = Field(default=None, max_length=256)
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    sign_out: bool = False


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _status_payload(principal: Optional[Principal], configured: bool, exporter: bool = False) -> dict:
    settings = get_settings()
    return {
        "configured": configured,
        # The headless exporter's read-only token: not a signed-in user, but the Next.js
        # proxy lets it read what a deck needs to render.
        "exporter": exporter,
        "authenticated": principal is not None,
        "username": principal.username if principal else None,
        "is_admin": bool(principal and principal.is_admin),
        "auth_disabled": auth_disabled(settings),
        "oidc": {"enabled": oidc.enabled(settings.auth.oidc), "label": settings.auth.oidc.label},
    }


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Too many attempts; try again in {max(1, retry_after // 60)} minute(s)",
        headers={"Retry-After": str(retry_after)},
    )


# --------------------------------------------------------------------------- sign-in


@API_V1_AUTH_ROUTER.get("/status")
async def get_status(request: Request):
    principal = current_principal(request)
    if auth_disabled():
        return _status_payload(principal, True)
    configured = await asyncio.to_thread(store.count_users) > 0
    exporter = principal is not None and principal.via == "export"
    return _status_payload(None if exporter else principal, configured, exporter)


@API_V1_AUTH_ROUTER.get("/verify")
async def verify_session(request: Request):
    principal = current_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"authenticated": True, "username": principal.username, "is_admin": principal.is_admin}


@API_V1_AUTH_ROUTER.post("/setup")
async def setup_credentials(body: AuthCredentialsRequest, request: Request):
    """Create the first admin. Only while there are no users at all."""
    client = client_key(dict(request.headers), request.scope)
    retry = ratelimit.TOKEN_CREATION.retry_after(f"setup:{client}")
    if retry:
        raise _too_many(retry)
    ratelimit.TOKEN_CREATION.hit(f"setup:{client}")
    if await asyncio.to_thread(store.count_users):
        raise HTTPException(status_code=409, detail="Credentials already configured")
    try:
        user = await asyncio.to_thread(store.create_user, body.username, body.password, is_admin=True)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    LOGGER.info("Created the first admin '%s'", user.username)
    return {"configured": True, "authenticated": False, "username": user.username}


@API_V1_AUTH_ROUTER.post("/login")
async def login(body: AuthCredentialsRequest, request: Request):
    if not await asyncio.to_thread(store.count_users):
        raise HTTPException(status_code=428, detail="Login setup is required")
    user_key = store.normalize_username(body.username)
    client = client_key(dict(request.headers), request.scope)
    retry = max(
        ratelimit.LOGIN_FAILURES_PER_USER.retry_after(user_key),
        ratelimit.LOGIN_FAILURES_PER_CLIENT.retry_after(client),
    )
    if retry:
        raise _too_many(retry)
    user = await asyncio.to_thread(store.authenticate, body.username, body.password)
    if user is None:
        ratelimit.LOGIN_FAILURES_PER_USER.hit(user_key)
        ratelimit.LOGIN_FAILURES_PER_CLIENT.hit(client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    ratelimit.LOGIN_FAILURES_PER_USER.reset(user_key)
    response = JSONResponse(
        {"configured": True, "authenticated": True, "username": user.username, "is_admin": user.is_admin}
    )
    set_session_cookie(response, user, request)
    return response


@API_V1_AUTH_ROUTER.post("/logout")
async def logout(request: Request):
    response = JSONResponse({"success": True})
    clear_session_cookie(response, request)
    return response


@API_V1_AUTH_ROUTER.post("/logout-all")
async def logout_everywhere(request: Request, account=Depends(require_account)):
    _, user = account
    await asyncio.to_thread(store.update_user, user.id, sign_out=True)
    response = JSONResponse({"success": True})
    clear_session_cookie(response, request)
    return response


@API_V1_AUTH_ROUTER.get("/oidc/start")
async def oidc_start():
    settings = get_settings()
    if not oidc.enabled(settings.auth.oidc):
        raise HTTPException(status_code=404, detail="Single sign-on is not configured")
    try:
        url, state = await oidc.start(settings.auth.oidc, settings.server.public_url)
    except Exception as exc:  # provider down or misconfigured
        LOGGER.warning("OIDC start failed: %s", exc)
        return RedirectResponse("/?reason=sso_failed", status_code=303)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        oidc.STATE_COOKIE,
        state,
        max_age=oidc.STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.server.public_url.lower().startswith("https://"),
        path="/api/v1/auth/oidc",
    )
    return response


@API_V1_AUTH_ROUTER.get("/oidc/callback")
async def oidc_callback(request: Request, code: str = Query(""), state: str = Query("")):
    settings = get_settings()
    if not oidc.enabled(settings.auth.oidc):
        raise HTTPException(status_code=404, detail="Single sign-on is not configured")
    try:
        username = await oidc.finish(
            settings.auth.oidc, settings.server.public_url, code, state, request.cookies.get(oidc.STATE_COOKIE)
        )
    except Exception as exc:
        LOGGER.warning("OIDC sign-in failed: %s", exc)
        return RedirectResponse("/?reason=sso_failed", status_code=303)
    user = await asyncio.to_thread(
        store.ensure_external_user, username, "oidc", create=settings.auth.oidc.create_users
    )
    if user is None:
        LOGGER.warning("OIDC sign-in for '%s' refused: no such active user", username)
        return RedirectResponse("/?reason=sso_no_user", status_code=303)
    await asyncio.to_thread(store.touch_login, user.id)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(oidc.STATE_COOKIE, path="/api/v1/auth/oidc")
    set_session_cookie(response, user, request)
    return response


# --------------------------------------------------------------------------- account


@API_V1_AUTH_ROUTER.get("/me")
async def me(principal: Principal = Depends(require_user)):
    user = await asyncio.to_thread(store.get_user, principal.user_id) if principal.user_id else None
    return {
        "username": principal.username,
        "is_admin": principal.is_admin,
        "via": principal.via,
        "has_password": bool(user and user.has_password),
        "source": user.source if user else None,
    }


@API_V1_AUTH_ROUTER.post("/password")
async def change_password(body: PasswordChangeRequest, request: Request, account=Depends(require_account)):
    """Change your own password (signs your other sessions out, keeps this one)."""
    _, user = account
    if user.has_password:
        retry = ratelimit.LOGIN_FAILURES_PER_USER.retry_after(user.username)
        if retry:
            raise _too_many(retry)
        if await asyncio.to_thread(store.authenticate, user.username, body.current_password) is None:
            ratelimit.LOGIN_FAILURES_PER_USER.hit(user.username)
            raise HTTPException(status_code=400, detail="Current password is wrong")
    try:
        updated = await asyncio.to_thread(store.update_user, user.id, password=body.new_password)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    response = JSONResponse({"success": True})
    set_session_cookie(response, updated, request)
    return response


@API_V1_AUTH_ROUTER.post("/export-token")
async def export_token(principal: Principal = Depends(require_user)):
    """A read-only token valid for a few minutes, for the headless exporter."""
    header = export_cookie_header(principal)
    return {"cookie": header}


# --------------------------------------------------------------------------- API tokens


@API_V1_AUTH_ROUTER.get("/tokens")
async def list_my_tokens(account=Depends(require_account)):
    _, user = account
    return [t.public() for t in await asyncio.to_thread(store.list_tokens, user.id)]


@API_V1_AUTH_ROUTER.post("/tokens")
async def create_my_token(body: TokenCreateRequest, account=Depends(require_account)):
    """A new API token for REST and MCP (``Authorization: Bearer <token>``); shown once."""
    _, user = account
    key = f"token:{user.id}"
    retry = ratelimit.TOKEN_CREATION.retry_after(key)
    if retry:
        raise _too_many(retry)
    ratelimit.TOKEN_CREATION.hit(key)
    raw, token = await asyncio.to_thread(store.create_token, user.id, body.name)
    return {**token.public(), "token": raw}


@API_V1_AUTH_ROUTER.get("/tokens/all")
async def list_all_tokens(_: Principal = Depends(require_admin)):
    return [t.public() for t in await asyncio.to_thread(store.list_tokens, None)]


@API_V1_AUTH_ROUTER.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: int, principal: Principal = Depends(require_user)):
    """Revoke one of your tokens (admins: anyone's)."""
    if principal.via in ("disabled", "export"):
        raise HTTPException(status_code=400, detail="Sign-in is turned off, so there is no account to manage")
    owner = None if principal.is_admin else principal.user_id
    try:
        await asyncio.to_thread(store.delete_token, token_id, owner)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------- users (admins)


@API_V1_AUTH_ROUTER.get("/users")
async def list_users(_: Principal = Depends(require_admin)):
    return [u.public() for u in await asyncio.to_thread(store.list_users)]


@API_V1_AUTH_ROUTER.post("/users")
async def create_user(body: UserCreateRequest, _: Principal = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(store.create_user, body.username, body.password, is_admin=body.is_admin)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return user.public()


@API_V1_AUTH_ROUTER.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserUpdateRequest, _: Principal = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(
            store.update_user,
            user_id,
            password=body.password or None,
            is_admin=body.is_admin,
            is_active=body.is_active,
            sign_out=body.sign_out,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return user.public()


@API_V1_AUTH_ROUTER.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, principal: Principal = Depends(require_admin)):
    if user_id == principal.user_id:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    try:
        await asyncio.to_thread(store.delete_user, user_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
