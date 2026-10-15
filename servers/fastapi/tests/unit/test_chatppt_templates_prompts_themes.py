import json
from pathlib import Path

import pytest

from chatppt import prompts, themes
from chatppt.templates import (
    TemplateManifest,
    default_builtin_dir,
    discover_templates,
    read_manifest,
    write_manifest,
)

LAYOUT = """
import * as z from "zod";
export const layoutId = "{id}";
export const layoutName = "{id}";
export const layoutDescription = "x";
export const Schema = z.object({{ title: z.string() }});
export default function L() {{ return null; }}
"""


def make_template(root: Path, tid: str, files: list[str], manifest: dict | None = None, legacy: dict | None = None) -> Path:
    folder = root / tid
    folder.mkdir(parents=True)
    for f in files:
        (folder / f).write_text(LAYOUT.format(id=f.removesuffix(".tsx")))
    if manifest is not None:
        (folder / "template.json").write_text(json.dumps(manifest))
    if legacy is not None:
        (folder / "settings.json").write_text(json.dumps(legacy))
    return folder


def test_builtin_templates_discoverable_from_legacy_settings():
    found = discover_templates(default_builtin_dir(), data_dir=Path("/nonexistent"))
    assert "general" in found
    general = found["general"]
    assert general.source == "builtin"
    assert general.manifest.icon_weight == "regular"
    assert general.manifest.default is True
    assert len(general.layout_files) >= 10
    assert all(p.suffix == ".tsx" for p in general.layout_files)
    assert "ExampleSlideLayoutTemplate.tsx" not in {p.name for p in found[next(iter(found))].layout_files}


def test_data_folder_replaces_builtin_and_manifest_orders_layouts(tmp_path):
    builtin = tmp_path / "builtin"
    data = tmp_path / "data"
    make_template(builtin, "house", ["B.tsx", "A.tsx"], legacy={"ordered": False, "icon_weight": "bold"})
    make_template(data, "house", ["Two.tsx", "One.tsx", "Three.tsx"],
                  manifest={"name": "House style", "ordered": True, "layouts": ["One.tsx", "Two.tsx", "Missing.tsx"], "icon_weight": "thin"})
    make_template(data, "Bad Id", ["X.tsx"], manifest={"name": "bad"})

    found = discover_templates(builtin, data)
    assert set(found) == {"house"}
    house = found["house"]
    assert house.source == "data"
    assert house.manifest.name == "House style"
    assert house.manifest.ordered is True
    assert [p.name for p in house.layout_files] == ["One.tsx", "Two.tsx"]
    fp1 = house.fingerprint()
    assert fp1.startswith("house:1:2:")
    (house.path / "One.tsx").write_text("changed")
    import os, time
    os.utime(house.path / "One.tsx", (time.time() + 5, time.time() + 5))
    assert house.fingerprint() != fp1


def test_write_and_read_manifest_round_trip(tmp_path):
    manifest = TemplateManifest(id="acme", name="Acme", ordered=True, icon_weight="fill", fonts=["Acme.ttf"])
    path = write_manifest(tmp_path / "acme", manifest)
    assert path.name == "template.json"
    assert read_manifest(tmp_path / "acme") == manifest


def test_manifest_rejects_bad_ids():
    with pytest.raises(ValueError):
        TemplateManifest(id="Has Space", name="x")


def test_prompt_override_and_render(tmp_path):
    text = prompts.render_prompt("slide_content.user", tmp_path, current_date_time="now", language="en", content="hello")
    assert "# Slide Language:\nen" in text and "hello" in text
    assert "{current_date_time}" not in text

    (tmp_path / "slide_content.user.md").write_text("OVERRIDE {content} {unknown}")
    assert prompts.render_prompt("slide_content.user", tmp_path, content="x") == "OVERRIDE x {unknown}"
    assert prompts.prompt_path("slide_content.user", tmp_path) == tmp_path / "slide_content.user.md"
    listed = {p.name: p for p in prompts.list_prompts(tmp_path)}
    assert listed["slide_content.user"].overridden is True
    assert listed["slide_content.system"].overridden is False
    with pytest.raises(prompts.PromptNotFound):
        prompts.load_prompt("does-not-exist", tmp_path)


def test_default_theme_and_user_theme(tmp_path):
    default = themes.load_theme("default", tmp_path)
    assert default.colors.accent == "#2563eb"
    assert default.css_variables()["--chatppt-color-accent"] == "#2563eb"

    (tmp_path / "house.json").write_text(json.dumps({
        "name": "House", "colors": {"primary": "#000", "accent": "#FF0000"}, "fonts": {"heading": "Georgia"},
        "footer": "Confidential",
    }))
    house = themes.load_theme("house", tmp_path)
    assert house.id == "house" and house.colors.accent == "#ff0000" and house.fonts.body == "Inter"
    assert set(themes.list_themes(tmp_path)) == {"default", "house"}
    (tmp_path / "broken.json").write_text(json.dumps({"name": "b", "colors": {"primary": "red"}}))
    assert "broken" not in themes.list_themes(tmp_path)
