"""Shared test mocks and helper utilities."""

from typing import Any


def http_request(headers: dict[str, str] | None = None) -> Any:
    """A bare Starlette ``Request``, for calling endpoints that take ``request_http`` directly."""
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw, "query_string": b""})
