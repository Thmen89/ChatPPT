"""The export hooks for exports the Next.js server runs (the editor's Export button):
``before_export`` on the deck the exporter renders, ``after_export`` on the written file.
Exports started through the API call the hooks in ``utils/export_utils.py``."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from chatppt.auth.web import sign_app_data_urls
from chatppt.hooks import run_hook
from services.database import get_async_session
from utils.asset_directory_utils import get_exports_directory

API_V1_HOOKS_ROUTER = APIRouter(prefix="/api/v1/hooks", tags=["Hooks"])


@API_V1_HOOKS_ROUTER.get("/export-deck/{id}")
async def export_deck(id: uuid.UUID, sql_session: AsyncSession = Depends(get_async_session)) -> JSONResponse:
    """The presentation as ``GET /api/v1/ppt/presentation/{id}`` returns it, after
    ``before_export``; the saved deck is not changed."""
    from api.v1.ppt.endpoints.presentation import get_presentation

    deck = (await get_presentation(id, sql_session)).model_dump(mode="json")
    deck = await run_hook("before_export", deck)
    # Signed /app_data links: the converter fetches slide images without a cookie.
    return JSONResponse(sign_app_data_urls(deck), headers={"Cache-Control": "no-store"})


@API_V1_HOOKS_ROUTER.post("/after-export", status_code=204)
async def after_export(path: str = Body(..., embed=True)) -> None:
    exports = Path(get_exports_directory()).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(exports) or not target.is_file():
        raise HTTPException(status_code=400, detail="path must be an exported file")
    await run_hook("after_export", str(target))
