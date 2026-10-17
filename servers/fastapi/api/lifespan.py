import asyncio
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI

from migrations import migrate_database_on_startup
from services.database import create_db_and_tables, dispose_engines
from utils.get_env import get_app_data_directory_env
from utils.model_availability import (
    check_llm_and_image_provider_api_or_model_availability,
)
from chatppt.config_store import migrate_user_config_json
from chatppt.settings import apply_to_environ, get_settings
from templates.custom_layout_from_db import migrate_db_templates_to_folders
from utils.user_config import load_codex_tokens_into_env
from chatppt.auth.bootstrap import run_startup as bootstrap_auth

logger = logging.getLogger(__name__)


def _configure_application_logging() -> None:
    """Honor LOG_LEVEL (default INFO) so template/export diagnostics are visible."""
    raw = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, raw, logging.INFO)
    logging.getLogger().setLevel(level)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Initializes the application data directory, runs Alembic migrations when
    MIGRATE_DATABASE_ON_STARTUP=true, creates any missing tables, bootstraps
    the login (migrating the old single account once), and checks LLM model
    availability.
    """
    _configure_application_logging()
    # chatppt.toml / CHATPPT_* are exported as the legacy env names so upstream readers see them.
    try:
        migrate_user_config_json()
    except Exception:  # pragma: no cover - never block startup on the one-time move
        logger.exception("Could not migrate userConfig.json into chatppt.toml")
    settings = get_settings()
    exported = apply_to_environ(settings)
    if settings.source_path:
        logger.info("Loaded %s (%d keys exported to the environment)", settings.source_path, len(exported))
    os.makedirs(get_app_data_directory_env() or str(settings.data_dir), exist_ok=True)
    await migrate_database_on_startup()
    await create_db_and_tables()
    try:
        await migrate_db_templates_to_folders()
    except Exception:  # pragma: no cover - old templates stay in the DB; never block startup
        logger.exception("Could not move imported templates from the database to folders")
    # userConfig.json login -> users table (once), then the AUTH_USERNAME/AUTH_PASSWORD preseed.
    await asyncio.to_thread(bootstrap_auth)
    load_codex_tokens_into_env()
    await check_llm_and_image_provider_api_or_model_availability()
    yield
    # Shutdown: release all database connections to prevent stale/leaked pools.
    await dispose_engines()
