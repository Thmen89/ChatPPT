"""The PPTX writer behind the built-in exporter: Next.js renders the deck in Chromium and
posts the slides as positioned shapes; this writes the .pptx into <data>/exports."""

from fastapi import APIRouter
from pydantic import BaseModel

from models.pptx_models import PptxPresentationModel
from services.pptx_writer import write_pptx_to_exports

EXPORT_ROUTER = APIRouter(prefix="/export", tags=["export"])


class ExportedFile(BaseModel):
    path: str


@EXPORT_ROUTER.post("/pptx", response_model=ExportedFile)
async def write_pptx(model: PptxPresentationModel) -> ExportedFile:
    return ExportedFile(path=await write_pptx_to_exports(model))
