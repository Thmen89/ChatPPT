"""Signed, stateless values: browser sessions, short-lived exporter tokens, OIDC state and
signed links to files under ``/app_data``. All HMAC-SHA256 with the key in the database.

A session names the user and their ``session_version``; bumping that number (password
change, "sign out everywhere", disabling the user) invalidates every session at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote, urlencode

from chatppt.auth import store

VERSION = 2
KIND_SESSION = "s"
KIND_EXPORT = "e"
KIND_OIDC = "o"
EXPORT_TTL_SECONDS = 15 * 60
INTERNAL_USER_ID = 0


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _mac(message: str, key: bytes | None = None) -> str:
    return _b64e(hmac.new(key or store.signing_key(), message.encode("utf-8"), hashlib.sha256).digest())


def sign(payload: dict[str, Any], ttl_seconds: int) -> str:
    body = dict(payload, v=VERSION, exp=int(time.time()) + ttl_seconds)
    encoded = _b64e(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encoded}.{_mac(encoded)}"


def unsign(token: str | None, kind: str) -> dict[str, Any] | None:
    """The payload of a valid, unexpired token of ``kind``; None otherwise."""
    if not token or token.count(".") != 1 or len(token) > 4096:
        return None
    encoded, mac = token.split(".")
    if not hmac.compare_digest(mac, _mac(encoded)):
        return None
    try:
        payload = json.loads(_b64d(encoded))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("v") != VERSION or payload.get("k") != kind:
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < time.time():
        return None
    return payload


# --------------------------------------------------------------------------- sessions


def issue_session(user: store.User, ttl_seconds: int) -> str:
    return sign({"k": KIND_SESSION, "u": user.id, "sv": user.session_version}, ttl_seconds)


def session_user(token: str | None) -> store.User | None:
    payload = unsign(token, KIND_SESSION)
    if payload is None or not isinstance(payload.get("u"), int):
        return None
    user = store.get_user(payload["u"])
    if user is None or not user.is_active or user.session_version != payload.get("sv"):
        return None
    return user


def issue_export_token(user_id: int = INTERNAL_USER_ID) -> str:
    """A read-only token (GET/HEAD only) for the headless exporter and other loopback calls.
    ``user_id`` 0 is the internal service identity."""
    return sign({"k": KIND_EXPORT, "u": user_id}, EXPORT_TTL_SECONDS)


def export_token_user_id(token: str | None) -> int | None:
    payload = unsign(token, KIND_EXPORT)
    if payload is None or not isinstance(payload.get("u"), int):
        return None
    return int(payload["u"])


# --------------------------------------------------------------------------- signed links


def _path_message(path: str, exp: int) -> str:
    return f"url:{path}:{exp}"


def sign_path(path: str, ttl_seconds: int) -> str:
    """``path`` (e.g. ``/app_data/images/x.png``) with ``exp`` and ``sig`` query parameters
    that let anyone holding the link fetch that one file until it expires."""
    exp = int(time.time()) + ttl_seconds
    sig = _mac(_path_message(path, exp))[:22]
    return f"{quote(path)}?{urlencode({'exp': exp, 'sig': sig})}"


def verify_path(path: str, exp: str | None, sig: str | None) -> bool:
    if not exp or not sig or not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _mac(_path_message(path, int(exp)))[:22])
