import json
from datetime import datetime
from typing import Optional

from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage

from models.presentation_layout import SlideLayoutModel
from models.presentation_outline_model import SlideOutlineModel
from utils.llm_client_error_handler import handle_llm_client_exceptions
from chatppt.prompts import render_prompt
from chatppt.providers import llm_for_step
from utils.llm_utils import generate_structured_with_schema_retries
from utils.schema_utils import (
    add_field_in_schema,
    ensure_array_schemas_have_items,
    remove_fields_from_schema,
)

# The layout schema goes to the model once, as ``response_format`` (llmai turns it into
# json_schema, a forced tool or a response schema depending on the provider). A model
# behind an endpoint that silently drops ``response_format`` answers without the schema's
# keys; when that happens its (client, model) lands here and later calls also carry the
# schema in the system prompt, as upstream always did.
_SCHEMA_IN_PROMPT: set[str] = set()


def _structured_output_key(client: object, model: str) -> str:
    base_url = getattr(getattr(client, "_client", None), "base_url", "")
    return f"{type(client).__name__}:{base_url}:{model}"


def _ignored_schema(content: dict, response_schema: dict) -> bool:
    """True when the reply shares less than half of the schema's top-level keys."""
    expected = response_schema.get("required") or list(
        (response_schema.get("properties") or {}).keys()
    )
    if not expected:
        return False
    present = sum(1 for key in expected if key in content)
    return present * 2 < len(expected)

def _resolve_prompt_language(language: Optional[str]) -> str:
    if language is None:
        return "auto-detect"
    s = str(language).strip()
    if not s:
        return "auto-detect"
    if s.lower() in {"auto", "auto-detect"}:
        return "auto-detect"
    return s


def _get_schema_markdown(response_schema: Optional[dict]) -> str:
    if not response_schema:
        return "- Follow the provided response schema strictly."
    try:
        schema_text = json.dumps(response_schema, ensure_ascii=False)
    except Exception:
        return "- Follow the provided response schema strictly."
    return f"- Follow this response schema exactly: {schema_text}"


def get_system_prompt(
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    response_schema: Optional[dict] = None,
):
    markdown_emphasis_rules = (
        "- Strictly use markdown to emphasize important points, by bolding or "
        "italicizing the part of text."
    )

    user_instructions = f"# User Instructions:\n{instructions}" if instructions else ""
    tone_instructions = (
        f"# Tone Instructions:\nMake slide as {tone} as possible." if tone else ""
    )

    verbosity_instructions = ""
    if verbosity:
        verbosity_instructions = "# Verbosity Instructions:\n"
        if verbosity == "concise":
            verbosity_instructions += "Make slide as concise as possible."
        elif verbosity == "standard":
            verbosity_instructions += "Make slide as standard as possible."
        elif verbosity == "text-heavy":
            verbosity_instructions += "Make slide as text-heavy as possible."

    output_fields_instructions = "# Output Fields:\n" + _get_schema_markdown(
        response_schema
    )

    return render_prompt(
        "slide_content.system",
        markdown_emphasis_rules=markdown_emphasis_rules,
        user_instructions=user_instructions,
        tone_instructions=tone_instructions,
        verbosity_instructions=verbosity_instructions,
        output_fields_instructions=output_fields_instructions,
    )


def get_user_prompt(outline: str, language: Optional[str]):
    return render_prompt(
        "slide_content.user",
        current_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        language=_resolve_prompt_language(language),
        content=outline,
    )


def get_messages(
    outline: str,
    language: Optional[str],
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    response_schema: Optional[dict] = None,
) -> list[Message]:

    return [
        SystemMessage(
            content=get_system_prompt(
                tone,
                verbosity,
                instructions,
                response_schema,
            ),
        ),
        UserMessage(
            content=get_user_prompt(outline, language),
        ),
    ]


async def get_slide_content_from_type_and_outline(
    slide_layout: SlideLayoutModel,
    outline: SlideOutlineModel,
    language: Optional[str],
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
):
    client, model = llm_for_step("content")

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

    key = _structured_output_key(client, model)
    schema_in_prompt = key in _SCHEMA_IN_PROMPT

    def schema_feedback(invalid_content: dict) -> Optional[str]:
        if schema_in_prompt or not _ignored_schema(invalid_content, response_schema):
            return None
        _SCHEMA_IN_PROMPT.add(key)
        return _get_schema_markdown(response_schema)

    try:
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=response_schema,
            strict=False,
        )
        messages = get_messages(
            outline.content,
            language,
            tone,
            verbosity,
            instructions,
            response_schema if schema_in_prompt else None,
        )

        return await generate_structured_with_schema_retries(
            client,
            model,
            messages=messages,
            response_format=response_format,
            json_schema=response_schema,
            strict=False,
            validate_schema=True,
            feedback_extra=schema_feedback,
        )

    except Exception as e:
        raise handle_llm_client_exceptions(e)
