"""Themes as tokens.

A theme is one small JSON file: colours, fonts, spacing, logo and footer. Any template can
read the tokens (layouts receive them as CSS variables ``--chatppt-<token>``), so one house
theme restyles every template. Shipped defaults live in ``servers/fastapi/themes/``; users
drop ``<data>/themes/<id>.json``; a template folder may carry its own ``theme.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "themes"
THEME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


class ThemeColors(BaseModel):
    primary: str = "#111827"
    secondary: str = "#374151"
    accent: str = "#2563eb"
    background: str = "#ffffff"
    surface: str = "#f3f4f6"
    text: str = "#111827"
    muted: str = "#6b7280"

    @field_validator("*")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not HEX_RE.match(value):
            raise ValueError(f"colour must be a hex value like #1a2b3c, got {value!r}")
        return value.lower()


class ThemeFonts(BaseModel):
    heading: str = "Inter"
    body: str = "Inter"
    mono: str = "JetBrains Mono"


class Theme(BaseModel):
    id: str = Field(description="File name without .json; lowercase letters, digits, - and _.")
    name: str
    colors: ThemeColors = Field(default_factory=ThemeColors)
    fonts: ThemeFonts = Field(default_factory=ThemeFonts)
    spacing: Literal["compact", "regular", "airy"] = "regular"
    radius: int = Field(default=8, ge=0, le=48, description="Corner radius in px for cards and images.")
    logo: str | None = Field(
        default=None, description="URL or path (relative to the theme file) of a logo shown on slides."
    )
    footer: str | None = Field(default=None, description="Footer text on every slide, e.g. a confidentiality note.")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not THEME_ID_RE.match(value):
            raise ValueError("theme id must be lowercase letters, digits, '-' or '_'")
        return value

    def css_variables(self) -> dict[str, str]:
        out = {f"--chatppt-color-{k}": v for k, v in self.colors.model_dump().items()}
        out.update({f"--chatppt-font-{k}": v for k, v in self.fonts.model_dump().items()})
        out["--chatppt-radius"] = f"{self.radius}px"
        out["--chatppt-spacing"] = self.spacing
        return out


def _themes_dir() -> Path:
    from chatppt.settings import get_settings

    return get_settings().themes_dir


def load_theme_file(path: Path) -> Theme:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("id", path.stem)
    data.setdefault("name", path.stem)
    return Theme.model_validate(data)


def theme_path(theme_id: str, data_dir: Path | None = None) -> Path | None:
    data_dir = _themes_dir() if data_dir is None else data_dir
    for base in (data_dir, BUILTIN_DIR):
        candidate = base / f"{theme_id}.json"
        if candidate.is_file():
            return candidate
    return None


def load_theme(theme_id: str, data_dir: Path | None = None) -> Theme:
    path = theme_path(theme_id, data_dir)
    if path is None:
        raise KeyError(f"theme '{theme_id}' not found")
    return load_theme_file(path)


def list_themes(data_dir: Path | None = None) -> dict[str, Theme]:
    data_dir = _themes_dir() if data_dir is None else data_dir
    themes: dict[str, Theme] = {}
    for base in (BUILTIN_DIR, data_dir):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                theme = load_theme_file(path)
            except (ValueError, json.JSONDecodeError):
                continue
            themes[theme.id] = theme
    return themes
