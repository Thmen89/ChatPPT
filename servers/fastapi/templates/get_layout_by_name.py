"""Resolve a template id to its layouts and JSON schemas, once per template version.

Layouts are TSX files with zod schemas, so only Next.js can compile them
(``/api/template?group=<id>``, ``lib/server-template-layouts.ts``). The result is cached
in-process by ``TemplateInfo.fingerprint()``, which changes whenever a layout file or the
manifest changes; custom (database) templates are cached by a hash of their layout code.
Nothing here launches a browser.
"""

import asyncio
import logging
from typing import Any

import aiohttp
from fastapi import HTTPException

from templates.custom_layout_from_db import load_custom_presentation_layout
from templates.presentation_layout import PresentationLayoutModel
from utils.internal_http import internal_request_headers
from utils.internal_urls import nextjs_base_url

LOGGER = logging.getLogger(__name__)

_MAX_LOG_DETAIL = 600

_cache: dict[str, PresentationLayoutModel] = {}
_locks: dict[str, asyncio.Lock] = {}


def _preview_detail(text: str, limit: int = _MAX_LOG_DETAIL) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _template_fingerprint(layout_name: str) -> str | None:
    """Cache key for a folder template, or None when the id is not a known folder."""
    try:
        from chatppt.templates import discover_templates

        info = discover_templates().get(layout_name)
    except Exception as exc:  # noqa: BLE001 - discovery problems must not block generation
        LOGGER.warning("[template_layout] template discovery failed: %s", exc)
        return None
    return info.fingerprint() if info else None


async def _fetch_template_payload(layout_name: str) -> dict[str, Any]:
    url = f"{nextjs_base_url()}/api/template"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params={"group": layout_name}, headers=internal_request_headers()
            ) as response:
                if response.status == 200:
                    payload = await response.json()
                    if isinstance(payload, dict):
                        return payload
                    error = "invalid payload"
                else:
                    error = await response.text()
                    LOGGER.warning(
                        "[template_layout] %s HTTP %s template=%r body=%s",
                        url,
                        response.status,
                        layout_name,
                        _preview_detail(error or ""),
                    )
    except aiohttp.ClientError as exc:
        error = str(exc)
        LOGGER.warning(
            "[template_layout] %s failed template=%r error=%s", url, layout_name, error
        )
    raise HTTPException(
        status_code=404,
        detail=f"Template '{layout_name}' not found: {_preview_detail(error or 'unknown error')}",
    )


async def _load_layout(layout_name: str) -> PresentationLayoutModel:
    if layout_name.startswith("custom-"):
        return await load_custom_presentation_layout(layout_name)
    payload = await _fetch_template_payload(layout_name)
    if not payload.get("slides"):
        raise HTTPException(
            status_code=404, detail=f"Template '{layout_name}' not found"
        )
    return PresentationLayoutModel(**payload)


async def get_layout_by_name(layout_name: str) -> PresentationLayoutModel:
    """Layouts for ``layout_name``; compiled once per template fingerprint."""
    if layout_name.startswith("custom-"):
        # Custom templates cache inside the loader, keyed by their layout code.
        return await _load_layout(layout_name)

    fingerprint = _template_fingerprint(layout_name)
    if fingerprint is None:
        # Not a folder we can fingerprint (e.g. a template only Next.js knows about).
        return await _load_layout(layout_name)

    cached = _cache.get(fingerprint)
    if cached is not None:
        return cached.model_copy(deep=True)

    lock = _locks.setdefault(layout_name, asyncio.Lock())
    async with lock:
        cached = _cache.get(fingerprint)
        if cached is None:
            cached = await _load_layout(layout_name)
            # Drop stale versions of this template before storing the new one.
            for key in [k for k in _cache if k.split(":", 1)[0] == layout_name]:
                del _cache[key]
            _cache[fingerprint] = cached
            LOGGER.info(
                "[template_layout] cached template=%r slides=%d fingerprint=%s",
                layout_name,
                len(cached.slides),
                fingerprint,
            )
    return cached.model_copy(deep=True)


def clear_layout_cache() -> None:
    _cache.clear()
