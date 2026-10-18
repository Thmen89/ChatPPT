# Customising ChatPPT

Everything is a file in the data folder (`/data` in Docker; `APP_DATA_DIRECTORY` elsewhere).
Nothing needs a rebuild or a restart: each file is re-read when it changes.

```
/data
├── chatppt.toml          settings (the settings page writes this file too)
├── templates/<id>/       slide templates: template.json + one .tsx per layout
├── themes/<id>.json      colour and font tokens
├── prompts/<name>.md     prompt overrides
├── providers/*.py        extra LLM or image backends
└── hooks.py              before_outline, after_slide, before_export, after_export
```

Each section names the test that covers it.

## Settings: `chatppt.toml`

`chatppt.toml` is the only source of truth. The settings page saves to it through
`PUT /api/v1/config`, writing atomically and keeping the previous file as `chatppt.toml.bak`.
Changes apply on the next request. Every key also has an environment variable
(`CHATPPT_LLM__PROVIDER` and so on), and the environment wins. Old Presenton variable names
still work and log one warning each. `CAN_CHANGE_KEYS=false` makes the settings page
read-only. The full list is in [config-reference.md](config-reference.md).

On first start, an existing `userConfig.json` is copied into `chatppt.toml` once. A copy
is kept as `userConfig.json.migrated`.

## Templates

A template is a folder: `template.json`, plus one `.tsx` file per layout. A layout file
exports `layoutId`, `layoutName`, `layoutDescription`, a zod `Schema` and a default React
component, the same format as the built-ins in
`servers/nextjs/app/presentation-templates/`. A `.tsx` file that declares no `layoutId` is
a helper the layouts can import (`import { Rule } from "./Rule"`).

```json
{ "id": "desk", "name": "Desk", "description": "Dark, two layouts", "ordered": false, "icon_weight": "regular" }
```

```tsx
import React from "react";
import * as z from "zod";
import { Rule } from "./Rule";

export const layoutId = "desk-title";
export const layoutName = "Title";
export const layoutDescription = "Opening slide: a title and a one-line subtitle.";

export const Schema = z.object({
  title: z.string().min(3).max(60).default("Quarterly review").meta({ description: "Slide title" }),
  subtitle: z.string().min(3).max(120).default("What moved and why").meta({ description: "One-line subtitle" }),
});

export default function Title({ data }: { data?: Partial<z.infer<typeof Schema>> }) {
  return (
    <div className="w-full max-w-[1280px] aspect-video mx-auto flex flex-col justify-center gap-6 px-[96px] bg-[#0b1220] text-[#e6e9ef]">
      <h1 className="text-[56px] font-semibold">{data?.title}</h1>
      <Rule />
      <p className="text-[24px] text-[#9aa4b2]">{data?.subtitle}</p>
    </div>
  );
}
```

Copy the folder to `/data/templates/desk/` and it shows up in the template picker. It
generates, renders in the editor and exports, all without a rebuild. Tailwind classes,
including arbitrary values like `bg-[#0b1220]`, are compiled locally on first use.

- **Imports:** layouts can import `react`, `zod`, `recharts`, `lucide-react`, `d3`,
  `chart.js`, the shared `ImageSchema`/`IconSchema` (`../defaultSchemes`) and files in the
  same folder.
- **Assets:** images and fonts go in `assets/` and `fonts/`. Reference them as
  `"./assets/logo.png"`. `"fonts": {"Inter": "fonts/Inter.woff2"}` in `template.json`
  loads a font.
- **Overriding a built-in:** a folder whose id matches a built-in (`general`, `modern`, …)
  replaces it.
- **PPTX import:** importing a PPTX writes a `custom-<uuid>` folder. Edit it like any other.
  Templates imported by older versions are moved out of the database into folders on
  first start, keeping their ids.
- **Editing:** after an edit, switch back to the browser tab and the change shows up.
- **Location:** to keep templates outside the data folder, set `CHATPPT_PATHS__TEMPLATES`
  as an environment variable, not in `chatppt.toml`; both servers read it.

Tested by `servers/nextjs/e2e/template-folder.spec.ts` (fixture
`e2e/fixtures/templates/desk/`) and `tests/unit/test_chatppt_template_folders.py`.

## Themes

A theme is a set of colours and a font, saved as `/data/themes/<id>.json`:

```json
{
  "name": "Ink",
  "colors": {
    "primary": "#3b82f6", "background": "#0a0a0a", "card": "#171717", "stroke": "#262626",
    "primary_text": "#ffffff", "background_text": "#fafafa",
    "graph": ["#3b82f6", "#22c55e", "#eab308"]
  },
  "font": { "name": "Inter" }
}
```

Layouts see the tokens as CSS variables: `--primary-color`, `--background-color`,
`--card-color`, `--stroke`, `--primary-text`, `--background-text`, `--graph-0` to `--graph-9`
(the `graph` list repeats to fill ten slots), plus `--heading-font-family` and
`--body-font-family`. Theme files appear in the editor's **Theme** menu next to the built-in
themes. To give every new deck a theme, set it in `chatppt.toml`:

```toml
[defaults]
theme = "ink"
```

Without a theme, each template keeps its own colours. `font.url` is optional: point it at a
stylesheet or font file you serve locally (`/app_data/fonts/…`). Leave it empty to use an
installed font. ChatPPT ships one theme, `graphite`.

Tested by `e2e/template-folder.spec.ts` (fixture `e2e/fixtures/themes/ink.json`) and
`tests/unit/test_chatppt_themes_providers_hooks.py`.

## Prompts

Prompts ship as files in `servers/fastapi/prompts/<name>.md`. To change one, save a file
with the same name in `/data/prompts/`. `{placeholders}` work as in the shipped file.

```bash
cp servers/fastapi/prompts/slide_content.system.md /data/prompts/
$EDITOR /data/prompts/slide_content.system.md
```

Tested by `tests/unit/test_chatppt_templates_prompts_themes.py`.

## Providers

**OpenAI-compatible servers** (vLLM, llama.cpp, a gateway) need only `chatppt.toml`:

```toml
[llm]
provider = "vllm-box"
model = "qwen"

[llm.providers.vllm-box]
base_url = "http://10.0.0.5:8000/v1"
api_key = "secret"
```

Image endpoints work the same way, with `[images] provider = "…"` and
`[images.providers.<id>]` holding `base_url`, `api_key` and `model`.

**Per-step models:** you can send each step to a different provider and model. The steps
are `outline`, `structure`, `content`, `edit`, `chat` and `template`. This is set in the
file only, not in the settings page:

```toml
[llm.routing.outline]
model = "small-fast-model"

[llm.routing.content]
provider = "anthropic"
model = "…"
```

**Any other backend** is one Python file in `/data/providers/`:

```python
from pathlib import Path

from chatppt.providers import ImageProviderSpec, LLMProviderSpec, register_image, register_llm
from llmai.shared import OpenAIClientConfig


def build(creds):  # creds: the [llm.providers.lab] table
    return OpenAIClientConfig(base_url=creds.base_url or "http://lab.invalid/v1", api_key=creds.api_key or "x")


async def generate(prompt, output_dir):  # return a file path in output_dir, or an https URL
    path = Path(output_dir) / "lab.png"
    path.write_text(prompt)
    return str(path)


register_llm(LLMProviderSpec("lab", "Lab model", "lab-1", build))
register_image(ImageProviderSpec("lab-images", "Lab images", "generative", generate=generate))
```

Select them with `llm.provider = "lab"` and `images.provider = "lab-images"`. Put the
credentials under `[llm.providers.lab]` or `[images.providers.lab-images]`. A file that
fails to import is logged and skipped. The chat panel still uses the provider chosen on
the settings page.

Tested by `tests/unit/test_chatppt_themes_providers_hooks.py`.

## Hooks

`/data/hooks.py` can define any of the four hooks below. A hook can change its argument in
place or return a replacement. Returning `None` keeps the argument as it is. Hooks can be
`async`. If a hook raises, the error is logged and generation carries on unchanged.

```python
def before_outline(request):        # dict: content, n_slides, language, instructions, tone, ...
    request["instructions"] = "House style: no adjectives."
    return request

def after_slide(slide):             # slide.content is the layout data, slide.layout its id
    slide.content["title"] = slide.content.get("title", "").upper()

def before_export(deck):            # dict with "slides"; affects the export, not the saved deck
    deck["slides"] = [s for s in deck["slides"] if not s["content"].get("draft")]

async def after_export(path):       # the written .pptx / .pdf
    print("exported", path)
```

Tested by `tests/unit/test_chatppt_themes_providers_hooks.py`.
