"""Start-up: move the old single login into the users table, and the env-var preseed.

Upstream kept one username, password hash and session secret in ``userConfig.json``
(``AUTH_USERNAME`` / ``AUTH_PASSWORD_HASH`` / ``AUTH_SECRET_KEY``). On first start of this
version that user becomes the first admin with the same password hash, so the same
credentials sign in; old sessions were signed with the old secret and are signed out once.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from chatppt.auth import store

LOGGER = logging.getLogger(__name__)

LEGACY_FIELDS = ("AUTH_USERNAME", "AUTH_PASSWORD_HASH", "AUTH_SECRET_KEY")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _user_config_path(environ: Mapping[str, str]) -> str | None:
    return (environ.get("USER_CONFIG_PATH") or "").strip() or None


def migrate_legacy_login(environ: Mapping[str, str] = os.environ) -> str | None:
    """Create the admin from ``userConfig.json`` when the users table is empty; then drop the
    login fields from the file. Returns the migrated username, if any."""
    from utils.user_config_store import read_user_config_file, update_user_config_file

    path = _user_config_path(environ)
    if not path or not os.path.isfile(path):
        return None
    try:
        config = read_user_config_file(path)
    except Exception:  # unreadable file: nothing to migrate, never block start-up
        return None
    username = str(config.get("AUTH_USERNAME") or "").strip()
    password_hash = str(config.get("AUTH_PASSWORD_HASH") or "").strip()
    if not any(field in config for field in LEGACY_FIELDS):
        return None

    migrated = None
    if username and password_hash and store.count_users() == 0:
        store.create_user(username, None, is_admin=True, password_hash=password_hash, validate=False)
        migrated = store.normalize_username(username)
        LOGGER.warning(
            "Sign-in moved from userConfig.json to the database: '%s' is now an admin. Existing "
            "browser sessions are signed out once; sign in again with the same username and password.",
            migrated,
        )

    def drop(existing: dict[str, object]) -> dict[str, object]:
        for field in LEGACY_FIELDS:
            existing.pop(field, None)
        return existing

    update_user_config_file(path, drop)
    return migrated


def bootstrap_from_env(environ: Mapping[str, str] = os.environ) -> None:
    """Upstream's env preseed, for multiple users:

    * ``RESET_AUTH=true``: remove every user and API token; the next visit asks for a new
      admin (recovery; prefer ``chatppt reset-password``).
    * ``AUTH_USERNAME`` + ``AUTH_PASSWORD``: create that admin when there are no users yet;
      with ``AUTH_OVERRIDE_FROM_ENV=true`` also reset that user's password (and make them
      admin) on every start.
    """
    if _truthy(environ.get("RESET_AUTH")):
        store.delete_all_users()
        LOGGER.warning("RESET_AUTH is set: removed all users and API tokens. The next visit asks for a new admin.")

    username = (environ.get("AUTH_USERNAME") or "").strip()
    password = environ.get("AUTH_PASSWORD") or ""
    if not username or not password:
        return
    existing = store.get_user_by_username(username)
    if store.count_users() == 0:
        store.create_user(username, password, is_admin=True, validate=False)
        LOGGER.info("Created admin '%s' from AUTH_USERNAME/AUTH_PASSWORD.", store.normalize_username(username))
    elif _truthy(environ.get("AUTH_OVERRIDE_FROM_ENV")):
        if existing is None:
            store.create_user(username, password, is_admin=True, validate=False)
        else:
            store.update_user(existing.id, password=password, is_admin=True, is_active=True)
        LOGGER.warning("AUTH_OVERRIDE_FROM_ENV is set: reset the password of '%s' from the environment.", username)


def run_startup(environ: Mapping[str, str] = os.environ) -> None:
    """Both steps; errors are logged, never fatal (``chatppt reset-password`` always works)."""
    try:
        migrate_legacy_login(environ)
    except Exception:
        LOGGER.exception("Could not move the login from userConfig.json into the database")
    try:
        bootstrap_from_env(environ)
    except Exception:
        LOGGER.exception("Could not set up the login from AUTH_USERNAME/AUTH_PASSWORD")
