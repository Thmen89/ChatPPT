"""What is left of ``userConfig.json``: Codex sign-in tokens (and, in ``simple_auth``, the
login). Provider settings live in ``chatppt.toml`` now (``chatppt/config_store.py``); an
existing ``userConfig.json`` is migrated into it once at startup."""

from utils.get_env import (
    get_codex_access_token_env,
    get_codex_account_id_env,
    get_codex_email_env,
    get_codex_is_pro_env,
    get_codex_refresh_token_env,
    get_codex_token_expires_env,
    get_codex_username_env,
    get_user_config_path_env,
)
from utils.parsers import parse_bool_or_none
from utils.user_config_store import read_user_config_file, update_user_config_file

CODEX_TOKEN_FIELDS = (
    "CODEX_ACCESS_TOKEN",
    "CODEX_REFRESH_TOKEN",
    "CODEX_TOKEN_EXPIRES",
    "CODEX_ACCOUNT_ID",
    "CODEX_USERNAME",
    "CODEX_EMAIL",
    "CODEX_IS_PRO",
)


def load_codex_tokens_into_env() -> None:
    """Restore a Codex sign-in saved by a previous run (env wins if already set)."""
    import os

    user_config_path = get_user_config_path_env()
    if not user_config_path:
        return
    saved = read_user_config_file(user_config_path)
    for field in CODEX_TOKEN_FIELDS:
        value = saved.get(field)
        if value is not None and value != "" and not os.environ.get(field):
            os.environ[field] = str(value)


def save_codex_tokens_to_user_config() -> None:
    """
    Write the current in-memory Codex OAuth token env vars back to userConfig.json
    so they survive container restarts.  Called after a successful token exchange
    and on logout (where the env vars have already been cleared to "").
    """
    user_config_path = get_user_config_path_env()
    if not user_config_path:
        return

    def merge_codex_tokens(existing: dict) -> dict:
        existing["CODEX_ACCESS_TOKEN"] = get_codex_access_token_env()
        existing["CODEX_REFRESH_TOKEN"] = get_codex_refresh_token_env()
        existing["CODEX_TOKEN_EXPIRES"] = get_codex_token_expires_env()
        existing["CODEX_ACCOUNT_ID"] = get_codex_account_id_env()
        existing["CODEX_USERNAME"] = get_codex_username_env()
        existing["CODEX_EMAIL"] = get_codex_email_env()
        existing["CODEX_IS_PRO"] = parse_bool_or_none(get_codex_is_pro_env())
        return existing

    try:
        update_user_config_file(user_config_path, merge_codex_tokens)
    except Exception as error:
        print(f"Error while saving Codex tokens to user config: {error}")
