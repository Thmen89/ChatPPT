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

import hashlib
import json
import re
import shutil
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
    fonts: dict[str, str] = Field(
        default_factory=dict,
        description="Font family -> URL or a file under fonts/ (a list of files under fonts/ also works).",
    )

    @field_validator("fonts", mode="before")
    @classmethod
    def _fonts_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {Path(str(name)).stem: f"fonts/{Path(str(name)).name}" for name in value}
        return value

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
        """Changes whenever a file in the folder changes; a cache key for compiled schemas."""
        digest = hashlib.sha1(usedforsecurity=False)
        for p in sorted(self.path.iterdir()):
            if p.is_file():
                st = p.stat()
                digest.update(f"{p.name}:{st.st_mtime_ns}:{st.st_size};".encode())
        return f"{self.id}:{self.manifest.version}:{len(self.layout_files)}:{digest.hexdigest()[:12]}"

    def layouts(self) -> list[LayoutSource]:
        return [read_layout(p) for p in self.layout_files]

    def modules(self) -> dict[str, str]:
        """Other ``.ts``/``.tsx`` files in the folder that layouts may import (``./Helper``)."""
        layout_names = {p.name for p in self.layout_files}
        return {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(self.path.iterdir())
            if p.is_file() and p.suffix in {".ts", ".tsx"} and p.name not in layout_names
        }

    def file(self, relative: str) -> Path | None:
        """A file under ``fonts/`` or ``assets/``; None for anything outside them."""
        target = (self.path / relative).resolve()
        for sub in ("fonts", "assets"):
            base = (self.path / sub).resolve()
            if target.is_relative_to(base) and target.is_file():
                return target
        return None


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
            if p.is_file()
            and p.name not in _SKIP_FILES
            and ".test." not in p.name
            and ".spec." not in p.name
            and _declares_layout(p)
        )
    )


_declares_cache: dict[Path, tuple[int, bool]] = {}


def _declares_layout(path: Path) -> bool:
    """A ``.tsx`` is a layout when it declares a ``layoutId``; others are helper modules."""
    mtime = path.stat().st_mtime_ns
    cached = _declares_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    found = _LAYOUT_ID_RE.search(path.read_text(encoding="utf-8", errors="replace")) is not None
    _declares_cache[path] = (mtime, found)
    return found


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


@dataclass(frozen=True)
class LayoutSource:
    file: str
    layout_id: str
    layout_name: str
    code: str


_LAYOUT_CONST = r"""(?:export\s+)?const\s+(?:slide)?{name}\s*(?::\s*string\s*)?=\s*(['"`])(.*?)\1"""
_LAYOUT_ID_RE = re.compile(_LAYOUT_CONST.format(name="[lL]ayoutId"))
_LAYOUT_NAME_RE = re.compile(_LAYOUT_CONST.format(name="[lL]ayoutName"))


def read_layout(path: Path) -> LayoutSource:
    """A layout file's code with its ``layoutId``/``layoutName`` (file stem when absent)."""
    code = path.read_text(encoding="utf-8")
    layout_id = _LAYOUT_ID_RE.search(code)
    layout_name = _LAYOUT_NAME_RE.search(code)
    return LayoutSource(
        file=path.name,
        layout_id=layout_id.group(2) if layout_id else path.stem,
        layout_name=layout_name.group(2) if layout_name else path.stem,
        code=code,
    )


def get_template(
    template_id: str, builtin_dir: Path | None = None, data_dir: Path | None = None
) -> TemplateInfo | None:
    """One template by id. A bare UUID also finds ``custom-<uuid>`` (imported templates)."""
    found = discover_templates(builtin_dir, data_dir)
    return found.get(template_id) or found.get(f"custom-{template_id}")


def _layout_file_name(layout_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", layout_id).strip("-") or "layout"
    return f"{stem}{LAYOUT_SUFFIX}"


def write_template(
    root: Path, manifest: TemplateManifest, layouts: list[tuple[str, str]], replace_layouts: bool = True
) -> TemplateInfo:
    """Write ``root/<id>/``: the manifest and one ``<layout_id>.tsx`` per ``(layout_id, code)``.
    With ``replace_layouts`` the folder's other layout files are removed first."""
    folder = root / manifest.id
    folder.mkdir(parents=True, exist_ok=True)
    if replace_layouts:
        for old in folder.glob(f"*{LAYOUT_SUFFIX}"):
            old.unlink()
    names = [_layout_file_name(layout_id) for layout_id, _ in layouts]
    for name, (_, code) in zip(names, layouts, strict=True):
        (folder / name).write_text(code, encoding="utf-8")
    if replace_layouts:  # keep the given order (an import's slide order), not file-name order
        manifest = manifest.model_copy(update={"layouts": list(dict.fromkeys(names))})
    write_manifest(folder, manifest)
    info = load_template(folder, "data")
    if info is None:
        raise ValueError(f"template '{manifest.id}' has no layouts")
    return info


def write_layout(info: TemplateInfo, layout_id: str, code: str) -> Path:
    """Replace the file holding ``layout_id`` (or add one)."""
    for layout in info.layouts():
        if layout.layout_id == layout_id:
            path = info.path / layout.file
            break
    else:
        path = info.path / _layout_file_name(layout_id)
        if info.manifest.layouts is not None:
            write_manifest(info.path, info.manifest.model_copy(update={"layouts": [*info.manifest.layouts, path.name]}))
    path.write_text(code, encoding="utf-8")
    return path


def delete_template(info: TemplateInfo) -> None:
    if info.source != "data":
        raise ValueError("built-in templates cannot be deleted")
    shutil.rmtree(info.path)


def write_manifest(folder: Path, manifest: TemplateManifest) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MANIFEST_NAME
    path.write_text(json.dumps(manifest.model_dump(exclude_none=True), indent=2) + "\n", encoding="utf-8")
    return path
