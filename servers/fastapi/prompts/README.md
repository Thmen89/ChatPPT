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
| `outline.system.md` | system prompt for the outline (title + one markdown block per slide) | `verbosity_instructions`, `title_slide_instructions`, `toc_instructions`, `layout_instructions` |
| `outline.user.md` | user prompt for the outline | `content`, `n_slides`, `language`, `tone`, `date`, `include_title_slide`, `toc_line`, `instructions`, `context` |
| `outline.layouts.md` | added to the outline prompt when the template is known up front (API/MCP), so the outline also picks each slide's layout | `layouts` |
| `structure.system.md` | layout choice per slide after the outline (editor flow) | `user_instructions`, `n_slides` |
| `structure.user.md` | the layouts and the outline for that call | `layouts`, `outline` |
| `structure_from_markdown.system.md` | layout choice when the API is given slide markdown | `user_instructions`, `presentation_layout` |
| `edit_slide.system.md` | editing one slide's content from a prompt | `user_instructions`, `tone_instructions`, `verbosity_instructions`, `memory_context` |
| `edit_slide.user.md` | the edit request and the slide data | `current_date_time`, `language`, `prompt`, `slide_data` |
| `edit_slide_html.system.md` | editing a slide's HTML | (none) |
| `edit_slide_html.user.md` | the HTML edit request | `prompt`, `memory_context`, `html` |
| `select_slide_layout.system.md` | picking a layout when an edit asks for one | `layouts`, `memory_context` |
| `select_slide_layout.user.md` | the edit request for that call | `prompt`, `slide_data`, `current_layout` |

The layout schema of a slide is not in any prompt: it goes to the model once, as the
structured-output schema. Endpoints that ignore structured output get it added to the
prompt automatically after their first reply misses it.

Still hard-coded in Python and due to move here (customisation workstream):
`templates/prompts.py` (PPTX import → layout code), `api/v1/ppt/endpoints/prompts.py`
(HTML edit), `services/chat/prompts.py`.
