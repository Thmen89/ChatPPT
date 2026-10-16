# Roadmap

ChatPPT is Presenton, made lean: one container, one data folder, fast, and customisable by
dropping files into `/data`. This file is the scoreboard and the plan. The principles are in
the planning prompt (it just works, really efficient, simple and elegant, heavily
customisable); `docs/architecture.md` describes what we started from.

## Scoreboard

Measured with `python scripts/bench/run.py` (full stack as shipped: nginx + Next.js + FastAPI +
MCP, mock LLM, 10 slides, `general` template, image generation off, 4 vCPU). The mock answers
instantly, so "0 ms" shows ChatPPT's own overhead; "800 ms" paces every LLM call like a fast
hosted model and shows what the pipeline's shape costs. Real-provider numbers
(`--real`) will be added once a key is configured.

| Metric | Baseline, mock 0 ms | Baseline, mock 800 ms | After wave 1, 0 ms / 800 ms | Target | Status |
|---|---|---|---|---|---|
| Cold start (all processes answering) | 4.9 s | 4.8 s | 4.1 s (9.4 s on a cold page cache) | < 3 s | |
| Idle RAM, whole stack | 493 MB (FastAPI 262, MCP 97, Next 113, nginx 22) | 493 MB | 435–451 MB (FastAPI 220: memory off by default) | < 300 MB | |
| Outline (create + stream) | 0.5 s | 1.3 s | 0.15 s / 0.97 s | provider-bound | |
| Time to first slide, after outline | 1.3 s | 2.3 s | 0.18 s / 1.8 s | < 1.5 s + one LLM call | |
| Time to full 10-slide deck, after outline | 1.3 s | 9.6 s | 0.91 s / 9.6 s | < 2 s + one LLM call (parallel) | |
| Prompt → full deck in editor | 1.9 s | 11.0 s | 1.2 s / 10.7 s | < 2 × LLM call | |
| PPTX export | 18.0 s | 16.9 s | 18.4 s / 18.9 s | < 5 s | |
| API deck incl. PPTX (`/presentation/generate`) | 22.6 s | 26.6 s | 22.4 s / 26.9 s | < 10 s + 2 LLM calls | |
| LLM requests per deck (UI / API) | 12 / 12 | 12 / 12 | 12 / 12 | 11 (outline, structure, 1/slide) or fewer | |
| Tokens per deck, approx (UI / API) | 18.2k / 17.7k | same | 18.2k / 17.7k | < 9k | |
| Container image, compressed | 1.25 GB (`ghcr.io/presenton/presenton:v0.8.7-beta`) | | not rebuilt (wave 2, packaging) | slim ≤ 450 MB, full ≤ 900 MB | |
| Git clone | 652 MB, 10,019 files | | tracked tree 141 MB → 46 MB; clone still carries history | < 100 MB | |
| CI | build only, no lint/types/e2e | | lint + types + tests + e2e + offline + scan (#5) | lint + types + tests + e2e + scan, < 10 min | |

Wave 1 (strip, zero telemetry, lean CI) did not touch the generation path, so the
generation numbers are unchanged within noise; the wins are RAM (memory off by default),
repo size, no outbound traffic and a real PR gate. Bench note: the icon model is no longer
in git, so the wave 1 run points `CHATPPT_FASTEMBED_ICON_CACHE_DIR` at the old cache to keep
icon search in the measured path.

Reading the baseline:

- **Export dominates.** 17–18 s of a 27 s API deck is the Puppeteer/PPTX export, with
  zero LLM latency. It renders every slide in headless Chromium through the Next.js
  `/pdf-maker` page and converts with a PyInstaller binary. Nothing else comes close.
- **Slides are generated one after another in the UI path** (`stream_presentation`),
  so a 10-slide deck costs ~10 LLM round-trips in series; the API path already batches
  10 in parallel. Parallelising the stream path turns 9.6 s into ~1.5 s at 800 ms latency.
- **Tokens are 80% prompt.** Every slide call embeds the layout's full JSON schema in the
  system prompt *and* sends it as `response_format`. Sending it once halves the bill.
- **Layout lookup launches Chromium.** `get_layout_by_name` runs an `extract-schema`
  Puppeteer task per generation before falling back to a JSON route; cached file-based
  manifests remove it entirely.
- **RAM is three Python/Node processes doing one job.** The MCP server is a second
  Python process that re-reads `openai_spec.json` and proxies to FastAPI; mounting it inside
  FastAPI saves ~100 MB. Lazy-loading fastembed/mem0 saves more.
- **Image size is mostly optional software**: LibreOffice, Tesseract, ImageMagick, spaCy,
  NLTK, fastembed weights, a second copy of Node in `/app/presentation-export`.

### Targets adjusted from the planning prompt

The prompt suggested first slide < 3 s, 10-slide deck < 30 s, idle RAM < 500 MB, slim image
< 800 MB, cold start < 5 s. The baseline already meets three of those on paper (first slide
2.3 s, idle 493 MB, cold start 4.8 s) because the numbers were measured without provider
latency and the stack is lighter than it looks at rest. They would not be meaningful
goals, so the table above tightens them and adds the two that matter most:

- **Export time is on the board** (it was not in the prompt) because it is the biggest cost.
- **Deck times are expressed relative to one LLM call**, since the provider bounds them;
  the pipeline's job is to not add much on top.
- **Idle RAM < 300 MB and image ≤ 450 MB compressed** (compressed is what registries and
  pull times show; the prompt did not say which).
- **Clone size and CI** are tracked because "it just works" starts at `git clone`.

If a target proves unreachable, the PR that hits the wall says what bounds it.

## Workstreams

Each agent owns only its listed paths, works on its own branch, and opens small PRs with
before/after bench numbers where relevant. Anything outside its paths goes through the lead.

### Done by the lead first

- `docs/architecture.md`, this roadmap, `scripts/bench/` (mock LLM + benchmark). **PR 1.**
- Shared contracts, one PR, that every agent builds on. **PR 2.** See `docs/contracts.md`:
  - `chatppt.toml` schema and loader (`servers/fastapi/chatppt/settings.py`), env overrides,
    legacy env names mapped with a warning.
  - Template folder format and manifest (`template.json`), discovery of
    `<data>/templates/*` plus the built-ins.
  - Prompt override lookup: `<data>/prompts/<name>.md` over the shipped default files.
  - Provider registry and per-step model routing (`chatppt/providers/`).

### Wave 1 (parallel, independent of the contracts)

| Agent | Concern | Owns | Done when |
|---|---|---|---|
| A | Strip and rebrand | repo root, `.github/` (not workflows), `readme_assets/`, branding strings, package metadata, `NOTICE` | `grep -ri presenton` hits only attribution; committed artifacts (87 MB model, `.coverage`, `tsbuildinfo`, 7 MB gif) gone and ignored; governance files present |
| B | Zero telemetry, offline start | `utils/mixpanel.ts` + call sites, `electron/app/sentry/`, backend Sentry init, `electron/app/utils/update-checker.ts`, first-run downloads (spaCy, NLTK, fastembed, Ollama installer) | a container with no network and no providers makes zero outbound connections, proven in CI |
| C | Lean CI and test harness | `.github/workflows/`, lint/type configs, test scaffolding, mock providers (reuse `scripts/bench/mock_llm.py`), Playwright | ruff + pyright/mypy + eslint + `tsc --noEmit` + unit tests + one Playwright flow (prompt → generate → edit → export PPTX) + dependency/container scan, green on `main` in < 10 min |

### Wave 2 (after PR 2)

| Agent | Concern | Owns | Done when |
|---|---|---|---|
| D | Speed | `utils/llm_calls/`, generation endpoints and background tasks, `utils/process_slides.py`, the stream path into the editor, layout/icon/preview caching, the export path's render step | stream path parallel; schema sent once per call; layout lookup cached and Chromium-free; export under 5 s or the PR explains the bound; scoreboard numbers on every PR |
| E | Customisation layer | settings loader and `chatppt.toml`, `utils/get_env.py`, `utils/user_config*.py`, the env-rewrite middleware, template loading in `app/presentation-templates/` and backend counterparts, prompt files, provider registry and routing, theme tokens, hooks | add a template, theme, prompt override and provider by dropping files in `/data` with no rebuild; PPTX import writes a template folder; `docs/customising.md` shows each |
| F | Packaging and footprint | `Dockerfile`, `start.js`, `nginx.conf` (remove if Next.js/FastAPI can front directly), `docker-compose.yml`, `deploy/`, health endpoints, `chatppt` CLI, MCP mounted in-process | slim image default with `full` variant; no runtime installs; one small compose file; `/healthz`; structured logs; `chatppt backup/restore/reset-password/doctor`; non-root multi-arch on GHCR; Postgres one opt-in setting; upgrade test in CI; footprint targets hit |

### Wave 3 (after wave 2)

| Agent | Concern | Owns | Done when |
|---|---|---|---|
| G | Auth and hardening, lightly | `api/v1/auth/`, `utils/simple_auth.py`, auth parts of `api/middlewares.py`, CORS/CSRF/headers/rate-limit middleware, upload and URL-fetching code, exporter image access, login screens | a few local users with admin flag; hashed revocable API tokens for REST and MCP; optional OIDC and trusted-header login; admin-only provider keys; CORS locked, CSRF, secure cookies, security headers, in-process rate limit, upload validation, SSRF/path-traversal guards, signed short-lived image URLs; existing single account migrated automatically; each fix has a test |
| H | Editor and UX polish | editor, home and onboarding screens in `servers/nextjs/` | prompt in, deck out, edit in place; screens and settings that no longer earn their place removed; streaming feels instant; keyboard first-class; a new user reaches an exported deck in ≤ 3 steps |
| I | Docs | `docs/` (except generated), README | README leads with the one-line `docker run`; 2-minute quickstart; `docs/customising.md`; API + MCP reference; offline install note; every command tested against a fresh container |

The Electron desktop app stays supported but secondary: agents keep it building when they
touch shared code and add nothing desktop-only.

## Decisions taken so far (defaults picked, not asked)

- Image generation stays off unless an image provider is configured (upstream behaviour).
- Bench numbers are compressed image sizes and median-of-N wall-clock seconds.
- The lead's PRs land on `main` by squash merge; agents' PRs are reviewed by the lead
  against the principles and rejected if they make the default heavier, slower, add a
  required service, or add a setting a new user has to understand.
