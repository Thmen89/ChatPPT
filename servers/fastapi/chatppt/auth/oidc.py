"""Optional single sign-on with any OpenID Connect provider (authorization code + PKCE).

Configured by ``[auth.oidc]`` (issuer, client_id, client_secret). The ID token comes
straight from the provider's token endpoint over TLS, which OpenID Connect Core (3.1.3.7)
accepts in place of checking its signature; issuer, audience, expiry and nonce are checked.
No library, no extra service: two HTTP calls per sign-in.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from chatppt.auth import signing
from chatppt.settings import OIDCSettings

STATE_COOKIE = "chatppt_oidc"
STATE_TTL_SECONDS = 600
CALLBACK_PATH = "/api/v1/auth/oidc/callback"
_TIMEOUT = httpx.Timeout(10.0)
_discovery: dict[str, tuple[float, dict[str, Any]]] = {}


class OIDCError(Exception):
    """Sign-in failed; the message is safe to show."""


def enabled(config: OIDCSettings) -> bool:
    return bool(config.issuer and config.client_id)


def redirect_uri(public_url: str) -> str:
    return public_url.rstrip("/") + CALLBACK_PATH


async def discover(issuer: str) -> dict[str, Any]:
    base = issuer.rstrip("/")
    cached = _discovery.get(base)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{base}/.well-known/openid-configuration")
    if response.status_code != 200:
        raise OIDCError(f"Could not read the provider's configuration (HTTP {response.status_code})")
    data = response.json()
    if not isinstance(data, dict) or "authorization_endpoint" not in data or "token_endpoint" not in data:
        raise OIDCError("The provider's configuration is incomplete")
    _discovery[base] = (time.monotonic(), data)
    return data


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


async def start(config: OIDCSettings, public_url: str) -> tuple[str, str]:
    """``(authorization URL, value for the state cookie)``."""
    assert config.issuer and config.client_id
    meta = await discover(config.issuer)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64e(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri(public_url),
        "scope": config.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    cookie = signing.sign({"k": signing.KIND_OIDC, "st": state, "n": nonce, "cv": verifier}, STATE_TTL_SECONDS)
    return f"{meta['authorization_endpoint']}?{urlencode(params)}", cookie


def _claims(id_token: str) -> dict[str, Any]:
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as exc:
        raise OIDCError("The provider returned an unreadable ID token") from exc
    if not isinstance(claims, dict):
        raise OIDCError("The provider returned an unreadable ID token")
    return claims


def check_claims(claims: dict[str, Any], *, issuer: str, client_id: str, nonce: str) -> None:
    if str(claims.get("iss", "")).rstrip("/") != issuer.rstrip("/"):
        raise OIDCError("ID token issuer does not match")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        raise OIDCError("ID token is not for this client")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp < time.time():
        raise OIDCError("ID token has expired")
    if claims.get("nonce") != nonce:
        raise OIDCError("ID token nonce does not match")


def username_from(claims: dict[str, Any], claim: str) -> str:
    for key in (claim, "email", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise OIDCError("The ID token names no user")


async def finish(config: OIDCSettings, public_url: str, code: str, state: str, cookie: str | None) -> str:
    """Exchange the code; returns the username the provider vouched for."""
    assert config.issuer and config.client_id
    saved = signing.unsign(cookie, signing.KIND_OIDC)
    if saved is None or not secrets.compare_digest(str(saved.get("st", "")), state or ""):
        raise OIDCError("Sign-in expired or was started elsewhere; try again")
    meta = await discover(config.issuer)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(public_url),
        "client_id": config.client_id,
        "code_verifier": str(saved["cv"]),
    }
    if config.client_secret:
        form["client_secret"] = config.client_secret
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(meta["token_endpoint"], data=form, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise OIDCError(f"The provider refused the sign-in (HTTP {response.status_code})")
    id_token = (response.json() or {}).get("id_token")
    if not isinstance(id_token, str):
        raise OIDCError("The provider returned no ID token")
    claims = _claims(id_token)
    check_claims(
        claims, issuer=str(meta.get("issuer") or config.issuer), client_id=config.client_id, nonce=str(saved["n"])
    )
    return username_from(claims, config.username_claim)
