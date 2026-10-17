"""The MCP server, inside the FastAPI process at ``/mcp``.

Tools are generated from ``openai_spec.json`` (the REST endpoints worth exposing) and
call the REST API over loopback with an internal auth header, exactly as the old
separate ``mcp_server.py`` process did; only the process is gone.

Nothing is imported or built until the first ``/mcp`` request, so a deployment that
never uses MCP pays no memory or start-up time for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from starlette.types import Receive, Scope, Send

from utils.simple_auth import get_internal_auth_headers

LOGGER = logging.getLogger(__name__)

SPEC_PATH = Path(__file__).resolve().parents[1] / "openai_spec.json"
MCP_PATH = "/mcp"
SERVER_NAME = "ChatPPT API (OpenAPI)"
# Generating a deck with a real provider and exporting it can take minutes.
TOOL_CALL_TIMEOUT = httpx.Timeout(600.0, connect=10.0)


def api_base_url() -> str:
    """Where this process's REST API answers on loopback (server.py exports it)."""
    return (os.getenv("NEXT_PUBLIC_FAST_API") or "http://127.0.0.1:8000").strip().rstrip("/")


async def _attach_internal_auth_header(request: httpx.Request) -> None:
    if "authorization" in request.headers:
        return
    auth_header = get_internal_auth_headers().get("Authorization")
    if auth_header:
        request.headers["Authorization"] = auth_header


def build_mcp_app(spec_path: Path = SPEC_PATH, base_url: str | None = None) -> Any:
    """The Starlette app FastMCP generates from the OpenAPI spec, serving ``MCP_PATH``."""
    from fastmcp import FastMCP  # heavy import; only on first use

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    client = httpx.AsyncClient(
        base_url=base_url or api_base_url(),
        timeout=TOOL_CALL_TIMEOUT,
        event_hooks={"request": [_attach_internal_auth_header]},
    )
    mcp = FastMCP.from_openapi(openapi_spec=spec, client=client, name=SERVER_NAME)
    return mcp.http_app(path=MCP_PATH)


class LazyMCP:
    """ASGI app for ``/mcp``: builds the MCP app on the first request and runs its
    lifespan (the streamable-HTTP session manager) in a background task until
    ``aclose()``, which the FastAPI lifespan calls on shutdown."""

    def __init__(self, factory: Any = build_mcp_app) -> None:
        self._factory = factory
        self._app: Any = None
        self._lock = asyncio.Lock()
        self._stop: asyncio.Event | None = None
        self._runner: asyncio.Task[None] | None = None

    @property
    def started(self) -> bool:
        return self._app is not None

    async def _ensure(self) -> Any:
        if self._app is not None:
            return self._app
        async with self._lock:
            if self._app is not None:
                return self._app
            app = self._factory()
            ready = asyncio.Event()
            stop = asyncio.Event()

            async def run() -> None:
                async with app.router.lifespan_context(app):
                    ready.set()
                    await stop.wait()

            runner = asyncio.create_task(run(), name="mcp-lifespan")
            ready_wait = asyncio.create_task(ready.wait())
            await asyncio.wait({runner, ready_wait}, return_when=asyncio.FIRST_COMPLETED)
            if not ready.is_set():
                ready_wait.cancel()
                runner.result()  # re-raises why the MCP app could not start
                raise RuntimeError("MCP server stopped during start-up")
            self._app, self._stop, self._runner = app, stop, runner
            LOGGER.info("MCP server ready at %s (%d bytes of OpenAPI spec)", MCP_PATH, SPEC_PATH.stat().st_size)
            return app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = await self._ensure()
        if scope["type"] == "http" and scope.get("path") == MCP_PATH + "/":
            scope = dict(scope, path=MCP_PATH, raw_path=MCP_PATH.encode())
        await app(scope, receive, send)

    async def aclose(self) -> None:
        if self._stop is not None and self._runner is not None:
            self._stop.set()
            await self._runner
        self._app = self._stop = self._runner = None


def mount(app: Any) -> LazyMCP:
    """Serve MCP at ``/mcp`` (and ``/mcp/``) on ``app``; returns the handle to close on shutdown."""
    from starlette.routing import Route

    lazy = LazyMCP()
    methods = ["GET", "POST", "DELETE", "OPTIONS"]
    app.router.routes.append(Route(MCP_PATH, endpoint=lazy, methods=methods, include_in_schema=False))
    app.router.routes.append(Route(MCP_PATH + "/", endpoint=lazy, methods=methods, include_in_schema=False))
    return lazy
