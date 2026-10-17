# Architecture

How ChatPPT runs today. Where it came from is in [upstream.md](upstream.md); the numbers and
what changed per workstream are in [roadmap.md](roadmap.md).

## One container, one port

```
              :5000 (PORT, public)
 browser ──▶  node start.js  (PID 1)
              └─ Next.js standalone server, in the same process
                   UI pages; /api/template, /api/export-presentation, ...
                   rewrites /api/v1/*, /app_data/*, /static/*, /mcp, /docs, /openapi.json
                        │
                        ▼  127.0.0.1:8000 (loopback only)
              python server.py  (uvicorn, child of start.js)
                   FastAPI: generation, storage, auth, webhooks, config
                   MCP at /mcp, built on first request
                   export: spawns presentation-export (Puppeteer + converter), which
                   loads http://127.0.0.1:5000/pdf-maker?id=... in Chromium
```

- **No reverse proxy.** The rewrites live in `servers/nextjs/next.config.mjs` and are fixed at
  build time to `127.0.0.1:8000`. Forwarded requests may be idle for up to 30 minutes
  (`experimental.proxyTimeout`), since `POST .../presentation/generate` answers only when the
  deck is exported.
- **`start.js`** resolves the data folder (`/data`, or an old `/app_data` mount), hands it to
  uid 1000 and drops root, sets the loopback URLs (`FAST_API_INTERNAL_URL`,
  `CHATPPT_NEXTJS_URL`), starts FastAPI, then imports the Next.js server into its own process.
  It forwards SIGTERM to the child and exits when either side dies. It writes no config.
- **MCP** is mounted in FastAPI (`api/mcp.py`). Tools are generated from
  `openai_spec.json` and call the REST API over loopback with the caller's `Authorization`
  header. Nothing MCP-related is imported until the first `/mcp` request.
- **Health:** `GET /healthz` on the public port (the image's `HEALTHCHECK`).

## Data folder

Everything an install owns is in `server.data_dir` (`/data` in the container):

```
/data
├── chatppt.toml            settings (the settings page writes it; .bak keeps the previous one)
├── fastapi.db              SQLite (Postgres/MySQL via server.database_url)
├── templates/<id>/         template folders (PPTX imports land here as custom-<uuid>/)
├── themes/<id>.json        themes
├── prompts/<name>.md       prompt overrides
├── providers/*.py          extra LLM or image backends
├── hooks.py                generation and export hooks
├── uploads/ images/ exports/ fonts/ pptx-to-html/   files served under /app_data
├── userConfig.json         only Codex sign-in tokens (older settings are migrated once)
└── backups/                chatppt backup
```

`/app_data/*` serves only the media folders, behind sign-in or a signed link. See
[contracts.md](contracts.md) for each extension point and [customising.md](customising.md)
for how to use them.

## Configuration

`chatppt/settings.py`: one schema, read from `CHATPPT_*` env > `chatppt.toml` > legacy
Presenton env names > defaults, re-read when the file's mtime changes (checked at most once a
second). At startup `apply_to_environ` exports explicitly configured keys under their legacy
names so upstream readers (`utils/get_env.py`) see them, and an old `userConfig.json` is
copied into `chatppt.toml` once. The settings page reads and writes through
`GET/PUT /api/v1/config` (admin only; `CAN_CHANGE_KEYS=false` makes it read-only). Reference:
[config-reference.md](config-reference.md).

## Generation

The UI path:

1. `POST /api/v1/ppt/presentation/create` stores the prompt, slide count, template and so on.
2. `GET /api/v1/ppt/outlines/stream/{id}` streams the outline (SSE). With the template known,
   the same call picks each slide's layout (`outline.layouts.md`), so no structure call is
   needed.
3. `POST /api/v1/ppt/presentation/prepare` stores the outline and layouts.
4. `GET /api/v1/ppt/presentation/stream/{id}` generates slide content, `llm.concurrency` (8)
   slides at a time, fetching icons (local fastembed index) and images as each finishes, and
   streams them to the editor. `after_slide` runs on each.
5. Export: `POST /api/export-presentation` (Next.js) runs the export runtime, which renders
   `/pdf-maker?id=...` in headless Chromium and converts it to PPTX or PDF. `before_export`
   and `after_export` run around it.

`POST /api/v1/ppt/presentation/generate` does 2 to 5 in one call (FastAPI drives the same
exporter). Every LLM call gets its client from `llm_for_step(step)`, and every prompt comes
from `render_prompt(name)`.

Layout schemas come from Next.js (`/api/template?group=<id>`, which compiles the template's
TSX) and are cached in FastAPI by the template's fingerprint, so a template is compiled once
per change. The editor compiles folder layouts in the browser
(`app/hooks/compileLayout.ts`) with Tailwind compiled locally.

## Auth

`chatppt/auth/`: local users (one or more admins) with PBKDF2 passwords, HttpOnly session
cookies, hashed revocable API tokens (`cpt_...`), optional OIDC or trusted proxy header. One
ASGI middleware (`chatppt/auth/middleware.py`) authenticates every request, keeps admin routes
to admins, enforces CSRF on cookie requests, caps bodies and sets security headers. The
exporter gets a 15-minute read-only token; exported files and slide images use signed,
expiring links. Details: [SECURITY.md](../SECURITY.md#how-chatppt-protects-an-install).

## Storage

SQLModel over SQLite by default (`<data>/fastapi.db`, aiosqlite). Tables are created at
startup; Alembic migrations run when `MIGRATE_DATABASE_ON_STARTUP=true`. Tables: presentations,
slides, image assets, templates (pre-folder imports), layout code, key/value, chat history,
webhooks, async generation tasks, users, API tokens.

## Optional subsystems

| Subsystem | Cost | Default |
|---|---|---|
| Icon search | fastembed ONNX model baked into the image, local vector index | on |
| Images | your image provider | placeholders until one is configured |
| Chat memory (mem0) | spaCy, on-disk Qdrant, extra LLM calls; `:full` image only | off (`features.memory`) |
| OCR (Tesseract), LibreOffice, ImageMagick | `:full` image only | used when present |
| Error reporting | a DSN you set (`server.error_reporting_dsn`) and the SDK you install | off |

No analytics, no update checks, no runtime downloads: [telemetry.md](telemetry.md).

## Desktop app

`electron/` bundles both servers and starts them itself (not through `start.js`); it shares
the two server trees. Its dependency plan is in
[electron-dependency-strategy.md](electron-dependency-strategy.md).
