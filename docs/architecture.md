# Architecture (as inherited from Presenton 0.8.7-beta)

How the app works today, written down so every workstream starts from the same
picture. Corrections to the planning prompt's assumptions are marked **(correction)**.

## Processes in the container

`start.js` (Node) is PID 1. It writes `userConfig.json` from env vars, then spawns:

| Process | Port | Role |
|---|---|---|
| nginx | 80 | Reverse proxy: `/` → Next.js, `/api/v1/` → FastAPI, `/mcp` → MCP, `/docs`. Also serves nothing itself; only routing. |
| Next.js (standalone) | 3000 | UI (editor, outline, templates, settings) and a handful of server routes (`/api/template`, `/api/export-presentation`, `/api/user-config`, …). |
| FastAPI (uvicorn) | 8000 | All generation, storage, export orchestration, auth, webhooks. |
| MCP server (fastmcp) | 8001 | Generated at startup from `openai_spec.json`; proxies tool calls to FastAPI with an internal auth header. |

Hard-coded assumptions worth knowing: FastAPI calls `http://localhost/...` (port 80,
i.e. nginx) to reach Next.js for layout schemas and export pages, so nginx is
load-bearing today, not optional. `NEXT_PUBLIC_URL` defaults to `http://127.0.0.1`.

## The generation path (what the UI does)

1. `POST /api/v1/ppt/presentation/create` stores a `PresentationModel` row (prompt, n_slides, tone, …).
2. `GET /api/v1/ppt/outlines/stream/{id}` streams the outline as SSE. One LLM call
   (`utils/llm_calls/generate_presentation_outlines.py`) with a JSON-schema response
   of exactly `n` slides, each `## title` + markdown body (100–1200 chars).
3. The UI fetches the layout for the chosen template. Built-in templates live as React/TSX
   files in `servers/nextjs/app/presentation-templates/<group>/*.tsx`, each exporting a
   zod `Schema`, `layoutId`, `layoutName`, `layoutDescription` and the component.
   `settings.json` per group carries `ordered`, `default`, `icon_weight`.
4. `POST /api/v1/ppt/presentation/prepare` picks a layout per slide. If the template is
   `ordered`, no LLM call; otherwise one LLM call (`generate_presentation_structure.py`)
   returns a list of layout indices.
5. `GET /api/v1/ppt/presentation/stream/{id}` generates slide content **sequentially**:
   one LLM call per slide (`generate_slide_content.py`, JSON-schema response matching the
   layout's schema plus a speaker note), each followed by asset fetching (icon search via a
   local fastembed vector store, image generation via the configured image provider).
   Slides are streamed to the editor as they finish.
6. Export: `POST /api/export-presentation` (Next.js) runs the bundled
   `presentation-export` runtime (a ~66 MB zip from `presenton/presenton-export`
   releases: Puppeteer + a PyInstaller converter). It opens `/pdf-maker?id=…` in headless
   Chromium, renders each slide to HTML, and converts to PPTX/PDF. Needs `sharp`'s native
   addon and a Chromium binary.

The REST API (`POST /api/v1/ppt/presentation/generate`) does steps 2, 4, 5, 6 in one call,
generating slide content in **parallel batches of 10** (unlike the UI stream path).

### Where the layout schema comes from on the backend

`templates/get_layout_by_name.py` resolves a template name by **launching Chromium through
the export runtime** (`extract-schema` on `http://localhost/schema?group=…`), then falls back
to the JSON route `http://localhost/api/template?group=…`, then overlays `settings.json`
read from disk. This runs on every generation; nothing is cached. It is the single biggest
avoidable cost in the pipeline after the export itself. **(correction)**: the prompt said
templates are "compiled into the Next.js app"; that is true for the editor, but layout
schemas are also extracted at runtime via Puppeteer or Babel (`lib/compile-template-schema.ts`).

### Custom templates

Importing a PPTX (`templates/router.py`, 17 endpoints) converts slides to images, asks the
LLM (vision) to write TSX layouts (`templates/prompts.py`), stores the TSX in the
`presentation_layout_codes` table, and compiles it **in the browser** with
`@babel/standalone` (`app/hooks/compileLayout.ts`, with React, Recharts, d3 and Lucide in
scope). This is the mechanism "templates as files" can reuse: layouts are already TSX text
compiled at runtime; only the storage (DB vs folder) and discovery differ.

## Configuration

Three layers, all mutable at runtime:

- **Environment variables** (~85 getters in `utils/get_env.py`, ~74 setters in `utils/set_env.py`).
- **`userConfig.json`** in the data directory, written by `start.js` from env at boot and by
  the settings UI (`/api/user-config`), with lock/backup handling in `utils/user_config_store.py`.
- **`UserConfigEnvUpdateMiddleware`**: on **every HTTP request**, re-reads `userConfig.json`
  and rewrites `os.environ` (`utils/user_config.py::update_env_with_user_config`) unless
  `CAN_CHANGE_KEYS=false`.

Provider selection is a 15-way `if/elif` repeated in `utils/llm_provider.py` (model),
`utils/llm_config.py` (client config), `utils/model_availability.py` (startup check) and
`start.js` (env → config). LLM calls go through the `llmai` package (one client API over
OpenAI-compatible, Anthropic, Google, Vertex, Azure, Bedrock, …).

## Storage

SQLite by default (`<data>/fastapi.db`, SQLModel + aiosqlite); Postgres/MySQL via
`DATABASE_URL`. Five Alembic migrations, run only when `MIGRATE_DATABASE_ON_STARTUP=true`
(otherwise `create_all`). Tables: presentations, slides, image assets, templates, layout
code, key/value, chat history, webhooks, async generation tasks, ollama pull status.

Auth is a single username + bcrypt-style hash + session secret stored in **`userConfig.json`**
(`utils/simple_auth.py`), checked by `SessionAuthMiddleware` on `/api/*` and `/app_data/*`
except `/app_data/images/`, which is public so the exporter can fetch images without a cookie.

## Optional subsystems (upstream defaults; see roadmap for what changed)

| Subsystem | Cost | Default |
|---|---|---|
| mem0 chat memory (`services/mem0_*`, `services/chat/`, ~3.4k lines) | spaCy `en_core_web_sm`, NLTK data, on-disk Qdrant, extra LLM calls | upstream: on. ChatPPT: off (`features.memory`) since #4 |
| Icon search (`services/icon_finder_service.py`) | fastembed MiniLM ONNX (baked at image build; untracked since #3) + 21 MB JSON vectorstore | always; never downloads at runtime since #4 |
| OCR | Tesseract + traineddata | installed in image |
| LibreOffice | ~400 MB in image | installed in image |
| Chromium + ImageMagick | required by export | installed in image |
| Ollama | upstream: `curl \| sh` at container start. Removed in #4 | off |
| Mixpanel (UI) | upstream hard-coded token. Removed in #4 | gone |
| Sentry | backend opt-in via `server.error_reporting_dsn`; Electron DSN removed in #4 | off |

## Desktop app

`electron/` bundles both servers plus LibreOffice, ImageMagick and Chromium; it has its own
update checker pointing at `raw.githubusercontent.com/presenton/presenton` and
`presenton.ai/download`. It shares the two server trees; nothing in the servers is
desktop-only except path helpers (`utils/path_helpers.py`).

## Size and weight (measured, this commit)

- Git clone: 652 MB `.git`, 10,019 files; largest tracked blobs: 87 MB fastembed model,
  15 MB icons vectorstore, 7.3 MB `loading.gif`, 6.3 MB icons.json, 1.3 MB NOTICE.
- Python venv (`uv sync`, 3.11): 647 MB. Next.js `node_modules`: 1.1 GB; standalone build 425 MB.
- Upstream container image `ghcr.io/presenton/presenton:v0.8.7-beta`: **1.25 GB compressed**, 22 layers.
- CI: one workflow, builds a PyInstaller binary; no lint, no type check, no e2e.

See `docs/roadmap.md` for the scoreboard and the workstreams.
