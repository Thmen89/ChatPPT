import os
import random
import re
import shutil
import uuid
from datetime import datetime
from typing import Any, List, Optional

import aiohttp
from fastapi import Body, Depends, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from chatppt.settings import get_settings
from chatppt.templates import (
    TemplateInfo,
    TemplateManifest,
    discover_templates,
    get_template,
    write_layout,
    write_manifest,
    write_template,
)
from constants.presentation import DEFAULT_TEMPLATES
from models.sql.template_create_info import TemplateCreateInfoModel
from services.database import async_session_maker, get_async_session
from services.export_task_service import EXPORT_TASK_SERVICE
from templates.example import build_template_example
from templates.get_layout_by_name import get_layout_by_name
from templates.presentation_layout import PresentationLayoutModel  # noqa: F401  (re-exported to templates.router)
from templates.preview import (
    FontsUploadAndSlidesPreviewResponse,  # noqa: F401  (re-exported to templates.router)
    upload_fonts_and_slides_preview_handler,
)
from templates.prompts import (
    SLIDE_LAYOUT_CREATION_SYSTEM_PROMPT,
    SLIDE_LAYOUT_EDIT_SECTION_SYSTEM_PROMPT,
    SLIDE_LAYOUT_EDIT_SYSTEM_PROMPT,
)
from templates.providers import edit_slide_layout_code, generate_slide_layout_code
from templates.slide_layout_jobs import (
    SlideLayoutJobStartResponse,
    SlideLayoutJobStatusResponse,
    start_slide_layout_job,
    get_slide_layout_job,
)
from utils.asset_directory_utils import (
    resolve_app_path_to_filesystem,
    resolve_image_path_to_filesystem,
)


class TemplateDetail(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    total_layouts: Optional[int] = None
    fingerprint: Optional[str] = None


class TemplateLayoutData(BaseModel):
    template: str
    layout_id: str
    layout_name: str
    layout_code: str
    fonts: Optional[Any] = None


class TemplateData(BaseModel):
    id: str
    init_id: Optional[uuid.UUID] = None
    name: str
    description: Optional[str] = None
    created_at: datetime
    ordered: bool = False
    icon_weight: str = "regular"


class GetTemplateLayoutsResponse(BaseModel):
    layouts: list[TemplateLayoutData]
    template: Optional[TemplateData] = None
    fonts: Optional[Any] = None
    modules: dict[str, str] = {}
    """Helper files layouts import from (``./ChartPrimitives``), by file name."""
    fingerprint: Optional[str] = None


class TemplateExample(BaseModel):
    template: str
    slides: List[dict]


class CreateTemplateInitRequest(BaseModel):
    pptx_url: str
    slide_image_urls: List[str]
    fonts: dict = {}


class CreateSlideLayoutRequest(BaseModel):
    id: uuid.UUID
    index: int


class CreateSlideLayoutResponse(BaseModel):
    react_component: str


class EditSlideLayoutRequest(BaseModel):
    react_component: str
    prompt: str


class EditSlideLayoutResponse(CreateSlideLayoutResponse):
    pass


class EditSlideLayoutSectionRequest(BaseModel):
    react_component: str
    section: str
    prompt: str


class EditSlideLayoutSectionResponse(CreateSlideLayoutResponse):
    pass


class SaveTemplateLayoutData(BaseModel):
    layout_id: str
    layout_name: str
    layout_code: str


class SaveTemplateRequest(BaseModel):
    template_info_id: uuid.UUID
    name: str
    description: Optional[str] = None
    layouts: List[SaveTemplateLayoutData]


class SaveTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    created_at: datetime


class CloneTemplateRequest(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class UpdateTemplateRequest(BaseModel):
    id: str
    layouts: List[SaveTemplateLayoutData]


class SaveSlideLayoutRequest(BaseModel):
    template_id: str
    layout_id: str
    layout_code: str


class CloneSlideLayoutRequest(BaseModel):
    template_id: str
    layout_id: str
    layout_name: Optional[str] = None


def _strip_code_fences(value: str) -> str:
    return (
        value.replace("```tsx", "")
        .replace("```typescript", "")
        .replace("```ts", "")
        .replace("```", "")
        .strip()
    )


_ASSET_FIELD_REPLACEMENTS = {
    "image_url": "__image_url__",
    "icon_url": "__icon_url__",
    "image_prompt": "__image_prompt__",
    "icon_query": "__icon_query__",
}

_ASSET_FIELD_DEFAULTS = {
    "__image_url__": "/static/images/replaceable_template_image.png",
    "__icon_url__": "/static/icons/placeholder.svg",
    "__image_prompt__": "replaceable image",
    "__icon_query__": "placeholder icon",
}


def _normalize_asset_fields(code: str) -> str:
    normalized = code
    for field_name, normalized_name in _ASSET_FIELD_REPLACEMENTS.items():
        normalized = re.sub(
            rf"(?<!_)\b{re.escape(field_name)}\b(?!_)",
            normalized_name,
            normalized,
        )

    # Models occasionally emit a bare object shorthand without a comma/value:
    #   icon: {
    #     __icon_url__
    #     __icon_query__: "play"
    #   }
    # These asset fields are not in scope as variables, so make them valid defaults.
    def replace_bare_asset_field(match: re.Match[str]) -> str:
        indentation, field_name = match.groups()
        default_value = _ASSET_FIELD_DEFAULTS[field_name]
        return f'{indentation}{field_name}: "{default_value}",'

    return re.sub(
        r"(?m)^(\s*)(__(?:image_url|icon_url|image_prompt|icon_query)__)\s*,?\s*$",
        replace_bare_asset_field,
        normalized,
    )


def _normalize_layout_code_for_create(code: str) -> str:
    normalized = _normalize_asset_fields(_strip_code_fences(code))

    first_import_match = re.search(r"(?m)^\s*import\b", normalized)
    if first_import_match:
        normalized = normalized[first_import_match.start() :]

    first_export_match = re.search(r"(?m)^\s*export\b", normalized)
    if first_export_match:
        normalized = normalized[: first_export_match.start()]

    normalized = re.sub(
        r"(?ms)^\s*(?:import|export)\b.*?;(?:\r?\n|$)",
        "",
        normalized,
    )
    normalized = re.sub(
        r"(?m)^\s*(?:import|export)\b.*(?:\r?\n|$)",
        "",
        normalized,
    )
    normalized = normalized.strip()
    normalized = re.sub(
        r'(layoutId\s*=\s*["\'])([^"\']+)(["\'])',
        lambda match: (
            match.group(0)
            if re.search(r"-\d{4}$", match.group(2))
            else f"{match.group(1)}{match.group(2)}-{random.randint(1000, 9999)}{match.group(3)}"
        ),
        normalized,
    )
    return normalized


def _update_layout_id_in_code(code: str) -> tuple[str, str]:
    match = re.search(r'(layoutId\s*=\s*["\'])([^"\']+)(["\'])', code)
    if not match:
        raise HTTPException(status_code=400, detail="layoutId not found in layout code")

    current_id = match.group(2)
    suffix = f"{random.randint(1000, 9999)}"
    new_id = re.sub(r"-\d{4}$", f"-{suffix}", current_id)
    if new_id == current_id:
        new_id = f"{current_id}-{suffix}"

    new_code = re.sub(
        r'(layoutId\s*=\s*["\'])([^"\']+)(["\'])',
        f"\\1{new_id}\\3",
        code,
        count=1,
    )
    return new_code, new_id


async def _download_image_bytes(image_url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to download slide image: {image_url}",
                )
            return await response.read()


async def _read_image_bytes_and_media_type(image_url: str) -> tuple[bytes, str]:
    actual_image_path = resolve_image_path_to_filesystem(image_url)
    if actual_image_path and os.path.isfile(actual_image_path):
        with open(actual_image_path, "rb") as image_file:
            image_bytes = image_file.read()
        file_extension = os.path.splitext(actual_image_path)[1].lower()
    else:
        image_bytes = await _download_image_bytes(image_url)
        file_extension = os.path.splitext(image_url)[1].lower()

    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return image_bytes, media_type_map.get(file_extension, "image/png")


def _template_or_404(template_id: str) -> TemplateInfo:
    if not template_id or not template_id.strip():
        raise HTTPException(status_code=400, detail="Template ID cannot be empty")
    info = get_template(template_id.strip())
    if info is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return info


def _data_template_or_400(template_id: str) -> TemplateInfo:
    info = get_template(str(template_id))
    if info is None or info.source != "data":
        raise HTTPException(status_code=400, detail="Template not found. Please use a valid template.")
    return info


def _template_data(info: TemplateInfo) -> "TemplateData":
    manifest_path = info.path / "template.json"
    created = manifest_path.stat().st_mtime if manifest_path.exists() else info.path.stat().st_mtime
    return TemplateData(
        id=info.id,
        name=info.manifest.name,
        description=info.manifest.description or None,
        created_at=datetime.fromtimestamp(created),
        ordered=info.manifest.ordered,
        icon_weight=info.manifest.icon_weight,
    )


def _files_url(template_id: str) -> str:
    return f"/api/v1/ppt/template/{template_id}/files"


def _with_folder_urls(template_id: str, code: str) -> str:
    """``"./assets/x.png"`` / ``"./fonts/x.woff2"`` in a layout point at the folder's files."""
    return re.sub(r"""(["'`])\./(assets|fonts)/""", lambda m: f"{m.group(1)}{_files_url(template_id)}/{m.group(2)}/", code)


def _font_urls(info: TemplateInfo) -> dict[str, str]:
    return {
        family: url if re.match(r"^(https?:)?/", url) else f"{_files_url(info.id)}/{url.lstrip('./')}"
        for family, url in info.manifest.fonts.items()
    }


async def get_all_templates(
    include_defaults: bool = Query(
        default=True, description="Whether to include default templates"
    ),
):
    """Built-in ids, then every template folder under ``<data>/templates`` (dropped in,
    imported from a PPTX, or overriding a built-in), with a fingerprint that changes
    whenever a file in the folder does."""
    templates: list[TemplateDetail] = []
    if include_defaults:
        templates.extend(
            TemplateDetail(id=template, name=template) for template in DEFAULT_TEMPLATES
        )
    for info in discover_templates().values():
        if info.source != "data":
            continue
        templates.append(
            TemplateDetail(
                id=info.id,
                name=info.manifest.name,
                description=info.manifest.description or None,
                total_layouts=len(info.layout_files),
                fingerprint=info.fingerprint(),
            )
        )
    return templates


async def get_layouts(
    template_id: str = Path(..., description="The id of the template"),
):
    info = _template_or_404(template_id)
    layouts = [
        TemplateLayoutData(
            template=info.id,
            layout_id=layout.layout_id,
            layout_name=layout.layout_name,
            layout_code=_with_folder_urls(info.id, layout.code),
            fonts=_font_urls(info) or None,
        )
        for layout in info.layouts()
    ]
    if not layouts:
        raise HTTPException(
            status_code=404,
            detail=f"No layouts found for template ID: {template_id}",
        )
    return GetTemplateLayoutsResponse(
        layouts=layouts,
        template=_template_data(info),
        fonts=_font_urls(info) or None,
        modules={name: _with_folder_urls(info.id, code) for name, code in info.modules().items()},
        fingerprint=info.fingerprint(),
    )


async def get_template_file(
    template_id: str = Path(..., description="The id of the template"),
    file_path: str = Path(..., description="A file under fonts/ or assets/"),
):
    """Fonts and images a template folder ships, for its layouts to reference."""
    info = _template_or_404(template_id)
    target = info.file(file_path)
    if target is None:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


async def get_template_by_id(
    id: str = Path(
        ...,
        description=f"The id of the template, must be one of {', '.join(DEFAULT_TEMPLATES)} or your custom template",
    ),
):
    if get_template(id) is None:
        raise HTTPException(
            status_code=400,
            detail="Template not found. Please use a valid template.",
        )
    return await get_layout_by_name(id)


async def get_template_example(
    id: str = Path(
        ...,
        description=f"The id of the template, must be one of {', '.join(DEFAULT_TEMPLATES)} or your custom template",
    ),
):
    template = await get_template_by_id(id=id)
    return TemplateExample(**build_template_example(id, template))


async def upload_fonts_and_slides_preview(
    pptx_file: UploadFile = File(..., description="PPTX file to preview"),
    font_files: Optional[List[UploadFile]] = File(
        default=None, description="Font files to upload"
    ),
    original_font_names: Optional[List[str]] = Form(default=None),
):
    return await upload_fonts_and_slides_preview_handler(
        pptx_file=pptx_file,
        font_files=font_files,
        original_font_names=original_font_names,
        max_slides=25,
    )


async def init_create_template(
    request: CreateTemplateInitRequest,
    sql_session: AsyncSession = Depends(get_async_session),
):
    if not request.slide_image_urls:
        raise HTTPException(
            status_code=400, detail="At least one slide image is required"
        )

    pptx_path = resolve_app_path_to_filesystem(request.pptx_url)
    if not pptx_path or not os.path.isfile(pptx_path):
        raise HTTPException(status_code=400, detail="PPTX file not found")

    pptx_document = await EXPORT_TASK_SERVICE.convert_pptx_to_html(
        pptx_path, get_fonts=False
    )
    if not pptx_document.slides:
        raise HTTPException(
            status_code=500,
            detail="PPTX-to-HTML export returned no slides",
        )

    if len(pptx_document.slides) < len(request.slide_image_urls):
        raise HTTPException(
            status_code=400,
            detail=(
                "PPTX-to-HTML export returned fewer slides than the preview images. "
                f"Expected at least {len(request.slide_image_urls)}, got {len(pptx_document.slides)}."
            ),
        )

    slide_htmls = pptx_document.slides[: len(request.slide_image_urls)]
    template_create_info = TemplateCreateInfoModel(
        fonts=request.fonts or {},
        pptx_url=request.pptx_url,
        slide_image_urls=request.slide_image_urls,
        slide_htmls=slide_htmls,
    )
    sql_session.add(template_create_info)
    await sql_session.commit()
    await sql_session.refresh(template_create_info)
    return template_create_info.id


async def _create_slide_layout_impl(
    sql_session: AsyncSession,
    request: CreateSlideLayoutRequest,
) -> CreateSlideLayoutResponse:
    template_info = await sql_session.get(TemplateCreateInfoModel, request.id)
    if not template_info:
        raise HTTPException(status_code=400, detail="Template not found")

    total_slides = len(template_info.slide_htmls)
    if request.index < 0 or request.index >= total_slides:
        raise HTTPException(status_code=400, detail="Invalid slide index")

    slide_html = template_info.slide_htmls[request.index]
    slide_image_url = template_info.slide_image_urls[request.index]
    image_bytes, media_type = await _read_image_bytes_and_media_type(slide_image_url)

    fonts_text = ""
    if template_info.fonts:
        font_names = [font.replace(" ", "_") for font in template_info.fonts.keys()]
        fonts_text = "#PROVIDED FONTS\n- " + "\n- ".join(font_names)

    user_text = f"{fonts_text}\n\n#SLIDE HTML REFERENCE\n{slide_html}"
    react_component = await generate_slide_layout_code(
        system_prompt=SLIDE_LAYOUT_CREATION_SYSTEM_PROMPT,
        user_text=user_text,
        image_bytes=image_bytes,
        media_type=media_type,
    )
    normalized_react_component = _normalize_layout_code_for_create(react_component)

    return CreateSlideLayoutResponse(react_component=normalized_react_component)


async def create_slide_layout(
    request: CreateSlideLayoutRequest = Body(...),
    sql_session: AsyncSession = Depends(get_async_session),
):
    return await _create_slide_layout_impl(sql_session, request)


async def create_slide_layout_job_start(
    request: CreateSlideLayoutRequest = Body(...),
):
    req = request.model_copy()

    async def work() -> str:
        async with async_session_maker() as session:
            result = await _create_slide_layout_impl(session, req)
            return result.react_component

    job_id = await start_slide_layout_job(work)
    return SlideLayoutJobStartResponse(job_id=job_id)


async def create_slide_layout_job_status(
    job_id: uuid.UUID,
):
    rec = await get_slide_layout_job(str(job_id))
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return SlideLayoutJobStatusResponse(
        status=rec.status,
        react_component=rec.react_component,
        error=rec.error,
    )


async def edit_slide_layout(
    request: EditSlideLayoutRequest,
):
    user_text = f"#Prompt\n{request.prompt}\n\n#TSX code\n{request.react_component}"
    react_component = await edit_slide_layout_code(
        system_prompt=SLIDE_LAYOUT_EDIT_SYSTEM_PROMPT,
        user_text=user_text,
    )
    return EditSlideLayoutResponse(
        react_component=_normalize_asset_fields(_strip_code_fences(react_component))
    )


async def edit_slide_layout_section(
    request: EditSlideLayoutSectionRequest,
):
    user_text = (
        f"#Prompt\n{request.prompt}\n\n"
        f"#Section to make changes around\n{request.section}\n\n"
        f"#TSX code\n{request.react_component}"
    )
    react_component = await edit_slide_layout_code(
        system_prompt=SLIDE_LAYOUT_EDIT_SECTION_SYSTEM_PROMPT,
        user_text=user_text,
    )
    return EditSlideLayoutSectionResponse(
        react_component=_normalize_asset_fields(_strip_code_fences(react_component))
    )


def _templates_root():
    return get_settings().templates_dir


async def save_template(
    request: SaveTemplateRequest,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """An imported PPTX becomes a template folder, ``<data>/templates/custom-<uuid>/``."""
    if not request.layouts:
        raise HTTPException(status_code=400, detail="Layouts are required")

    template_info = await sql_session.get(TemplateCreateInfoModel, request.template_info_id)
    if not template_info:
        raise HTTPException(status_code=400, detail="Template info not found")

    template_uuid = uuid.uuid4()
    fonts = template_info.fonts if isinstance(template_info.fonts, dict) else {}
    manifest = TemplateManifest(
        id=f"custom-{template_uuid}",
        name=request.name,
        description=request.description or "",
        fonts={str(k): str(v) for k, v in fonts.items() if v},
    )
    try:
        info = write_template(
            _templates_root(),
            manifest,
            [(layout.layout_id, layout.layout_code) for layout in request.layouts],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SaveTemplateResponse(
        id=template_uuid,
        name=info.manifest.name,
        description=request.description,
        created_at=_template_data(info).created_at,
    )


async def clone_template(request: CloneTemplateRequest = Body(...)):
    source = _template_or_404(request.id)
    template_uuid = uuid.uuid4()
    manifest = source.manifest.model_copy(
        update={
            "id": f"custom-{template_uuid}",
            "name": request.name,
            "description": source.manifest.description if request.description is None else request.description,
            "default": False,
            "layouts": None,
        }
    )
    target = _templates_root() / manifest.id
    shutil.copytree(source.path, target)
    write_manifest(target, manifest)
    (target / "settings.json").unlink(missing_ok=True)
    info = _data_template_or_400(manifest.id)

    return SaveTemplateResponse(
        id=template_uuid,
        name=info.manifest.name,
        description=info.manifest.description or None,
        created_at=_template_data(info).created_at,
    )


async def update_template(request: UpdateTemplateRequest):
    if not request.layouts:
        raise HTTPException(status_code=400, detail="Layouts are required")

    info = _data_template_or_400(request.id)
    write_template(
        info.path.parent,
        info.manifest,
        [(layout.layout_id, layout.layout_code) for layout in request.layouts],
    )
    data = _template_data(info)
    return SaveTemplateResponse(
        id=_uuid_or_none(info.id) or uuid.uuid5(uuid.NAMESPACE_URL, info.id),
        name=data.name,
        description=data.description,
        created_at=data.created_at,
    )


def _uuid_or_none(template_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(template_id.removeprefix("custom-"))
    except ValueError:
        return None


async def save_slide_layout(request: SaveSlideLayoutRequest):
    info = _data_template_or_400(request.template_id)
    if not any(layout.layout_id == request.layout_id for layout in info.layouts()):
        raise HTTPException(status_code=400, detail="Layout not found")
    write_layout(info, request.layout_id, request.layout_code)


async def clone_slide_layout(request: CloneSlideLayoutRequest = Body(...)):
    info = _data_template_or_400(request.template_id)
    layout = next((item for item in info.layouts() if item.layout_id == request.layout_id), None)
    if layout is None:
        raise HTTPException(status_code=400, detail="Layout not found")

    new_layout_code, new_layout_id = _update_layout_id_in_code(layout.code)
    if request.layout_name:
        new_layout_code = re.sub(
            r'(layoutName\s*=\s*["\'])([^"\']+)(["\'])',
            lambda m: f"{m.group(1)}{request.layout_name}{m.group(3)}",
            new_layout_code,
            count=1,
        )
    write_layout(info, new_layout_id, new_layout_code)

    return SaveTemplateLayoutData(
        layout_id=new_layout_id,
        layout_name=request.layout_name or layout.layout_name,
        layout_code=new_layout_code,
    )
