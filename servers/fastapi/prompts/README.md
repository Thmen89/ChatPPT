# Prompts

Every file here is a prompt the backend sends to the model. Override any of them without
a rebuild by copying the file to `<data>/prompts/<same name>.md` and editing it; the
override is picked up on the next request.

Placeholders are `{name}` and are filled by the code that uses the prompt (see
`chatppt/prompts.py`). Unknown placeholders are left untouched. If you write literal JSON
in a prompt, double the braces: `{{ "key": 1 }}`.

| File | Used for | Placeholders |
|---|---|---|
| `slide_content.system.md` | system prompt for each slide's structured content | `markdown_emphasis_rules`, `user_instructions`, `tone_instructions`, `verbosity_instructions`, `output_fields_instructions` |
| `slide_content.user.md` | user prompt for each slide | `current_date_time`, `language`, `content` |

Still hard-coded in Python and due to move here (customisation workstream):
`utils/llm_calls/generate_presentation_outlines.py` (outline system/user),
`generate_presentation_structure.py` (layout selection, two variants),
`edit_slide.py`, `edit_slide_html.py`, `select_slide_type_on_edit.py`,
`templates/prompts.py` (PPTX import → layout code), `api/v1/ppt/endpoints/prompts.py`
(HTML edit), `services/chat/prompts.py`.
