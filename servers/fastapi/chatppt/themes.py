"""Themes as tokens.

A theme is one small JSON file of colours and a font. Layouts read the tokens as CSS
variables (``--primary-color``, ``--background-color``, ``--card-color``, ``--stroke``,
``--primary-text``, ``--background-text``, ``--graph-0`` … ``--graph-9``,
``--heading-font-family``, ``--body-font-family``); the built-in layouts fall back to their
own colours when a variable is unset, so no theme means each template's own look.

Shipped themes live in ``servers/fastapi/themes/``; users drop ``<data>/themes/<id>.json``
(same id replaces a shipped one). Themes appear in the editor's theme menu, and
``defaults.theme`` in chatppt.toml applies one to every new deck.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

LOGGER = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "themes"
THEME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
GRAPH_SLOTS = 10
_DEFAULT_GRAPH = [
    "#2563eb",
    "#16a34a",
    "#f59e0b",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#475569",
]


def _hex(value: str) -> str:
    if not isinstance(value, str) or not HEX_RE.match(value):
        raise ValueError(f"colour must be a hex value like #1a2b3c, got {value!r}")
    return value.lower()


class ThemeColors(BaseModel):
    primary: str = Field(default="#111827", description="Accents, buttons, highlights.")
    background: str = Field(default="#ffffff", description="Slide background.")
    card: str = Field(default="#f3f4f6", description="Boxes and cards on the slide.")
    stroke: str = Field(default="#e5e7eb", description="Borders and rules.")
    primary_text: str = Field(default="#ffffff", description="Text on the primary colour.")
    background_text: str = Field(default="#111827", description="Body text.")
    graph: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_GRAPH),
        min_length=1,
        max_length=GRAPH_SLOTS,
        description="Chart series colours, in order (repeated to fill ten slots).",
    )

    @field_validator("primary", "background", "card", "stroke", "primary_text", "background_text")
    @classmethod
    def _valid_hex(cls, value: str) -> str:
        return _hex(value)

    @field_validator("graph")
    @classmethod
    def _valid_graph(cls, value: list[str]) -> list[str]:
        return [_hex(v) for v in value]

    def graph_slots(self) -> list[str]:
        return [self.graph[i % len(self.graph)] for i in range(GRAPH_SLOTS)]


class ThemeFont(BaseModel):
    name: str = Field(default="Inter", description="Font family for headings and body.")
    url: str = Field(
        default="",
        description="Stylesheet or font file to load it from (e.g. /app_data/fonts/x.woff2); empty uses an installed font.",
    )


class Theme(BaseModel):
    id: str = Field(description="File name without .json; lowercase letters, digits, - and _.")
    name: str
    description: str = ""
    colors: ThemeColors = Field(default_factory=ThemeColors)
    font: ThemeFont = Field(default_factory=ThemeFont)
    logo: str | None = Field(default=None, description="URL of a logo the layouts that support one show.")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not THEME_ID_RE.match(value):
            raise ValueError("theme id must be lowercase letters, digits, '-' or '_'")
        return value

    def css_variables(self) -> dict[str, str]:
        c = self.colors
        out = {
            "--primary-color": c.primary,
            "--background-color": c.background,
            "--card-color": c.card,
            "--stroke": c.stroke,
            "--primary-text": c.primary_text,
            "--background-text": c.background_text,
        }
        out.update({f"--graph-{i}": colour for i, colour in enumerate(c.graph_slots())})
        out["--heading-font-family"] = out["--body-font-family"] = f'"{self.font.name}"'
        return out

    def presentation_theme(self) -> dict[str, Any]:
        """The shape the editor and exporter store on a presentation (``presentation.theme``)."""
        c = self.colors
        colors: dict[str, str] = {
            "primary": c.primary,
            "background": c.background,
            "card": c.card,
            "stroke": c.stroke,
            "primary_text": c.primary_text,
            "background_text": c.background_text,
        }
        colors.update({f"graph_{i}": colour for i, colour in enumerate(c.graph_slots())})
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "user": "system",
            "logo": None,
            "logo_url": self.logo,
            "company_name": None,
            "data": {"colors": colors, "fonts": {"textFont": {"name": self.font.name, "url": self.font.url}}},
        }


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
        if THEME_ID_RE.match(theme_id) and candidate.is_file():
            return candidate
    return None


def load_theme(theme_id: str, data_dir: Path | None = None) -> Theme:
    path = theme_path(theme_id, data_dir)
    if path is None:
        raise KeyError(f"theme '{theme_id}' not found")
    return load_theme_file(path)


def list_themes(data_dir: Path | None = None) -> dict[str, Theme]:
    """Shipped themes, then ``<data>/themes`` (same id replaces). Invalid files are skipped
    with a warning."""
    data_dir = _themes_dir() if data_dir is None else data_dir
    themes: dict[str, Theme] = {}
    for base in (BUILTIN_DIR, data_dir):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                theme = load_theme_file(path)
            except (ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("Skipping theme %s: %s", path, exc)
                continue
            themes[theme.id] = theme
    return themes


def default_presentation_theme() -> dict[str, Any] | None:
    """``defaults.theme`` from chatppt.toml as a presentation theme, for new decks; None when
    unset or not found (the deck keeps its template's own colours)."""
    from chatppt.settings import get_settings

    theme_id = get_settings().defaults.theme
    if not theme_id:
        return None
    try:
        return load_theme(theme_id).presentation_theme()
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning("defaults.theme %r ignored: %s", theme_id, exc)
        return None
