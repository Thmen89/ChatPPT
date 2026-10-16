"""Codex sign-in state lives in the process environment (persisted by
``utils.user_config.save_codex_tokens_to_user_config``). Provider settings are written to
``chatppt.toml`` instead (``chatppt/config_store.py``)."""

import os


def set_codex_access_token_env(value: str):
    os.environ["CODEX_ACCESS_TOKEN"] = value


def set_codex_refresh_token_env(value: str):
    os.environ["CODEX_REFRESH_TOKEN"] = value


def set_codex_token_expires_env(value: str):
    os.environ["CODEX_TOKEN_EXPIRES"] = value


def set_codex_account_id_env(value: str):
    os.environ["CODEX_ACCOUNT_ID"] = value


def set_codex_username_env(value: str):
    os.environ["CODEX_USERNAME"] = value


def set_codex_email_env(value: str):
    os.environ["CODEX_EMAIL"] = value


def set_codex_is_pro_env(value: str):
    os.environ["CODEX_IS_PRO"] = value


def set_codex_model_env(value: str):
    os.environ["CODEX_MODEL"] = value
