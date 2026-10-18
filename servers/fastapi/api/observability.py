"""Logs and health: one logfmt line per request, ``/healthz`` for probes.

Every log line is ``key=value`` pairs (logfmt), readable by eye and by Loki, Datadog,
``grep`` or ``jq -R``. The level comes from ``server.log_level`` (legacy ``LOG_LEVEL``).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACCESS_LOGGER = logging.getLogger("chatppt.access")

# Probes hit these every few seconds; they log at DEBUG so they don't drown real traffic.
QUIET_PATHS = frozenset({"/healthz"})

# Standard LogRecord attributes, plus uvicorn's ANSI duplicate of every message.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime", "color_message"}


def _logfmt_value(value: Any) -> str:
    text = str(value)
    if text == "" or any(c in text for c in ' ="\\\n\t'):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'
    return text


class LogfmtFormatter(logging.Formatter):
    """``ts=… level=… logger=… msg=…`` plus any ``extra=`` fields, one line per record."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        pairs: list[tuple[str, Any]] = [
            ("ts", ts),
            ("level", record.levelname.lower()),
            ("logger", record.name),
            ("msg", record.getMessage()),
        ]
        pairs += [(k, v) for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")]
        if record.exc_info:
            pairs.append(("exc", self.formatException(record.exc_info)))
        return " ".join(f"{k}={_logfmt_value(v)}" for k, v in pairs)


def normalize_level(level: str | None) -> str:
    name = (level or "info").strip().upper()
    if name == "WARN":
        name = "WARNING"
    return name if name in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"


def uvicorn_log_config(level: str | None) -> dict[str, Any]:
    """``logging.config.dictConfig`` for uvicorn: everything through one logfmt handler.

    uvicorn's own access log is off; ``AccessLogMiddleware`` writes a richer line instead.
    """
    lvl = normalize_level(level)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"logfmt": {"()": LogfmtFormatter}},
        "handlers": {
            "default": {"class": "logging.StreamHandler", "formatter": "logfmt", "stream": "ext://sys.stdout"}
        },
        "root": {"handlers": ["default"], "level": lvl},
        "loggers": {
            "uvicorn": {"handlers": [], "level": lvl, "propagate": True},
            "uvicorn.error": {"handlers": [], "level": lvl, "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},
        },
    }


class AccessLogMiddleware:
    """One line per HTTP request, written when the response finishes (so a streamed
    outline logs once, with its full duration)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            level = logging.DEBUG if path in QUIET_PATHS and status < 400 else logging.INFO
            if ACCESS_LOGGER.isEnabledFor(level):
                ACCESS_LOGGER.log(
                    level,
                    "request",
                    extra={
                        "method": scope.get("method", ""),
                        "path": path,  # no query string: it can carry session tokens
                        "status": status,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    },
                )


class UnbufferedStreamsMiddleware:
    """Mark ``text/event-stream`` responses so no proxy holds them back: ``no-transform``
    keeps the public port's gzip (and CDNs) off them, ``X-Accel-Buffering: no`` does the
    same for an nginx put in front. Without it, outline and slide streams arrive at the
    browser all at once at the end."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if content_type.startswith(b"text/event-stream"):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers += [(b"cache-control", b"no-cache, no-transform"), (b"x-accel-buffering", b"no")]
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


health_router = APIRouter()


@health_router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness for Docker/Kubernetes: the process answers. No database, no disk writes."""
    return {"status": "ok"}
