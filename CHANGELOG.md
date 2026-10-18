# Changelog

All notable changes to ChatPPT. ChatPPT started as a fork of
[Presenton](https://github.com/presenton/presenton) 0.8.7-beta.

## Unreleased

The lean rebuild.

- Architecture notes, roadmap scoreboard and benchmark harness (`scripts/bench/`). (#1)
- Shared contracts: `chatppt.toml` settings, templates as folders, prompts as files,
  provider registry and per-step model routing. (#2)
- Strip and rebrand: renamed to ChatPPT; removed committed build artifacts (fastembed model
  cache, `.coverage`, `tsconfig.tsbuildinfo`) and upstream marketing assets; new logo and
  icons; built-in templates no longer load placeholder icons and images from Presenton's S3
  bucket; minimal README, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT and `docs/upstream.md`.
  - Session cookie is now `chatppt_session`; `presenton_session` is still accepted for one
    release.
  - `CHATPPT_FASTEMBED_ICON_CACHE_DIR`, `CHATPPT_APP_ROOT`, `CHATPPT_HOST_HTTP_PORT`,
    `CHATPPT_CHROMIUM_CACHE_RECOVERY` and the Electron build `CHATPPT_*` variables replace
    their `PRESENTON_*` names; the old names are still read for one release.
  - Default temp directory is `/tmp/chatppt`.
- Zero telemetry and offline start: the bundled product analytics and the built-in Sentry DSN are removed; error
  reporting is opt-in via `server.error_reporting_dsn`; the desktop update check is off by
  default; chat memory (mem0) is off by default; nothing is downloaded at runtime (icon and
  memory models are baked in at build time); `docs/telemetry.md` says what is sent. (#4)
- Wave 1 follow-ups: Next.js export reads `CHATPPT_APP_ROOT` first (the desktop app now sets
  that name); NOTICE rebuilds keep the attribution header.
