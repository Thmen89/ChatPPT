"""Template folders: write/read, runtime discovery, the folder-backed endpoints and the
one-time move of database templates into folders."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import chatppt.settings as settings_mod
from chatppt.templates import (
    TemplateManifest,
    delete_template,
    discover_templates,
    get_template,
    write_layout,
    write_template,
)
from models.sql.presentation_layout_code import PresentationLayoutCodeModel
from models.sql.template import TemplateModel
from templates import custom_layout_from_db, handler

LAYOUT = """import * as z from "zod";
import {{ Badge }} from "./Badge";
export const layoutId = "{id}";
export const layoutName = "{name}";
export const layoutDescription = "x";
export const Schema = z.object({{ title: z.string() }});
export default function L() {{ return <img src="./assets/logo.png" />; }}
"""
HELPER = "export function Badge() { return null; }\n"


def layout(layout_id: str, name: str | None = None) -> str:
    return LAYOUT.format(id=layout_id, name=name or layout_id.title())


@pytest.fixture
def templates_root(tmp_path, monkeypatch):
    """``<data>/templates`` in a temp folder; built-ins stay the real ones."""
    for name in list(os.environ):
        if name.startswith("CHATPPT_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(settings_mod, "_loaded", None)
    root = tmp_path / "templates"
    root.mkdir()
    yield root
    settings_mod._loaded = None


def test_write_template_keeps_slide_order_and_reads_back(templates_root):
    manifest = TemplateManifest(id="desk", name="Desk")
    info = write_template(templates_root, manifest, [("title", layout("title")), ("chart", layout("chart"))])
    (info.path / "Badge.tsx").write_text(HELPER)

    found = get_template("desk")
    assert found is not None and found.source == "data"
    assert [item.layout_id for item in found.layouts()] == ["title", "chart"]
    assert found.manifest.layouts == ["title.tsx", "chart.tsx"]
    assert found.modules() == {"Badge.tsx": HELPER}  # no layoutId: a helper, not a layout


def test_helper_tsx_without_layout_id_is_not_a_layout(templates_root):
    folder = templates_root / "plain"
    folder.mkdir()
    (folder / "template.json").write_text(json.dumps({"id": "plain", "name": "Plain"}))
    (folder / "A.tsx").write_text(layout("a"))
    (folder / "ChartPrimitives.tsx").write_text(HELPER)
    info = get_template("plain")
    assert info is not None
    assert [p.name for p in info.layout_files] == ["A.tsx"]
    assert list(info.modules()) == ["ChartPrimitives.tsx"]


def test_bare_uuid_resolves_imported_folder(templates_root):
    template_uuid = str(uuid.uuid4())
    write_template(
        templates_root, TemplateManifest(id=f"custom-{template_uuid}", name="Imported"), [("a", layout("a"))]
    )
    info = get_template(template_uuid)
    assert info is not None and info.id == f"custom-{template_uuid}"


def test_write_layout_replaces_or_appends(templates_root):
    info = write_template(templates_root, TemplateManifest(id="desk", name="Desk"), [("a", layout("a"))])
    write_layout(info, "a", layout("a", "Renamed"))
    write_layout(info, "b", layout("b"))
    again = get_template("desk")
    assert again is not None
    assert [(item.layout_id, item.layout_name) for item in again.layouts()] == [("a", "Renamed"), ("b", "B")]


def test_fingerprint_changes_when_a_file_changes(templates_root):
    info = write_template(templates_root, TemplateManifest(id="desk", name="Desk"), [("a", layout("a"))])
    before = info.fingerprint()
    path = info.path / "a.tsx"
    path.write_text(layout("a", "Edited"))
    later = time.time() + 5
    os.utime(path, (later, later))
    assert get_template("desk").fingerprint() != before  # type: ignore[union-attr]


def test_files_are_confined_to_fonts_and_assets(templates_root):
    info = write_template(templates_root, TemplateManifest(id="desk", name="Desk"), [("a", layout("a"))])
    (info.path / "assets").mkdir()
    (info.path / "assets" / "logo.png").write_bytes(b"png")
    assert info.file("assets/logo.png") == (info.path / "assets" / "logo.png").resolve()
    assert info.file("template.json") is None
    assert info.file("assets/../template.json") is None
    assert info.file("../../etc/passwd") is None


def test_builtins_cannot_be_deleted_and_data_folders_can(templates_root):
    builtin = discover_templates()["general"]
    with pytest.raises(ValueError):
        delete_template(builtin)
    info = write_template(templates_root, TemplateManifest(id="desk", name="Desk"), [("a", layout("a"))])
    delete_template(info)
    assert not info.path.exists()


def test_data_folder_overrides_builtin_id(templates_root):
    write_template(templates_root, TemplateManifest(id="general", name="My general"), [("a", layout("a"))])
    info = get_template("general")
    assert info is not None and info.source == "data" and info.manifest.name == "My general"


# ---- endpoints ---------------------------------------------------------------------------


def test_listing_includes_dropped_in_folder_with_fingerprint(templates_root):
    write_template(templates_root, TemplateManifest(id="desk", name="Desk", description="d"), [("a", layout("a"))])
    listed = asyncio.run(handler.get_all_templates(include_defaults=True))
    ids = [item.id for item in listed]
    assert "general" in ids and "desk" in ids
    desk = next(item for item in listed if item.id == "desk")
    assert desk.total_layouts == 1 and desk.fingerprint and desk.description == "d"


def test_layouts_endpoint_serves_code_modules_and_folder_urls(templates_root):
    manifest = TemplateManifest(id="desk", name="Desk", fonts={"Inter": "fonts/Inter.woff2"})
    info = write_template(templates_root, manifest, [("a", layout("a"))])
    (info.path / "Badge.tsx").write_text(HELPER)

    response = asyncio.run(handler.get_layouts(template_id="desk"))
    assert response.template is not None and response.template.id == "desk"
    assert response.fingerprint == get_template("desk").fingerprint()  # type: ignore[union-attr]
    assert list(response.modules) == ["Badge.tsx"]
    code = response.layouts[0].layout_code
    assert '"/api/v1/ppt/template/desk/files/assets/logo.png"' in code
    assert response.fonts == {"Inter": "/api/v1/ppt/template/desk/files/fonts/Inter.woff2"}

    with pytest.raises(HTTPException) as missing:
        asyncio.run(handler.get_layouts(template_id="nope"))
    assert missing.value.status_code == 404


def test_template_file_endpoint_refuses_paths_outside_assets(templates_root):
    info = write_template(templates_root, TemplateManifest(id="desk", name="Desk"), [("a", layout("a"))])
    (info.path / "assets").mkdir()
    (info.path / "assets" / "logo.png").write_bytes(b"png")
    ok = asyncio.run(handler.get_template_file(template_id="desk", file_path="assets/logo.png"))
    assert Path(ok.path).name == "logo.png"
    with pytest.raises(HTTPException) as refused:
        asyncio.run(handler.get_template_file(template_id="desk", file_path="template.json"))
    assert refused.value.status_code == 404


def test_save_clone_update_and_edit_layouts_use_folders(templates_root):
    template_info = SimpleNamespace(fonts={"Inter": "https://example.invalid/inter.css"})

    class Session:
        async def get(self, _model, _id):
            return template_info

    request = handler.SaveTemplateRequest(
        template_info_id=uuid.uuid4(),
        name="Imported deck",
        description="from a pptx",
        layouts=[
            handler.SaveTemplateLayoutData(layout_id="slide-1", layout_name="One", layout_code=layout("slide-1")),
            handler.SaveTemplateLayoutData(layout_id="slide-2", layout_name="Two", layout_code=layout("slide-2")),
        ],
    )
    saved = asyncio.run(handler.save_template(request, sql_session=Session()))  # type: ignore[arg-type]
    folder_id = f"custom-{saved.id}"
    info = get_template(folder_id)
    assert info is not None and info.manifest.name == "Imported deck"
    assert info.manifest.fonts == {"Inter": "https://example.invalid/inter.css"}
    assert [item.layout_id for item in info.layouts()] == ["slide-1", "slide-2"]

    cloned = asyncio.run(handler.clone_template(handler.CloneTemplateRequest(id=folder_id, name="Copy")))
    copy = get_template(str(cloned.id))
    assert copy is not None and copy.manifest.name == "Copy" and len(copy.layouts()) == 2

    asyncio.run(
        handler.save_slide_layout(
            handler.SaveSlideLayoutRequest(
                template_id=folder_id, layout_id="slide-1", layout_code=layout("slide-1", "Edited")
            )
        )
    )
    assert get_template(folder_id).layouts()[0].layout_name == "Edited"  # type: ignore[union-attr]

    with pytest.raises(HTTPException):  # built-ins are read-only
        asyncio.run(
            handler.save_slide_layout(
                handler.SaveSlideLayoutRequest(template_id="general", layout_id="x", layout_code=layout("x"))
            )
        )


# ---- database -> folders -----------------------------------------------------------------


def test_database_templates_move_to_folders_once(templates_root, tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    template_id = uuid.uuid4()
    empty_id = uuid.uuid4()

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(
                SQLModel.metadata.create_all, tables=[TemplateModel.__table__, PresentationLayoutCodeModel.__table__]
            )  # type: ignore[attr-defined]
        async with maker() as session:
            session.add(TemplateModel(id=template_id, name="Old import", description="db"))
            session.add(TemplateModel(id=empty_id, name="No layouts"))
            for index in (1, 2):
                session.add(
                    PresentationLayoutCodeModel(
                        presentation=template_id,
                        layout_id=f"l{index}",
                        layout_name=f"L{index}",
                        layout_code=layout(f"l{index}"),
                        fonts={"Inter": "/app_data/fonts/inter.ttf"},
                    )
                )
            await session.commit()

    asyncio.run(seed())
    monkeypatch.setattr(custom_layout_from_db, "async_session_maker", maker)

    assert asyncio.run(custom_layout_from_db.migrate_db_templates_to_folders()) == 1
    info = get_template(str(template_id))
    assert info is not None and info.id == f"custom-{template_id}"
    assert info.manifest.name == "Old import" and info.manifest.fonts == {"Inter": "/app_data/fonts/inter.ttf"}
    assert [item.layout_id for item in info.layouts()] == ["l1", "l2"]
    assert get_template(str(empty_id)) is None

    # A second start finds the folder and leaves it alone (edits on disk survive).
    (info.path / "l1.tsx").write_text(layout("l1", "Edited on disk"))
    assert asyncio.run(custom_layout_from_db.migrate_db_templates_to_folders()) == 0
    assert get_template(str(template_id)).layouts()[0].layout_name == "Edited on disk"  # type: ignore[union-attr]
    asyncio.run(engine.dispose())
