"""Writing ``chatppt.toml``: what the settings UI saves, and the one-time move off
``userConfig.json``.

The settings UI still speaks upstream's flat key names (``LLM``, ``OPENAI_API_KEY``, ...);
they are the legacy names in ``settings.LEGACY_ENV`` and map one-to-one onto toml keys.
Writes are atomic, keep the previous file as ``chatppt.toml.bak`` and reload the settings in
place, so a change applies to the next request without a restart. Only keys that differ
from what is already in effect are written, so values that come from the environment stay
there.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chatppt.settings import (
    LEGACY_ENV,
    Legacy,
    Settings,
    _get_path,
    _set_path,
    config_path,
    get_settings,
    reload_settings,
)

LOGGER = logging.getLogger(__name__)

_UI_PREFIXES = ("llm.", "images.")
_UI_EXTRA = {"features.images", "features.web_search"}
UI_KEYS: dict[str, Legacy] = {e.env: e for e in LEGACY_ENV if e.path.startswith(_UI_PREFIXES) or e.path in _UI_EXTRA}
"""Flat names the settings UI reads and writes, with their toml key."""
_UI_BOOLS = {name for name, e in UI_KEYS.items() if e.parse is not str}

_lock = threading.Lock()


def can_change_keys() -> bool:
    """``CAN_CHANGE_KEYS=false`` (deploy-time policy, env only) locks the settings UI."""
    return (os.environ.get("CAN_CHANGE_KEYS") or "").strip().lower() != "false"


# --------------------------------------------------------------------------- toml writing

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{ " + ", ".join(f"{_key(str(k))} = {_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def dump_toml(data: Mapping[str, Any]) -> str:
    """Serialise plain tables, scalars and lists (all ``chatppt.toml`` uses)."""
    lines: list[str] = []

    def table(node: Mapping[str, Any], prefix: tuple[str, ...]) -> None:
        scalars = [(k, v) for k, v in node.items() if not isinstance(v, Mapping)]
        tables = [(k, v) for k, v in node.items() if isinstance(v, Mapping)]
        if prefix and scalars:
            lines.append("")
            lines.append("[" + ".".join(_key(p) for p in prefix) + "]")
        lines.extend(f"{_key(k)} = {_value(v)}" for k, v in scalars)
        for k, v in tables:
            table(v, (*prefix, k))

    table(data, ())
    return "\n".join(lines).lstrip("\n") + "\n"


def read_toml(path: Path) -> dict[str, Any]:
    import tomllib

    if not path.is_file():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def write_toml(path: Path, data: Mapping[str, Any]) -> None:
    """Atomic write; the previous file is kept as ``<name>.bak``. Mode 0600 (keys live here)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# ChatPPT configuration. Reference: docs/config-reference.md\n# Saved by the settings page; the previous version is in chatppt.toml.bak.\n\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(header + dump_toml(data))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        if path.is_file():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _delete_path(raw: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    trail: list[tuple[dict[str, Any], str]] = []
    node: Any = raw
    for part in parts[:-1]:
        if not isinstance(node, dict) or not isinstance(node.get(part), dict):
            return
        trail.append((node, part))
        node = node[part]
    node.pop(parts[-1], None)
    for parent, key in reversed(trail):  # prune tables left empty
        if parent[key]:
            break
        del parent[key]


def update_config(changes: Mapping[str, Any], path: Path | None = None) -> Settings:
    """Set dotted keys in ``chatppt.toml`` (``None`` removes one), then reload settings."""
    path = path or config_path()
    with _lock:
        raw = read_toml(path)
        for dotted, value in changes.items():
            if value is None:
                _delete_path(raw, dotted)
            else:
                _set_path(raw, dotted, value)
        write_toml(path, raw)
    return reload_settings()


# --------------------------------------------------------------------------- settings UI


def _ui_bool(name: str, value: Any) -> bool:
    entry = UI_KEYS[name]
    return bool(entry.parse(str(value)))


def ui_values(settings: Settings | None = None) -> dict[str, Any]:
    """The effective settings in the UI's flat shape (booleans as booleans)."""
    settings = settings or get_settings()
    dumped = settings.model_dump()
    out: dict[str, Any] = {}
    for name, entry in UI_KEYS.items():
        value = _get_path(dumped, entry.path)
        if value is None or value == "":
            continue
        if name in _UI_BOOLS:
            # Flat names are phrased as the legacy env var ("DISABLE_..."); invert where it is.
            out[name] = entry.to_env(value) == "true"
        else:
            out[name] = value
    return out


def ui_changes(incoming: Mapping[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Toml changes for a settings-page save: only keys that differ from what is in effect,
    or that the file already sets (so clearing a field removes it)."""
    settings = settings or get_settings()
    dumped = settings.model_dump()
    changes: dict[str, Any] = {}
    for name, raw in incoming.items():
        entry = UI_KEYS.get(name)
        if entry is None:
            continue
        if name in _UI_BOOLS:
            value: Any = None if raw is None or raw == "" else _ui_bool(name, raw)
        else:
            value = str(raw).strip() if raw is not None else None
            value = value or None
        current = _get_path(dumped, entry.path)
        if settings.is_explicit(entry.path):
            if value != current:
                changes[entry.path] = value
        elif value is not None and value != current:
            changes[entry.path] = value
    return changes


def save_ui_values(incoming: Mapping[str, Any]) -> Settings:
    changes = ui_changes(incoming)
    return update_config(changes) if changes else get_settings()


# --------------------------------------------------------------------------- userConfig.json


def user_config_json_path(settings: Settings | None = None, environ: Mapping[str, str] = os.environ) -> Path:
    explicit = (environ.get("USER_CONFIG_PATH") or "").strip()
    return Path(explicit) if explicit else (settings or get_settings()).data_dir / "userConfig.json"


def migrate_user_config_json(settings: Settings | None = None, environ: Mapping[str, str] = os.environ) -> list[str]:
    """Once: copy what the old settings page saved in ``userConfig.json`` into
    ``chatppt.toml``. Values the environment provides, and keys the toml already sets, are
    left alone. The json stays where it is (login and Codex sign-in still live there) and a
    copy is kept as ``userConfig.json.migrated``, which also marks the migration done."""
    settings = settings or get_settings()
    source = user_config_json_path(settings, environ)
    marker = source.with_name(source.name + ".migrated")
    if not source.is_file() or marker.exists():
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Could not read %s; nothing migrated", source)
        return []
    if not isinstance(data, dict):
        return []

    changes: dict[str, Any] = {}
    for name, entry in UI_KEYS.items():
        value = data.get(name)
        if value is None or value == "" or (environ.get(name) or "").strip():
            continue
        if settings.is_explicit(entry.path):
            continue
        changes[entry.path] = entry.parse(str(value))
    # "Images off" with no provider is what an unconfigured install looks like; not a choice.
    if changes.get("features.images") is False and "images.provider" not in changes:
        del changes["features.images"]
    if changes:
        update_config(changes)
    shutil.copy2(source, marker)
    LOGGER.info("Moved %d setting(s) from %s into %s (backup: %s)", len(changes), source, config_path(), marker.name)
    return sorted(changes)
