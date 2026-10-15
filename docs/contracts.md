# Shared contracts

The four seams every workstream builds on. They live under `servers/fastapi/chatppt/` (and
`servers/nextjs/lib/template-dirs.ts` for the UI side) and are the only places that define
how ChatPPT is configured and extended. Upstream code is wired to them where it costs a
line or two; replacing upstream's own plumbing behind them is the customisation
workstream's job.

## The data folder

Everything a deployment owns lives in one directory, `/data` in the container
(`APP_DATA_DIRECTORY` / `server.data_dir` elsewhere):

```
/data
  chatppt.toml          configuration (optional; env vars work alone)
  chatppt.db            SQLite (today still fastapi.db; Postgres via server.database_url)
  templates/<id>/       template folders (below)
  prompts/<name>.md     prompt overrides
  themes/<id>.json      themes
  uploads/ images/ exports/ fonts/
```

## 1. Configuration: `chatppt.toml`

`chatppt/settings.py`. One file, one schema (`Settings`), generated reference in
`docs/config-reference.md` (`python -m chatppt --reference`).

- Precedence: `CHATPPT_*` env > `chatppt.toml` > legacy Presenton env names > defaults.
- Env form: `CHATPPT_` + key path upper-cased with `__` between levels
  (`CHATPPT_LLM__PROVIDERS__OPENAI__API_KEY`).
- Legacy names (`LLM`, `OPENAI_API_KEY`, `DISABLE_IMAGE_GENERATION`, …) are mapped by
  `LEGACY_ENV` and log one warning naming the new key. They are *not* "explicit": code that
  checks `settings.is_explicit("llm.provider")` can tell a real config from a bridged one.
- Bridge: `apply_to_environ(settings)` runs once at startup (`api/lifespan.py`) and exports
  explicitly configured keys under their legacy names so untouched `utils/get_env.py`
  readers keep working. The per-request `UserConfigEnvUpdateMiddleware` still exists; the
  customisation workstream removes it and makes the settings UI write `chatppt.toml`.
- Sections: `server`, `llm` (+ `llm.providers.<id>`, `llm.routing.<step>`), `images`
  (+ `images.providers.<id>`), `features`, `auth`, `paths`, `defaults`.
- Rule: a new user must not have to understand a setting to get a deck. Every new key needs
  a default that works and a one-line description (it becomes the reference).

## 2. Templates as folders

`chatppt/templates.py` and `servers/nextjs/lib/template-dirs.ts` implement the same rules.

- A template is `templates/<id>/` with `template.json` and one `.tsx` layout per slide type.
  Layout files are unchanged from upstream: `layoutId`, `layoutName`, `layoutDescription`,
  zod `Schema`, default component. Optional `theme.json`, `fonts/`, `assets/`.
- Discovery: built-ins (`servers/nextjs/app/presentation-templates/<id>/`) then
  `<data>/templates/<id>/`; same id in the data folder replaces the built-in.
- Manifest (`TemplateManifest`): `id`, `name`, `description`, `version`, `ordered`,
  `default`, `icon_weight`, optional `layouts` (explicit order), `theme`, `fonts`.
  Built-ins without a manifest fall back to their legacy `settings.json`.
- `TemplateInfo.fingerprint()` changes when any layout or the manifest changes: that is the
  cache key for compiled schemas and previews. Nothing should compile a layout twice for the
  same fingerprint.
- The backend's `/api/template?group=<id>` (Next.js, `lib/server-template-layouts.ts`) now
  resolves through the same discovery, so a dropped-in folder is already visible to
  generation. The editor-side registry (`presentation-templates/index.tsx`, static imports)
  still only knows built-ins; the customisation workstream swaps it for runtime loading via
  the existing `compileLayout.ts` path that custom (DB) templates use.
- Importing a company PPTX produces such a folder (today it writes TSX to the DB).

## 3. Prompts as files

`chatppt/prompts.py`, defaults in `servers/fastapi/prompts/<name>.md`.

- `render_prompt("slide_content.system", **vars)` reads `<data>/prompts/<name>.md` if it
  exists, else the shipped file; cached by mtime, so edits apply on the next request.
- `{placeholders}` use `str.format` syntax; unknown ones are left as-is; JSON in a prompt
  doubles its braces.
- `slide_content.system` / `slide_content.user` are moved as the reference; the remaining
  prompts are listed in `servers/fastapi/prompts/README.md` for the customisation
  workstream. New prompts start as files, never as Python strings.

## 4. Providers and model routing

`chatppt/providers/`.

- `LLMProviderSpec(id, label, default_model, build(creds) -> llmai ClientConfig, needs, …)`
  registered with `register_llm`; all 15 upstream providers are in `providers/llm.py`,
  each a few lines. A new backend is one more `register_llm` call (or one new file imported
  from `registry._ensure_loaded`). `ImageProviderSpec` likewise in `providers/images.py`.
- `llm_for_step(step)` → `(client, model)` for `outline | structure | content | edit | chat
  | template`, resolved from `[llm.routing].<step>` → `[llm]` → provider default. Generation
  code calls this instead of `get_client(config=get_llm_config()), get_model()`; the
  outline, structure, slide-content and edit calls already do.
- When nothing explicit is configured the resolver returns the legacy upstream config, so
  env/UI-configured installs behave exactly as before.
- Missing credentials are a 400 whose message names the `chatppt.toml` key to set.

## Themes as tokens

`chatppt/themes.py`, default in `servers/fastapi/themes/default.json`. A theme is colours
(hex), fonts, spacing, radius, logo and footer. `Theme.css_variables()` gives
`--chatppt-color-*`, `--chatppt-font-*`, `--chatppt-radius`, `--chatppt-spacing`; layouts
read those so one theme restyles every template. User themes: `<data>/themes/<id>.json`.

## Hooks (shape only; implemented by the customisation workstream)

Pre/post hooks around generation and export as Python callables registered from
`<data>/hooks.py`: `before_outline(request)`, `after_slide(slide)`, `before_export(deck)`,
`after_export(path)`. No plugin system; one file, plain functions.

## What this PR deliberately does not do

Remove the env-rewrite middleware, move the editor to runtime template loading, move the
rest of the prompts, convert PPTX import to folders, or change any default behaviour. Those
belong to the owning workstreams; this PR gives them the seams and the tests.
