from typing import Optional
from fastapi import HTTPException
from llmai.shared import SystemMessage, UserMessage
from chatppt.prompts import render_prompt
from chatppt.providers import llm_for_step
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import extract_text, get_generate_kwargs, run_llm_call

def get_user_prompt(prompt: str, html: str, memory_context: Optional[str] = None):
    return render_prompt(
        "edit_slide_html.user",
        prompt=prompt,
        memory_context=(
            f"\n**Retrieved Presentation Memory Context:**\n{memory_context}\n"
            if memory_context
            else ""
        ),
        html=html,
    )


async def get_edited_slide_html(
    prompt: str, html: str, memory_context: Optional[str] = None
):
    client, model = llm_for_step("edit")

    try:
        response = await run_llm_call(
            client.generate,
            **get_generate_kwargs(
                model=model,
                messages=[
                    SystemMessage(content=render_prompt("edit_slide_html.system")),
                    UserMessage(
                        content=get_user_prompt(prompt, html, memory_context)
                    ),
                ],
            ),
        )
        response_text = extract_text(response.content)
        if response_text is None:
            raise HTTPException(status_code=400, detail="LLM did not return any content")
        return extract_html_from_response(response_text) or html
    except Exception as e:
        raise handle_llm_client_exceptions(e)


def extract_html_from_response(response_text: str) -> Optional[str]:
    start_index = response_text.find("<")
    end_index = response_text.rfind(">")

    if start_index != -1 and end_index != -1 and end_index > start_index:
        return response_text[start_index : end_index + 1]

    return None
