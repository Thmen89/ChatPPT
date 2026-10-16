"""Imported (``custom-<uuid>``) templates are folders under ``<data>/templates/`` now.

``load_custom_presentation_layout`` resolves one like any other template folder (through
the Next.js schema route), and ``migrate_db_templates_to_folders`` moves templates that
older versions stored in the database into folders once at startup. Their ids do not
change, so existing presentations keep pointing at them.
"""

import logging

import aiohttp
from fastapi import HTTPException
from sqlmodel import select

from chatppt.templates import TemplateManifest, get_template, write_template
from models.sql.presentation_layout_code import PresentationLayoutCodeModel
from models.sql.template import TemplateModel
from services.database import async_session_maker
from templates.presentation_layout import PresentationLayoutModel
from utils.internal_http import internal_request_headers

LOGGER = logging.getLogger(__name__)

_TEMPLATE_SCHEMA_URL = "http://localhost/api/template"


async def load_custom_presentation_layout(layout_name: str) -> PresentationLayoutModel:
    """Layouts and schemas of a template folder, compiled by Next.js (no Puppeteer)."""
    if get_template(layout_name) is None:
        raise HTTPException(status_code=404, detail=f"Template '{layout_name}' not found")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _TEMPLATE_SCHEMA_URL,
                params={"group": layout_name},
                headers=internal_request_headers(),
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    LOGGER.error(
                        "[template_layout] schema route HTTP %s template=%r body=%s",
                        response.status,
                        layout_name,
                        (error or "")[:600],
                    )
                    raise HTTPException(
                        status_code=404 if response.status == 404 else 500,
                        detail=f"Template '{layout_name}' could not be compiled: {error or response.status}",
                    )
                payload = await response.json()
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reach template compile service: {exc}",
        ) from exc

    if not isinstance(payload, dict) or not payload.get("slides"):
        raise HTTPException(status_code=404, detail=f"Template '{layout_name}' not found")
    return PresentationLayoutModel(**payload)


async def migrate_db_templates_to_folders() -> int:
    """Write every database template that has no folder yet to ``custom-<uuid>/``."""
    from chatppt.settings import get_settings

    root = get_settings().templates_dir
    async with async_session_maker() as session:
        templates = (await session.execute(select(TemplateModel))).scalars().all()
        moved = 0
        for template in templates:
            template_id = f"custom-{template.id}"
            if (root / template_id).exists():
                continue
            layouts = (
                (
                    await session.execute(
                        select(PresentationLayoutCodeModel).where(
                            PresentationLayoutCodeModel.presentation == template.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not layouts:
                continue
            fonts = layouts[0].fonts if isinstance(layouts[0].fonts, dict) else {}
            manifest = TemplateManifest(
                id=template_id,
                name=template.name or template_id,
                description=template.description or "",
                fonts={str(k): str(v) for k, v in fonts.items() if v},
            )
            try:
                write_template(root, manifest, [(layout.layout_id, layout.layout_code) for layout in layouts])
            except (OSError, ValueError) as exc:
                LOGGER.warning("Could not move template %s to a folder: %s", template_id, exc)
                continue
            moved += 1
    if moved:
        LOGGER.info("Moved %d imported template(s) from the database to %s", moved, root)
    return moved
