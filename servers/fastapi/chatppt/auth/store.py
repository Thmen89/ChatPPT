"""Users, API tokens and the signing key, in the app database (SQLite by default).

Synchronous on purpose: the CLI uses it as is, the server calls it from a thread
(``asyncio.to_thread``) and keeps hot lookups in a short in-process cache, so a request
that carries a session or token usually costs no query at all.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, func
from sqlmodel import Session, SQLModel, col, select

from chatppt.auth import passwords
from models.sql.key_value import KeyValueSqlModel
from models.sql.user import ApiTokenModel, UserModel

LOGGER = logging.getLogger(__name__)

TOKEN_PREFIX = "cpt_"
SIGNING_KEY_NAME = "auth.signing_key"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{1,63}$")
CACHE_SECONDS = 5.0
TOKEN_TOUCH_SECONDS = 60


class AuthError(ValueError):
    """A request the user can fix (bad name, last admin, ...); the message is shown as is."""


@dataclass(frozen=True)
class User:
    id: int
    username: str
    is_admin: bool
    is_active: bool
    session_version: int
    source: str
    has_password: bool
    created_at: int
    last_login_at: int | None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "source": self.source,
            "has_password": self.has_password,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


@dataclass(frozen=True)
class Token:
    id: int
    user_id: int
    username: str
    name: str
    prefix: str
    created_at: int
    last_used_at: int | None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "name": self.name,
            "prefix": self.prefix,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


def _user(row: UserModel) -> User:
    assert row.id is not None
    return User(
        id=row.id,
        username=row.username,
        is_admin=row.is_admin,
        is_active=row.is_active,
        session_version=row.session_version,
        source=row.source,
        has_password=bool(row.password_hash),
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


# --------------------------------------------------------------------------- engine


_engines: dict[str, Engine] = {}
_engine_lock = threading.Lock()


def database_url() -> str:
    from utils.db_utils import get_database_url_and_connect_args, to_sync_sqlalchemy_url

    url, _ = get_database_url_and_connect_args()
    return str(to_sync_sqlalchemy_url(url))


def engine() -> Engine:
    """One sync engine per database URL; creates the auth tables if they are missing (the
    CLI may run before the server ever has)."""
    url = database_url()
    existing = _engines.get(url)
    if existing is not None:
        return existing
    with _engine_lock:
        existing = _engines.get(url)
        if existing is not None:
            return existing
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        created = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        tables = [UserModel.__table__, ApiTokenModel.__table__, KeyValueSqlModel.__table__]
        SQLModel.metadata.create_all(created, tables=tables)  # type: ignore[arg-type]
        _engines[url] = created
        return created


def dispose() -> None:
    """Forget engines and caches (tests, and after the database URL changes)."""
    with _engine_lock:
        for created in _engines.values():
            created.dispose()
        _engines.clear()
    invalidate()
    _signing_key.clear()


@contextmanager
def session() -> Iterator[Session]:
    with Session(engine()) as s:
        yield s


# --------------------------------------------------------------------------- cache

_cache_lock = threading.Lock()
_user_cache: dict[int, tuple[float, User | None]] = {}
_token_cache: dict[str, tuple[float, int | None]] = {}
_count_cache: list[tuple[float, int]] = []


def invalidate() -> None:
    with _cache_lock:
        _user_cache.clear()
        _token_cache.clear()
        _count_cache.clear()


def _now() -> int:
    return int(time.time())


# --------------------------------------------------------------------------- users


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def check_new_username(username: str) -> str:
    name = normalize_username(username)
    if not USERNAME_RE.match(name):
        raise AuthError("Usernames are 2-64 characters: letters, digits and . _ @ + -")
    return name


def count_users() -> int:
    """Number of users (cached briefly: every unauthenticated request asks)."""
    with _cache_lock:
        if _count_cache and time.monotonic() - _count_cache[0][0] < CACHE_SECONDS:
            return _count_cache[0][1]
    with session() as s:
        count = int(s.exec(select(func.count()).select_from(UserModel)).one())
    with _cache_lock:
        _count_cache[:] = [(time.monotonic(), count)]
    return count


def list_users() -> list[User]:
    with session() as s:
        return [_user(row) for row in s.exec(select(UserModel).order_by(col(UserModel.username)))]


def get_user(user_id: int) -> User | None:
    with _cache_lock:
        hit = _user_cache.get(user_id)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    with session() as s:
        row = s.get(UserModel, user_id)
        user = _user(row) if row else None
    with _cache_lock:
        _user_cache[user_id] = (time.monotonic(), user)
    return user


def get_user_by_username(username: str) -> User | None:
    with session() as s:
        row = s.exec(select(UserModel).where(UserModel.username == normalize_username(username))).first()
        return _user(row) if row else None


def create_user(
    username: str,
    password: str | None,
    *,
    is_admin: bool = False,
    source: str = "local",
    password_hash: str | None = None,
    validate: bool = True,
) -> User:
    name = check_new_username(username) if validate else normalize_username(username)
    if not name:
        raise AuthError("Username is required")
    if password is not None:
        passwords.check_new_password(password)
        password_hash = passwords.hash_password(password)
    with session() as s:
        if s.exec(select(UserModel).where(UserModel.username == name)).first():
            raise AuthError(f"User '{name}' already exists")
        row = UserModel(
            username=name,
            password_hash=password_hash,
            is_admin=is_admin,
            source=source,
            created_at=_now(),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        user = _user(row)
    invalidate()
    return user


def _active_admins(s: Session) -> int:
    query = select(func.count()).select_from(UserModel).where(UserModel.is_admin, UserModel.is_active)
    return int(s.exec(query).one())


def update_user(
    user_id: int,
    *,
    password: str | None = None,
    is_admin: bool | None = None,
    is_active: bool | None = None,
    sign_out: bool = False,
) -> User:
    """Change a user. A new password, disabling, or ``sign_out`` signs the user out
    everywhere (their sessions stop validating); API tokens keep working unless disabled."""
    with session() as s:
        row = s.get(UserModel, user_id)
        if row is None:
            raise AuthError("No such user")
        losing_admin = row.is_admin and row.is_active and (is_admin is False or is_active is False)
        if losing_admin and _active_admins(s) <= 1:
            raise AuthError("Keep at least one active admin")
        if password is not None:
            passwords.check_new_password(password)
            row.password_hash = passwords.hash_password(password)
            sign_out = True
        if is_admin is not None:
            row.is_admin = is_admin
        if is_active is not None:
            row.is_active = is_active
            sign_out = sign_out or not is_active
        if sign_out:
            row.session_version += 1
        s.add(row)
        s.commit()
        s.refresh(row)
        user = _user(row)
    invalidate()
    return user


def delete_user(user_id: int) -> None:
    with session() as s:
        row = s.get(UserModel, user_id)
        if row is None:
            raise AuthError("No such user")
        if row.is_admin and row.is_active and _active_admins(s) <= 1:
            raise AuthError("Keep at least one active admin")
        for token in s.exec(select(ApiTokenModel).where(ApiTokenModel.user_id == user_id)):
            s.delete(token)
        s.delete(row)
        s.commit()
    invalidate()


def authenticate(username: str, password: str) -> User | None:
    """The active user these credentials belong to, or None. Upgrades old hashes."""
    with session() as s:
        row = s.exec(select(UserModel).where(UserModel.username == normalize_username(username))).first()
        stored = row.password_hash if row else None
        if not passwords.verify_password(password, stored) or row is None or not row.is_active:
            return None
        if stored and passwords.needs_rehash(stored):
            row.password_hash = passwords.hash_password(password)
        row.last_login_at = _now()
        s.add(row)
        s.commit()
        s.refresh(row)
        user = _user(row)
    invalidate()
    return user


def touch_login(user_id: int) -> None:
    with session() as s:
        row = s.get(UserModel, user_id)
        if row is not None:
            row.last_login_at = _now()
            s.add(row)
            s.commit()


def ensure_external_user(username: str, source: str, *, create: bool = True) -> User | None:
    """The user an SSO provider or trusted proxy vouched for, created on first sight (the
    very first user of an install becomes its admin). None if missing or disabled."""
    name = normalize_username(username)
    if not name:
        return None
    user = get_user_by_username(name)
    if user is None:
        if not create:
            return None
        try:
            user = create_user(name, None, is_admin=count_users() == 0, source=source, validate=False)
        except AuthError:  # created concurrently
            user = get_user_by_username(name)
        if user is not None:
            LOGGER.info("Created user '%s' on first %s sign-in", name, source)
    return user if user is not None and user.is_active else None


# --------------------------------------------------------------------------- API tokens


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_token(user_id: int, name: str) -> tuple[str, Token]:
    """A new token for the user; the raw value is returned once and only its hash is kept."""
    label = (name or "").strip()[:128] or "API token"
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with session() as s:
        owner = s.get(UserModel, user_id)
        if owner is None:
            raise AuthError("No such user")
        row = ApiTokenModel(
            user_id=user_id, name=label, prefix=raw[:12], token_hash=hash_token(raw), created_at=_now()
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        assert row.id is not None
        token = Token(row.id, user_id, owner.username, row.name, row.prefix, row.created_at, None)
    return raw, token


def list_tokens(user_id: int | None = None) -> list[Token]:
    """Tokens of one user, or of everyone when ``user_id`` is None (admins)."""
    query = select(ApiTokenModel, UserModel).where(col(ApiTokenModel.user_id) == col(UserModel.id))
    if user_id is not None:
        query = query.where(ApiTokenModel.user_id == user_id)
    with session() as s:
        rows = s.exec(query.order_by(col(ApiTokenModel.created_at).desc())).all()
        out = []
        for tok, owner in rows:
            assert tok.id is not None
            out.append(Token(tok.id, tok.user_id, owner.username, tok.name, tok.prefix, tok.created_at, tok.last_used_at))
        return out


def delete_token(token_id: int, user_id: int | None = None) -> None:
    """Revoke a token (only the owner's when ``user_id`` is given)."""
    with session() as s:
        row = s.get(ApiTokenModel, token_id)
        if row is None or (user_id is not None and row.user_id != user_id):
            raise AuthError("No such token")
        s.delete(row)
        s.commit()
    invalidate()


def resolve_token(raw: str) -> User | None:
    """The active user an API token belongs to, or None (revoked, unknown, user disabled)."""
    if not raw.startswith(TOKEN_PREFIX) or len(raw) > 128:
        return None
    digest = hash_token(raw)
    with _cache_lock:
        hit = _token_cache.get(digest)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        user_id = hit[1]
    else:
        with session() as s:
            row = s.exec(select(ApiTokenModel).where(ApiTokenModel.token_hash == digest)).first()
            user_id = row.user_id if row else None
            if row is not None and (row.last_used_at or 0) < _now() - TOKEN_TOUCH_SECONDS:
                row.last_used_at = _now()
                s.add(row)
                s.commit()
        with _cache_lock:
            _token_cache[digest] = (time.monotonic(), user_id)
    user = get_user(user_id) if user_id is not None else None
    return user if user is not None and user.is_active else None


# --------------------------------------------------------------------------- signing key

_signing_key: dict[str, bytes] = {}


def signing_key() -> bytes:
    """The HMAC key for sessions and signed links: random, made once, kept in the database
    (so it survives restarts and travels with backups)."""
    url = database_url()
    cached = _signing_key.get(url)
    if cached is not None:
        return cached
    query = select(KeyValueSqlModel).where(KeyValueSqlModel.key == SIGNING_KEY_NAME)
    with session() as s:
        rows = list(s.exec(query))
        if not rows:
            s.add(KeyValueSqlModel(key=SIGNING_KEY_NAME, value={"key": secrets.token_urlsafe(48)}))
            s.commit()
            rows = list(s.exec(query))
        # Two processes racing on a fresh database each insert one; both settle on the same.
        values = sorted(str((row.value or {}).get("key") or "") for row in rows)
    key = base64.urlsafe_b64decode(values[-1] + "=" * (-len(values[-1]) % 4))
    _signing_key[url] = key
    return key
