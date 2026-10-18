from datetime import datetime
from typing import List, Optional

from llmai.shared import (
    JSONSchemaResponse,
    Message,
    ResponseStreamCompletionChunk,
    SystemMessage,
    UserMessage,
    WebSearchTool,
)

from pydantic import BaseModel, Field

from chatppt.prompts import render_prompt
from models.presentation_layout import PresentationLayoutModel
from models.presentation_outline_model import PresentationOutlineModel
from utils.get_dynamic_models import get_presentation_outline_model_with_n_slides
from utils.llm_client_error_handler import handle_llm_client_exceptions
from chatppt import hooks
from chatppt.providers import llm_for_step
from utils.llm_utils import (
    get_generate_kwargs,
    serialize_structured_content,
    stream_generate_events,
)
from utils.schema_utils import prepare_schema_for_validation


def get_system_prompt(
    verbosity: Optional[str] = None,
    include_title_slide: bool = True,
    include_table_of_contents: bool = False,
    layout: Optional[PresentationLayoutModel] = None,
):
    verbosity_instructions = (
        "Slide content should be around 20 words but detailed enough to generate a good slide."
        if verbosity == "concise"
        else (
            "Slide content should be around 60 words but detailed enough to generate a good slide."
            if verbosity == "text-heavy"
            else "Slide content should be around 40 words but detailed enough to generate a good slide."
        )
    )

    title_slide_instructions = (
        "Include presenter name in first slide."
        if include_title_slide
        else "Do not include presenter name in any slides."
    )

    toc_instructions = (
        "Include a table of contents slide in the outline sequence.\n"
        if include_table_of_contents
        else ""
    )

    layout_instructions = (
        render_prompt("outline.layouts", layouts=layout.to_string()) if layout else ""
    )

    return render_prompt(
        "outline.system",
        verbosity_instructions=verbosity_instructions,
        title_slide_instructions=title_slide_instructions,
        toc_instructions=toc_instructions,
        layout_instructions=layout_instructions,
    )


def _resolve_prompt_language(language: Optional[str]) -> str:
    if language is None:
        return "auto-detect"
    s = str(language).strip()
    if not s:
        return "auto-detect"
    if s.lower() in {"auto", "auto-detect"}:
        return "auto-detect"
    return s


def _resolve_prompt_n_slides(n_slides: Optional[int]) -> str:
    if n_slides is None:
        return "auto-detect"
    return str(n_slides)


def get_user_prompt(
    content: str,
    n_slides: Optional[int],
    language: Optional[str],
    additional_context: Optional[str] = None,
    tone: Optional[str] = None,
    instructions: Optional[str] = None,
    include_title_slide: bool = True,
    include_table_of_contents: bool = False,
):
    return render_prompt(
        "outline.user",
        content=content or "",
        n_slides=_resolve_prompt_n_slides(n_slides),
        language=_resolve_prompt_language(language),
        tone=tone or "",
        date=datetime.now().strftime("%Y-%m-%d"),
        include_title_slide=include_title_slide,
        toc_line=(
            f"Include Table Of Contents: {str(include_table_of_contents).lower()}\n"
            if include_table_of_contents
            else ""
        ),
        instructions=instructions or "",
        context=additional_context or "None",
    )


def get_messages(
    content: str,
    n_slides: Optional[int],
    language: Optional[str],
    additional_context: Optional[str] = None,
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    include_title_slide: bool = True,
    include_table_of_contents: bool = False,
    layout: Optional[PresentationLayoutModel] = None,
) -> list[Message]:
    return [
        SystemMessage(
            content=get_system_prompt(
                verbosity,
                include_title_slide,
                include_table_of_contents,
                layout,
            ),
        ),
        UserMessage(
            content=get_user_prompt(
                content,
                n_slides,
                language,
                additional_context,
                tone,
                instructions,
                include_title_slide,
                include_table_of_contents,
            ),
        ),
    ]


def _outline_with_layouts_model(n_slides: Optional[int], n_layouts: int) -> type[BaseModel]:
    """Outline schema whose slides also carry the index of the layout to use."""

    class SlideOutlineWithLayout(BaseModel):
        content: str = Field(
            description="Markdown content for each slide",
            min_length=100 if n_slides is not None else None,
            max_length=1200 if n_slides is not None else None,
        )
        layout: int = Field(
            description="Index of the layout for this slide", ge=0, le=n_layouts - 1
        )

    class PresentationOutlineWithLayouts(BaseModel):
        slides: List[SlideOutlineWithLayout] = Field(
            description="List of slide outlines",
            min_length=n_slides,
            max_length=n_slides,
        )

    return PresentationOutlineWithLayouts


@hooks.before_outline
async def generate_ppt_outline(
    content: str,
    n_slides: Optional[int],
    language: Optional[str] = None,
    additional_context: Optional[str] = None,
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    include_title_slide: bool = True,
    web_search: bool = False,
    include_table_of_contents: bool = False,
    layout: Optional[PresentationLayoutModel] = None,
):
    """Stream the outline JSON. With ``layout`` (an unordered template), each slide also
    gets a ``layout`` index, so the separate structure call can be skipped."""
    client, model = llm_for_step("outline")
    if layout is not None and layout.slides:
        response_model = _outline_with_layouts_model(n_slides, len(layout.slides))
    else:
        layout = None
        response_model = (
            get_presentation_outline_model_with_n_slides(n_slides)
            if n_slides is not None
            else PresentationOutlineModel
        )

    use_search_tool = web_search

    try:
        outline_schema = prepare_schema_for_validation(
            response_model.model_json_schema(),
            strict=True,
        )
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=outline_schema,
            strict=True,
        )
        emitted_content = False
        async for event in stream_generate_events(
            client,
            **get_generate_kwargs(
                model=model,
                messages=get_messages(
                    content,
                    n_slides,
                    language,
                    additional_context,
                    tone,
                    verbosity,
                    instructions,
                    include_title_slide,
                    include_table_of_contents,
                    layout,
                ),
                response_format=response_format,
                tools=([WebSearchTool()] if use_search_tool else None),
                stream=True,
            ),
        ):
            if getattr(event, "type", None) == "content":
                chunk = getattr(event, "chunk", None)
                if chunk:
                    emitted_content = True
                    yield chunk
            elif (
                isinstance(event, ResponseStreamCompletionChunk) and not emitted_content
            ):
                final_content = serialize_structured_content(event.content)
                if final_content:
                    yield final_content
    except Exception as e:
        yield handle_llm_client_exceptions(e)
