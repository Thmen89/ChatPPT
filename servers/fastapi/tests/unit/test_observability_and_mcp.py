"""/healthz, logfmt access lines, unbuffered event streams, and MCP mounted in-process."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from api import mcp
from api.observability import (
    AccessLogMiddleware,
    LogfmtFormatter,
    UnbufferedStreamsMiddleware,
    health_router,
    normalize_level,
    uvicorn_log_config,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen():  # type: ignore[no-untyped-def]
            yield "data: {}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/plain")
    async def plain() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(UnbufferedStreamsMiddleware)
    app.add_middleware(AccessLogMiddleware)
    return app


def test_healthz_is_cheap_and_ok() -> None:
    res = TestClient(_app()).get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_event_streams_are_marked_no_transform() -> None:
    client = TestClient(_app())
    res = client.get("/stream")
    assert res.headers["cache-control"] == "no-cache, no-transform"
    assert res.headers["x-accel-buffering"] == "no"
    assert "no-transform" not in client.get("/plain").headers.get("cache-control", "")


def test_access_log_one_line_per_request(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app())
    with caplog.at_level(logging.INFO, logger="chatppt.access"):
        client.get("/plain?token=secret")
        client.get("/healthz")  # probes log at DEBUG only
    records = [r for r in caplog.records if r.name == "chatppt.access"]
    assert len(records) == 1
    rec: Any = records[0]
    assert (rec.method, rec.path, rec.status) == ("GET", "/plain", 200)
    assert rec.duration_ms >= 0
    line = LogfmtFormatter().format(rec)
    assert "path=/plain " in line and "status=200" in line and "secret" not in line
    assert line.startswith("ts=") and "level=info logger=chatppt.access msg=request" in line


def test_logfmt_quotes_values_with_spaces() -> None:
    rec = logging.LogRecord("x", logging.WARNING, __file__, 1, 'say "hi" there', None, None)
    rec.color_message = "\x1b[1mignored"
    line = LogfmtFormatter().format(rec)
    assert 'msg="say \\"hi\\" there"' in line
    assert "color_message" not in line


def test_log_level_from_settings() -> None:
    assert normalize_level("debug") == "DEBUG"
    assert normalize_level("warn") == "WARNING"
    assert normalize_level("nonsense") == "INFO"
    cfg = uvicorn_log_config("error")
    assert cfg["root"]["level"] == "ERROR"
    assert cfg["loggers"]["uvicorn.access"]["propagate"] is False


def test_lazy_mcp_builds_on_first_request_and_closes() -> None:
    built: list[int] = []

    def factory() -> Any:
        built.append(1)
        return mcp.build_mcp_app(base_url="http://127.0.0.1:9")

    app = FastAPI()
    lazy = mcp.LazyMCP(factory)
    from starlette.routing import Route

    app.router.routes.append(Route(mcp.MCP_PATH, endpoint=lazy, methods=["GET", "POST", "DELETE"]))
    app.router.routes.append(Route(mcp.MCP_PATH + "/", endpoint=lazy, methods=["GET", "POST", "DELETE"]))
    assert not lazy.started and built == []

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app) as client:
        for path in (mcp.MCP_PATH, mcp.MCP_PATH + "/"):
            res = client.post(path, json=init, headers=headers)
            assert res.status_code == 200, res.text
            assert "ChatPPT API" in res.text
        assert lazy.started and built == [1]
        client.portal.call(lazy.aclose)  # type: ignore[union-attr]
    assert not lazy.started


def test_mcp_spec_ships_and_the_main_app_mounts_it() -> None:
    assert mcp.SPEC_PATH.is_file()
    from api.main import app

    paths = {getattr(r, "path", None) for r in app.router.routes}
    assert {"/mcp", "/mcp/", "/healthz"} <= paths


def test_internal_auth_header_attached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import httpx

    monkeypatch.setattr(mcp, "get_internal_auth_headers", lambda: {"Authorization": "Bearer t"})
    req = httpx.Request("GET", "http://127.0.0.1:8000/x")
    asyncio.run(mcp._attach_internal_auth_header(req))
    assert req.headers["authorization"] == "Bearer t"
    keep = httpx.Request("GET", "http://127.0.0.1:8000/x", headers={"Authorization": "Basic u"})
    asyncio.run(mcp._attach_internal_auth_header(keep))
    assert keep.headers["authorization"] == "Basic u"
