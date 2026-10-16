from typing import Optional

from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage
from models.presentation_layout import PresentationLayoutModel
from models.presentation_outline_model import PresentationOutlineModel
from chatppt.prompts import render_prompt
from chatppt.providers import llm_for_step
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import generate_structured_with_schema_retries
from utils.get_dynamic_models import get_presentation_structure_model_with_n_slides
from utils.schema_utils import prepare_schema_for_validation
from models.presentation_structure_model import PresentationStructureModel


def get_messages(
    presentation_layout: PresentationLayoutModel,
    n_slides: int,
    data: str,
    instructions: Optional[str] = None,
) -> list[Message]:
    system_prompt = render_prompt(
        "structure.system",
        user_instructions=f"# User Instruction: {instructions}" if instructions else "",
        n_slides=n_slides,
    )

    return [
        SystemMessage(content=system_prompt),
        UserMessage(
            content=render_prompt(
                "structure.user",
                layouts=presentation_layout.to_string(),
                outline=data,
            )
        ),
    ]


def get_messages_for_slides_markdown(
    presentation_layout: PresentationLayoutModel,
    n_slides: int,
    data: str,
    instructions: Optional[str] = None,
) -> list[Message]:
    system_prompt = render_prompt(
        "structure_from_markdown.system",
        user_instructions=instructions or "",
        presentation_layout=presentation_layout.to_string(with_schema=True),
    )

    return [SystemMessage(content=system_prompt), UserMessage(content=data)]


async def generate_presentation_structure(
    presentation_outline: PresentationOutlineModel,
    presentation_layout: PresentationLayoutModel,
    instructions: Optional[str] = None,
    using_slides_markdown: bool = False,
) -> PresentationStructureModel:
    client, model = llm_for_step("structure")
    response_model = get_presentation_structure_model_with_n_slides(
        len(presentation_outline.slides)
    )

    try:
        messages = (
            get_messages_for_slides_markdown(
                presentation_layout,
                len(presentation_outline.slides),
                presentation_outline.to_string(),
                instructions,
            )
            if using_slides_markdown
            else get_messages(
                presentation_layout,
                len(presentation_outline.slides),
                presentation_outline.to_string(),
                instructions,
            )
        )
        structure_schema = prepare_schema_for_validation(
            response_model.model_json_schema(),
            strict=True,
        )
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=structure_schema,
            strict=True,
        )

        content = await generate_structured_with_schema_retries(
            client,
            model,
            messages=messages,
            response_format=response_format,
            json_schema=structure_schema,
            strict=True,
            validate_schema=True,
        )
        return PresentationStructureModel(**content)
    except Exception as e:
        raise handle_llm_client_exceptions(e)
