import os
import logging
from typing import Literal
from urllib.parse import urlencode
import uuid

import httpx
from pathvalidate import sanitize_filename

from chatppt.hooks import run_hook

from models.presentation_and_path import PresentationAndPath
from utils.filename_utils import safe_export_basename
from utils.internal_urls import nextjs_base_url
from models.pptx_models import PptxPresentationModel
from services.export_task_service import EXPORT_TASK_SERVICE
from services.pptx_writer import export_basename, write_pptx_to_exports
from utils.asset_directory_utils import get_exports_directory
from utils.runtime_limits import log_memory


LOGGER = logging.getLogger(__name__)
RENDER_TIMEOUT_S = 300.0


def export_engine() -> str:
    """``chromium`` (Next.js renders, this process writes) or ``bundle`` (the earlier
    presentation-export bundle), from ``CHATPPT_EXPORT_ENGINE``."""
    return "bundle" if (os.getenv("CHATPPT_EXPORT_ENGINE") or "").strip().lower() == "bundle" else "chromium"


async def _export_with_chromium(
    presentation_id: uuid.UUID,
    basename: str,
    export_as: Literal["pptx", "pdf"],
    cookie_header: str | None,
) -> str:
    """Ask Next.js to render the deck (POST /api/export-presentation/render) and save the
    result into <data>/exports."""
    headers = {"Cookie": cookie_header} if cookie_header else {}
    async with httpx.AsyncClient(timeout=RENDER_TIMEOUT_S) as client:
        response = await client.post(
            f"{nextjs_base_url()}/api/export-presentation/render",
            json={"id": str(presentation_id), "format": export_as},
            headers=headers,
        )
    if response.status_code != 200:
        raise RuntimeError(f"Export render failed ({response.status_code}): {response.text[:300]}")
    if export_as == "pptx":
        model = PptxPresentationModel.model_validate_json(response.content)
        model.name = basename
        return await write_pptx_to_exports(model)
    path = os.path.join(get_exports_directory(), f"{export_basename(basename)}_{uuid.uuid4()}.pdf")
    with open(path, "wb") as f:
        f.write(response.content)
    os.chmod(path, 0o644)
    return path


def _get_next_public_url() -> str:
    if os.getenv("CHATPPT_NEXTJS_URL"):
        return nextjs_base_url()
    return (os.getenv("NEXT_PUBLIC_URL") or "").strip() or "http://127.0.0.1"


def _get_next_public_fastapi_url() -> str | None:
    value = (os.getenv("NEXT_PUBLIC_FAST_API") or "").strip()
    return value or None


def _build_presentation_export_url(presentation_id: uuid.UUID) -> tuple[str, str | None]:
    params = {"id": str(presentation_id)}
    fastapi_url = _get_next_public_fastapi_url()
    if fastapi_url:
        params["fastapiUrl"] = fastapi_url
    return (
        f"{_get_next_public_url().rstrip('/')}/pdf-maker?{urlencode(params)}",
        fastapi_url,
    )


async def export_presentation(
    presentation_id: uuid.UUID,
    title: str,
    export_as: Literal["pptx", "pdf"],
    cookie_header: str | None = None,
) -> PresentationAndPath:
    log_memory(
        LOGGER,
        "presentation.export.start",
        presentation_id=str(presentation_id),
        export_as=export_as,
    )
    name = (title or "").strip() or str(uuid.uuid4())
    basename = safe_export_basename(sanitize_filename(name))
    if export_engine() == "bundle":
        export_url, fastapi_url = _build_presentation_export_url(presentation_id)
        export_result = await EXPORT_TASK_SERVICE.export_from_url(
            url=export_url,
            title=basename,
            export_as=export_as,
            fastapi_url=fastapi_url,
            cookie_header=cookie_header,
        )
        path = export_result.path
    else:
        path = await _export_with_chromium(presentation_id, basename, export_as, cookie_header)
    log_memory(
        LOGGER,
        "presentation.export.finish",
        presentation_id=str(presentation_id),
        export_as=export_as,
    )
    await run_hook("after_export", path)
    return PresentationAndPath(
        presentation_id=presentation_id,
        path=path,
    )
