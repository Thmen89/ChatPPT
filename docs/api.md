# API and MCP

Everything is on the one public port (5000). The REST API, MCP and the API docs are served by
FastAPI behind it; nothing else needs to be exposed.

## Auth

Every `/api/*`, `/mcp`, `/docs`, `/openapi.json` and `/app_data/*` request needs a signed-in
user, unless `auth.disabled = true`.

| Method | Use it for | How |
|---|---|---|
| API token | scripts, MCP clients | `Authorization: Bearer cpt_...` |
| Basic | one-off calls, making the first token | `curl -u user:password` (rate-limited like logins) |
| Session cookie | the browser | set by the login page |

Make a token on **Settings → Account & tokens**, or:

```bash
curl -s -u admin:<password> -X POST http://localhost:5000/api/v1/auth/tokens \
  -H 'Content-Type: application/json' -d '{"name": "scripts"}'
# {"id": 1, "name": "scripts", ..., "token": "cpt_..."}
```

The token is shown once, stored only as a hash, acts as the user who made it, and is revoked
with `DELETE /api/v1/auth/tokens/{id}`. Admin-only routes (`/api/v1/config`, users,
webhooks) need an admin's token. Details: [SECURITY.md](../SECURITY.md).

## Endpoints

The full list, with schemas, is at `/docs` (Swagger UI) and `/openapi.json`. The ones you need:

| Method and path | Does |
|---|---|
| `POST /api/v1/ppt/presentation/generate` | Prompt to exported deck in one call; returns when the file is written |
| `POST /api/v1/ppt/presentation/generate/async` | Same, returns `{"id": "task-...", "status": ...}` at once |
| `GET /api/v1/ppt/presentation/status/{task_id}` | Poll an async task; `data` holds the result when `status` is `completed` |
| `POST /api/v1/ppt/files/upload` | Multipart `files=@report.pdf`; returns paths to pass as `files` to generate |
| `GET /api/v1/ppt/presentation/all` | All decks |
| `GET /api/v1/ppt/presentation/{id}` | One deck with its slides |
| `POST /api/v1/ppt/presentation/edit` | Patch slide content by index, re-export (`presentation_id`, `slides`, `export_as`) |
| `POST /api/v1/ppt/presentation/derive` | Same, into a copy |
| `DELETE /api/v1/ppt/presentation/{id}` | Delete a deck |
| `POST /api/v1/webhook/subscribe` | `{"url", "event", "secret"}`; events `presentation.generation.completed` / `.failed` (admin) |
| `GET`, `PUT /api/v1/config` | Read or change settings in `chatppt.toml` (admin) |
| `GET /healthz` | Liveness, no auth |

### Generate

```bash
curl -s -X POST http://localhost:5000/api/v1/ppt/presentation/generate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content": "Q3 review: thesis, numbers, risks", "n_slides": 6, "template": "general", "export_as": "pptx"}'
```

| Field | Default | |
|---|---|---|
| `content` | required | The prompt, or the text to turn into slides |
| `n_slides` | model decides | 1 to 50 |
| `template` | `general` | A built-in id or a folder in `<data>/templates/` |
| `language` | model decides | e.g. `"English"` |
| `instructions` | | Extra guidance for the model |
| `tone` | `default` | `default`, `casual`, `professional`, `funny`, `educational`, `sales_pitch` |
| `verbosity` | `standard` | `concise`, `standard`, `text-heavy` |
| `files` | | Paths returned by `files/upload` |
| `slides_markdown` | | One markdown string per slide; skips the outline |
| `include_title_slide` | `true` | |
| `include_table_of_contents` | `false` | |
| `web_search` | `false` | Provider-side grounding where supported |
| `export_as` | `pptx` | `pptx` or `pdf` |
| `trigger_webhook` | `false` | Notify webhook subscribers |

Response:

```json
{
  "presentation_id": "6f0c...",
  "path": "/data/exports/q3-review_6f0c....pptx",
  "edit_path": "/presentation?id=6f0c...",
  "download_url": "/app_data/exports/q3-review_6f0c....pptx?exp=...&sig=..."
}
```

`path` is where the file is on the server (in the data folder). `download_url` is signed and expires after `auth.signed_url_minutes` (60); it needs no auth
header, so it can be handed on: `curl -o deck.pptx "http://localhost:5000$download_url"`.
`edit_path` opens the deck in the editor.

A synchronous call can take minutes with a real model; the public port keeps the request
open for up to 30 minutes. For longer jobs, or clients with short timeouts, use
`generate/async` and poll `status/{task_id}`.

## MCP

ChatPPT is an MCP server at `http://<host>:5000/mcp` (streamable HTTP), inside the FastAPI
process; it is built on the first `/mcp` request, so an install that never uses it pays
nothing. Tools:

| Tool | Calls |
|---|---|
| `generate_presentation` | `POST /api/v1/ppt/presentation/generate` (same fields as above) |
| `templates_list` | `GET /api/v1/ppt/template-management/summary` |

Send an API token; tool calls run as that user:

```json
{
  "mcpServers": {
    "chatppt": {
      "url": "http://localhost:5000/mcp",
      "headers": { "Authorization": "Bearer cpt_..." }
    }
  }
}
```

The tools are generated from `servers/fastapi/openai_spec.json`; add an endpoint there to
expose it as a tool.
