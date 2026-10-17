"""User hooks: ``<data>/hooks.py`` may define any of

* ``before_outline(request: dict) -> dict | None`` - the outline request (``content``,
  ``n_slides``, ``language``, ``instructions``, ``tone``, ``verbosity`` ...), before the model
  sees it.
* ``after_slide(slide) -> slide | None`` - each generated slide (``slide.content`` is the
  layout data, ``slide.layout`` the layout id), before it is saved and streamed.
* ``before_export(deck: dict) -> dict | None`` - the presentation (with ``slides``) as the
  exporter is about to render it; changes affect the export only, not the saved deck.
* ``after_export(path: str) -> None`` - the exported file, once written.

A hook may change its argument in place or return a replacement (``None`` keeps the
argument); it may be ``async``. A missing file or function is a no-op. A hook that raises
is logged with its traceback and skipped: generation and export carry on with the
unchanged value. The file is re-read when it changes.
"""

from __future__ import annotations

import functools
import importlib.util
import inspect
import logging
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, TypeVar

LOGGER = logging.getLogger(__name__)

HookName = Literal["before_outline", "after_slide", "before_export", "after_export"]
HOOK_NAMES: tuple[HookName, ...] = ("before_outline", "after_slide", "before_export", "after_export")
MODULE_NAME = "chatppt_user_hooks"

T = TypeVar("T")

_cache: dict[str, Any] = {"path": None, "mtime": None, "module": None}


def hooks_path() -> Path:
    from chatppt.settings import get_settings

    return get_settings().data_dir / "hooks.py"


def _module(path: Path | None = None) -> ModuleType | None:
    path = path or hooks_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        _cache.update(path=path, mtime=None, module=None)
        return None
    if _cache["path"] == path and _cache["mtime"] == mtime:
        cached: ModuleType | None = _cache["module"]
        return cached
    module: ModuleType | None = None
    try:
        spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
        if spec is None or spec.loader is None:
            raise ImportError("not a Python module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        spec.loader.exec_module(module)
        found = [name for name in HOOK_NAMES if callable(getattr(module, name, None))]
        LOGGER.info("Loaded %s (hooks: %s)", path, ", ".join(found) or "none")
    except Exception:  # noqa: BLE001 - a broken hooks file must not stop generation
        LOGGER.exception("%s failed to load; hooks are off until it is fixed", path)
        sys.modules.pop(MODULE_NAME, None)
        module = None
    _cache.update(path=path, mtime=mtime, module=module)
    return module


def get_hook(name: HookName) -> Callable[[Any], Any] | None:
    module = _module()
    hook = getattr(module, name, None) if module else None
    return hook if callable(hook) else None


async def run_hook(name: HookName, value: T) -> T:
    """Run one hook on ``value``; returns its replacement, or ``value`` (possibly changed in
    place) when the hook returns None, is missing, or raises."""
    hook = get_hook(name)
    if hook is None:
        return value
    try:
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
    except Exception:  # noqa: BLE001 - logged, never raised
        LOGGER.exception("hooks.py %s raised; continuing without it", name)
        return value
    return value if result is None else result


def before_outline(fn: Callable[..., AsyncIterator[T]]) -> Callable[..., AsyncIterator[T]]:
    """Decorator for the outline generator: its arguments go through ``before_outline``."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> AsyncIterator[T]:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        request = dict(bound.arguments)
        changed = await run_hook("before_outline", request)
        if not isinstance(changed, dict):
            LOGGER.error("hooks.py before_outline must return a dict or None; ignored")
            changed = request
        allowed = {k: v for k, v in changed.items() if k in signature.parameters}
        async for chunk in fn(**allowed):
            yield chunk

    return wrapper
