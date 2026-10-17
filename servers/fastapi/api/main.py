import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse

from api.lifespan import app_lifespan
from api.middlewares import SessionAuthMiddleware
from api.v1.auth.router import API_V1_AUTH_ROUTER
from api.v1.config.router import API_V1_CONFIG_ROUTER
from api.v1.hooks.router import API_V1_HOOKS_ROUTER
from api.v1.mock.router import API_V1_MOCK_ROUTER
from api.v1.ppt.router import API_V1_PPT_ROUTER
from api.v1.webhook.router import API_V1_WEBHOOK_ROUTER
from chatppt.settings import get_settings
from utils.get_env import get_app_data_directory_env
from utils.mime_types import init_sandbox_safe_mimetypes
from utils.path_helpers import get_resource_path


init_sandbox_safe_mimetypes()


def _maybe_init_sentry() -> None:
    """Error reporting is operator opt-in. Nothing is sent anywhere unless
    ``server.error_reporting_dsn`` (legacy ``SENTRY_DSN``) is set; PII stays off
    unless ``SENTRY_SEND_DEFAULT_PII=true``; tracing is off unless
    ``SENTRY_TRACES_SAMPLE_RATE`` is set. See docs/telemetry.md."""
    dsn = (get_settings().server.error_reporting_dsn or "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk  # optional dependency, not installed by default
    except ImportError:
        logging.getLogger(__name__).warning(
            "server.error_reporting_dsn is set but sentry_sdk is not installed; "
            "error reporting stays off."
        )
        return

    try:
        traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE") or 0.0)
    except ValueError:
        traces_sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=(os.getenv("SENTRY_SEND_DEFAULT_PII") or "").strip().lower() == "true",
        traces_sample_rate=traces_sample_rate,
    )


_maybe_init_sentry()

app = FastAPI(lifespan=app_lifespan)

# Routers
app.include_router(API_V1_PPT_ROUTER)
app.include_router(API_V1_WEBHOOK_ROUTER)
app.include_router(API_V1_MOCK_ROUTER)
app.include_router(API_V1_AUTH_ROUTER)
app.include_router(API_V1_CONFIG_ROUTER)
app.include_router(API_V1_HOOKS_ROUTER)

# Mount app_data and static assets (direct FastAPI access; nginx also serves /static in Docker).
app_data_dir = get_app_data_directory_env()
if app_data_dir:
    os.makedirs(app_data_dir, exist_ok=True)
    app.mount("/app_data", StaticFiles(directory=app_data_dir), name="app_data")

static_dir = get_resource_path("static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Middlewares
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionAuthMiddleware)


@app.middleware("http")
async def static_icon_fallback_middleware(request: Request, call_next):
    """Serve placeholder when icon paths are missing (e.g. renamed Phosphor icons)."""
    response = await call_next(request)
    if response.status_code != 404:
        return response
    path = request.url.path
    if not path.startswith("/static/icons/"):
        return response
    placeholder = get_resource_path("static/icons/placeholder.svg")
    if not os.path.isfile(placeholder):
        return response
    return FileResponse(placeholder, media_type="image/svg+xml")
