from datetime import datetime
from typing import Optional

from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage
from models.presentation_layout import SlideLayoutModel
from models.sql.slide import SlideModel
from chatppt.prompts import render_prompt
from chatppt.providers import llm_for_step
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import generate_structured_with_schema_retries
from utils.schema_utils import (
    add_field_in_schema,
    ensure_array_schemas_have_items,
    remove_fields_from_schema,
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


def get_system_prompt(
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    memory_context: Optional[str] = None,
):
    memory_block = (
        "\n# Retrieved Presentation Memory Context\n"
        f"{memory_context}\n"
        "- Use this context only if it is relevant to the user prompt.\n"
        "- Prefer this context over assumptions when resolving ambiguity.\n"
        if memory_context
        else ""
    )

    return render_prompt(
        "edit_slide.system",
        user_instructions=f"# User Instruction:\n{instructions}" if instructions else "",
        tone_instructions=f"# Tone:\n{tone}" if tone else "",
        verbosity_instructions=f"# Verbosity:\n{verbosity}" if verbosity else "",
        memory_context=memory_block,
    )


def get_user_prompt(prompt: str, slide_data: dict, language: str):
    return render_prompt(
        "edit_slide.user",
        current_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        language=_resolve_prompt_language(language),
        prompt=prompt,
        slide_data=slide_data,
    )


def get_messages(
    prompt: str,
    slide_data: dict,
    language: Optional[str],
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    memory_context: Optional[str] = None,
) -> list[Message]:
    return [
        SystemMessage(
            content=get_system_prompt(tone, verbosity, instructions, memory_context),
        ),
        UserMessage(
            content=get_user_prompt(prompt, slide_data, language),
        ),
    ]


async def get_edited_slide_content(
    prompt: str,
    slide: SlideModel,
    language: Optional[str],
    slide_layout: SlideLayoutModel,
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    memory_context: Optional[str] = None,
):
    client, model = llm_for_step("edit")

    response_schema = remove_fields_from_schema(
        slide_layout.json_schema, ["__image_url__", "__icon_url__"]
    )
    response_schema = add_field_in_schema(
        response_schema,
        {
            "__speaker_note__": {
                "type": "string",
                "minLength": 100,
                "maxLength": 500,
                "description": "Speaker note for the slide",
            }
        },
        True,
    )
    response_schema = ensure_array_schemas_have_items(response_schema)

    try:
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=response_schema,
            strict=False,
        )
        messages = get_messages(
            prompt,
            slide.content,
            language,
            tone,
            verbosity,
            instructions,
            memory_context,
        )

        return await generate_structured_with_schema_retries(
            client,
            model,
            messages=messages,
            response_format=response_format,
            json_schema=response_schema,
            strict=False,
            validate_schema=True,
        )

    except Exception as e:
        raise handle_llm_client_exceptions(e)
