from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.slide_layout_index import SlideLayoutIndex
from models.sql.slide import SlideModel
from chatppt.prompts import render_prompt
from chatppt.providers import llm_for_step
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import generate_structured_with_schema_retries
from utils.schema_utils import prepare_schema_for_validation


def get_messages(
    prompt: str,
    slide_data: dict,
    layout: PresentationLayoutModel,
    current_slide_layout: int,
    memory_context: str = "",
) -> list[Message]:
    return [
        SystemMessage(
            content=render_prompt(
                "select_slide_layout.system",
                layouts=layout.to_string(),
                memory_context=(
                    f"\n# Retrieved Presentation Memory Context\n{memory_context}\n"
                    if memory_context
                    else ""
                ),
            ),
        ),
        UserMessage(
            content=render_prompt(
                "select_slide_layout.user",
                prompt=prompt,
                slide_data=slide_data,
                current_layout=current_slide_layout,
            ),
        ),
    ]


async def get_slide_layout_from_prompt(
    prompt: str,
    layout: PresentationLayoutModel,
    slide: SlideModel,
    memory_context: str = "",
) -> SlideLayoutModel:
    client, model = llm_for_step("edit")

    slide_layout_index = layout.get_slide_layout_index(slide.layout)

    try:
        layout_index_schema = prepare_schema_for_validation(
            SlideLayoutIndex.model_json_schema(),
            strict=True,
        )
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=layout_index_schema,
            strict=True,
        )
        messages = get_messages(
            prompt,
            slide.content,
            layout,
            slide_layout_index,
            memory_context,
        )

        content = await generate_structured_with_schema_retries(
            client,
            model,
            messages=messages,
            response_format=response_format,
            json_schema=layout_index_schema,
            strict=True,
            validate_schema=True,
        )
        index = SlideLayoutIndex(**content).index
        return layout.slides[index]

    except Exception as e:
        raise handle_llm_client_exceptions(e)
