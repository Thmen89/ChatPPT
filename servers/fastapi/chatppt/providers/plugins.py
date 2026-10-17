"""Providers added as files: every ``<data>/providers/*.py`` is imported and may call
``register_llm`` / ``register_image``. A file is re-imported when it changes; one that fails
to import is logged and skipped, never fatal.

Selecting one is ``llm.provider = "<id>"`` or ``images.provider = "<id>"`` in chatppt.toml
(credentials under ``[llm.providers.<id>]`` / ``[images.providers.<id>]``).
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from chatppt.providers.base import ImageProviderSpec
from chatppt.settings import LEGACY_IMAGE_IDS, LEGACY_LLM_IDS, Settings, get_settings

LOGGER = logging.getLogger(__name__)
MODULE_PREFIX = "chatppt_user_providers."

_loaded: dict[Path, int] = {}


def providers_dir(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).data_dir / "providers"


def load_plugins(folder: Path | None = None) -> list[str]:
    """Import new or changed provider files; returns the file names imported this call."""
    try:
        folder = folder or providers_dir()
        files = sorted(folder.glob("*.py")) if folder.is_dir() else []
    except OSError:
        return []
    imported = []
    for path in files:
        if path.name.startswith("_"):
            continue
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        if _loaded.get(path) == mtime:
            continue
        _loaded[path] = mtime
        name = MODULE_PREFIX + path.stem
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError("not a Python module")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except Exception:  # noqa: BLE001 - a broken plugin must not take the app down
            LOGGER.exception("Provider file %s failed to load; skipped", path)
            sys.modules.pop(name, None)
            continue
        imported.append(path.name)
        LOGGER.info("Loaded provider file %s", path.name)
    return imported


def plugin_llm_selected(settings: Settings | None = None) -> bool:
    """``llm.provider`` names a provider upstream code does not know and that is not a
    toml-only OpenAI-compatible endpoint (those are bridged as ``custom``)."""
    settings = settings or get_settings()
    provider = settings.llm.provider
    if not provider or provider in LEGACY_LLM_IDS or not settings.is_explicit("llm.provider"):
        return False
    creds = settings.llm.providers.get(provider)
    return not (creds and creds.base_url)


def selected_image_plugin(settings: Settings | None = None) -> Callable[[str, str], Awaitable[str]] | None:
    """The ``generate`` of the image provider chosen in chatppt.toml when it comes from a
    provider file, as an async ``(prompt, output_dir) -> path or URL``; else None."""
    from chatppt.providers.registry import image_providers

    settings = settings or get_settings()
    provider = settings.images.provider
    if not provider or provider in LEGACY_IMAGE_IDS:
        return None
    spec: ImageProviderSpec | None = image_providers().get(provider)
    if spec is None or spec.generate is None:
        return None
    generate = spec.generate

    async def run(prompt: str, output_dir: str) -> str:
        result = generate(prompt, output_dir)
        return await result if inspect.isawaitable(result) else result

    return run
