# Shared contracts

The seams ChatPPT is configured and extended through. They live in
`servers/fastapi/chatppt/` (and `servers/nextjs/lib/template-dirs.ts` for the UI side). New
code goes through them; how to use each one as a user is in [customising.md](customising.md).

## The data folder

Everything a deployment owns lives in `server.data_dir` (`/data` in the container,
`APP_DATA_DIRECTORY` elsewhere). Layout: [architecture.md](architecture.md#data-folder).
Each user file is re-read when its mtime changes; nothing needs a restart.

## 1. Configuration: `chatppt.toml`

`chatppt/settings.py`. One schema (`Settings`); the reference
[config-reference.md](config-reference.md) is generated from it
(`python -m chatppt --reference` in `servers/fastapi`).

- Precedence: `CHATPPT_*` env > `chatppt.toml` > legacy Presenton env names > defaults.
- Env form: `CHATPPT_` + key path upper-cased, `__` between levels
  (`CHATPPT_LLM__PROVIDERS__OPENAI__API_KEY`). `CHATPPT_LLM_API_KEY` is a shorthand for the
  key of `llm.provider` (provider guessed from the key's prefix when none is set).
- Legacy names (`LLM`, `OPENAI_API_KEY`, `DISABLE_IMAGE_GENERATION`, ...) are mapped by
  `LEGACY_ENV` and log one warning naming the new key. They are not "explicit":
  `settings.is_explicit("llm.provider")` tells a real config from a bridged one.
- `get_settings()` reloads when the file changes. `apply_to_environ(settings)` exports
  explicit keys under their legacy names so `utils/get_env.py` readers see them; a reload
  re-exports and removes stale ones.
- Writes go through `chatppt/config_store.py` (`update_config`, atomic, keeps `.bak`); the
  settings page uses it via `PUT /api/v1/config`. An old `userConfig.json` is migrated once.
- Sections: `server`, `llm` (+ `llm.providers.<id>`, `llm.routing.<step>`), `images`
  (+ `images.providers.<id>`), `features`, `auth`, `paths`, `defaults`.
- Rule: a new user must not have to understand a setting to get a deck. Every new key needs
  a default that works and a one-line description (it becomes the reference).

## 2. Templates as folders

`chatppt/templates.py` and `servers/nextjs/lib/template-dirs.ts` implement the same rules.

- A template is `<id>/` with `template.json` and one `.tsx` per layout (`layoutId`,
  `layoutName`, `layoutDescription`, zod `Schema`, default component); other `.tsx` files are
  helpers. Optional `fonts/`, `assets/`.
- Discovery: built-ins (`servers/nextjs/app/presentation-templates/<id>/`), then
  `<data>/templates/<id>/`; the same id in the data folder replaces the built-in.
  `discover_templates()` / `get_template(id)`.
- Manifest (`TemplateManifest`): `id`, `name`, `description`, `version`, `ordered`,
  `default`, `icon_weight`, `layouts`, `fonts`.
- `TemplateInfo.fingerprint()` changes when any layout or the manifest changes; it is the
  cache key for compiled schemas. Nothing compiles a layout twice for one fingerprint.
- PPTX import writes a `custom-<uuid>/` folder; templates imported into the database by older
  versions are moved to folders at startup.

## 3. Prompts as files

`chatppt/prompts.py`; defaults in `servers/fastapi/prompts/<name>.md`, listed with their
placeholders in that folder's README.

- `render_prompt("slide_content.system", **values)` reads `<data>/prompts/<name>.md` if it
  exists, else the shipped file; cached by mtime.
- `{placeholders}` use `str.format` syntax; unknown ones are left as-is; JSON in a prompt
  doubles its braces.
- New prompts start as files, never as Python strings.

## 4. Providers and model routing

`chatppt/providers/`.

- `LLMProviderSpec(id, label, default_model, build(creds) -> llmai client config, needs, ...)`
  registered with `register_llm`; the built-ins are in `providers/llm.py`, image providers
  (`ImageProviderSpec`, `register_image`) in `providers/images.py`. `<data>/providers/*.py`
  files are imported and may register more.
- An unknown id with a `base_url` under `[llm.providers.<id>]` is an OpenAI-compatible
  endpoint; no code needed.
- `llm_for_step(step)` returns `(client, model)` for `outline | structure | content | edit |
  chat | template`, resolved from `[llm.routing].<step>`, then `[llm]`, then the provider's
  `model` and default. Every generation call uses it. With nothing explicit configured it
  returns the legacy upstream config.
- Missing credentials are a 400 whose message names the `chatppt.toml` key to set.

## 5. Themes as tokens

`chatppt/themes.py`; shipped themes in `servers/fastapi/themes/`, user themes in
`<data>/themes/<id>.json`. A theme is hex colours (`primary`, `background`, `card`, `stroke`,
`primary_text`, `background_text`, `graph`), a font and an optional logo.
`Theme.css_variables()` gives `--primary-color`, `--background-color`, `--card-color`,
`--stroke`, `--primary-text`, `--background-text`, `--graph-0` to `--graph-9`,
`--heading-font-family`, `--body-font-family`. Layouts read those, with their own colours as
fallback, so one theme restyles every template. `defaults.theme` applies one to new decks.

## 6. Hooks

`chatppt/hooks.py`. Plain functions in `<data>/hooks.py`: `before_outline(request)`,
`after_slide(slide)`, `before_export(deck)`, `after_export(path)`. Call sites use
`await run_hook(name, value)` (the outline generator uses the `@before_outline` decorator).
A hook returns a replacement or `None` (keep, possibly changed in place); one that raises is
logged and skipped. No plugin system: one file.

## 7. Auth

`chatppt/auth/`. Every request passes one middleware that sets a `Principal` (session, token,
basic, proxy, export or disabled). Routes that need a user or an admin depend on
`require_account` / `require_admin`; admin-only path prefixes are listed in `ADMIN_RULES`.
Policy and threat notes: [SECURITY.md](../SECURITY.md).
