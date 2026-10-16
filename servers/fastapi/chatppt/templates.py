"""Templates as folders.

A template is a directory holding a ``template.json`` manifest and one ``.tsx`` layout per
slide type. Built-in templates live in ``servers/nextjs/app/presentation-templates/<id>/``
and user templates in ``<data>/templates/<id>/``; a user folder with the same id replaces
the built-in one. Both servers discover templates with the same rules (see
``servers/nextjs/lib/template-dirs.ts``).

Layout files keep the format upstream already uses: each exports ``layoutId``,
``layoutName``, ``layoutDescription``, a zod ``Schema`` and a default React component.
Until a built-in folder gains ``template.json`` its legacy ``settings.json`` is read.

Folder layout::

    <id>/
      template.json      manifest (below)
      *.tsx              layouts, one per slide type
      theme.json         optional theme tokens (chatppt/themes.py)
      fonts/  assets/    optional files the layouts reference by relative URL
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, Field, field_validator

from chatppt.settings import IconWeight

MANIFEST_NAME = "template.json"
LEGACY_SETTINGS_NAME = "settings.json"
LAYOUT_SUFFIX = ".tsx"
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SKIP_FILES = {"ExampleSlideLayoutTemplate.tsx"}


class TemplateManifest(BaseModel):
    id: str = Field(description="Folder name; lowercase letters, digits, - and _.")
    name: str = Field(description="Shown in the template picker.")
    description: str = ""
    version: int = Field(default=1, ge=1, description="Bump when layouts change incompatibly.")
    ordered: bool = Field(
        default=False, description="Use layouts in file order instead of letting the model pick one per slide."
    )
    default: bool = Field(default=False, description="Offer this template first.")
    icon_weight: IconWeight = "regular"
    layouts: list[str] | None = Field(
        default=None, description="Layout file names in order; default is every .tsx sorted by name."
    )
    theme: str | None = Field(default=None, description="theme.json in the folder, or a theme id from <data>/themes.")
    fonts: list[str] = Field(default_factory=list, description="Font files under fonts/ to load with the layouts.")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not TEMPLATE_ID_RE.match(value):
            raise ValueError("template id must be lowercase letters, digits, '-' or '_'")
        return value


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    path: Path
    manifest: TemplateManifest
    source: Literal["builtin", "data"]
    layout_files: tuple[Path, ...] = field(default_factory=tuple)

    def fingerprint(self) -> str:
        """Changes whenever a layout or the manifest changes; a cache key for compiled schemas."""
        newest = 0.0
        for p in (*self.layout_files, self.path / MANIFEST_NAME, self.path / LEGACY_SETTINGS_NAME):
            if p.exists():
                newest = max(newest, p.stat().st_mtime)
        return f"{self.id}:{self.manifest.version}:{len(self.layout_files)}:{newest:.0f}"


def default_builtin_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "nextjs" / "app" / "presentation-templates"


def read_manifest(folder: Path) -> TemplateManifest:
    """``template.json`` if present, else the legacy ``settings.json`` plus folder name."""
    manifest_path = folder / MANIFEST_NAME
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data.setdefault("id", folder.name)
        data.setdefault("name", folder.name)
        return TemplateManifest.model_validate(data)

    legacy: dict[str, Any] = {}
    legacy_path = folder / LEGACY_SETTINGS_NAME
    if legacy_path.is_file():
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            legacy = {}
    icon_weight = str(legacy.get("icon_weight") or "regular").lower().replace("_", "-")
    return TemplateManifest(
        id=folder.name.lower(),
        name=folder.name,
        description=str(legacy.get("description") or ""),
        ordered=bool(legacy.get("ordered", False)),
        default=bool(legacy.get("default", False)),
        icon_weight=cast(IconWeight, icon_weight if icon_weight in get_args(IconWeight) else "regular"),
    )


def layout_files(folder: Path, manifest: TemplateManifest) -> tuple[Path, ...]:
    if manifest.layouts:
        return tuple(folder / name for name in manifest.layouts if (folder / name).is_file())
    return tuple(
        sorted(
            p
            for p in folder.glob(f"*{LAYOUT_SUFFIX}")
            if p.is_file() and p.name not in _SKIP_FILES and ".test." not in p.name and ".spec." not in p.name
        )
    )


def load_template(folder: Path, source: Literal["builtin", "data"]) -> TemplateInfo | None:
    if not folder.is_dir():
        return None
    try:
        manifest = read_manifest(folder)
    except (ValueError, json.JSONDecodeError):
        return None
    files = layout_files(folder, manifest)
    if not files:
        return None
    return TemplateInfo(id=manifest.id, path=folder, manifest=manifest, source=source, layout_files=files)


def discover_templates(builtin_dir: Path | None = None, data_dir: Path | None = None) -> dict[str, TemplateInfo]:
    """All templates by id; a data-dir folder replaces a built-in one with the same id."""
    if data_dir is None:
        from chatppt.settings import get_settings

        data_dir = get_settings().templates_dir
    found: dict[str, TemplateInfo] = {}
    for base, source in ((builtin_dir or default_builtin_dir(), "builtin"), (data_dir, "data")):
        if not base or not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
            info = load_template(folder, source)  # type: ignore[arg-type]
            if info:
                found[info.id] = info
    return found


def write_manifest(folder: Path, manifest: TemplateManifest) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MANIFEST_NAME
    path.write_text(json.dumps(manifest.model_dump(exclude_none=True), indent=2) + "\n", encoding="utf-8")
    return path
