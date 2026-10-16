"""Prompts as files.

Every LLM prompt ships as a readable file in ``servers/fastapi/prompts/<name>.md`` and can
be overridden by dropping ``<data>/prompts/<name>.md`` next to the config file. No rebuild;
the file is re-read when its mtime changes.

Placeholders use ``{name}`` (``str.format`` syntax). Unknown placeholders are left as-is,
so a literal brace in prose is harmless; JSON examples inside a prompt must double their
braces (``{{`` ``}}``).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "prompts"
SUFFIX = ".md"


class PromptNotFound(KeyError):
    pass


class _Safe(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class PromptInfo:
    name: str
    path: Path
    overridden: bool


def _override_dir() -> Path:
    from chatppt.settings import get_settings

    return get_settings().prompts_dir


def prompt_path(name: str, override_dir: Path | None = None) -> Path:
    """Where ``name`` is read from: the data-dir override if present, else the shipped file."""
    override_dir = _override_dir() if override_dir is None else override_dir
    for base in (override_dir, BUILTIN_DIR):
        candidate = base / f"{name}{SUFFIX}"
        if candidate.is_file():
            return candidate
    raise PromptNotFound(f"prompt '{name}' not found in {override_dir} or {BUILTIN_DIR}")


_cache: dict[Path, tuple[float, str]] = {}


def load_prompt(name: str, override_dir: Path | None = None) -> str:
    path = prompt_path(name, override_dir)
    mtime = os.stat(path).st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    _cache[path] = (mtime, text)
    return text


def render_prompt(name: str, override_dir: Path | None = None, **values: Any) -> str:
    return load_prompt(name, override_dir).format_map(_Safe(values))


def list_prompts(override_dir: Path | None = None) -> list[PromptInfo]:
    override_dir = _override_dir() if override_dir is None else override_dir
    names: dict[str, PromptInfo] = {}
    for base, overridden in ((BUILTIN_DIR, False), (override_dir, True)):
        if not base.is_dir():
            continue
        for path in sorted(base.glob(f"*{SUFFIX}")):
            names[path.stem] = PromptInfo(path.stem, path, overridden)
    return [names[k] for k in sorted(names)]


def builtin_names() -> Iterable[str]:
    return (p.stem for p in sorted(BUILTIN_DIR.glob(f"*{SUFFIX}")))
