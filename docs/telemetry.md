# Telemetry and network use

**ChatPPT sends nothing about you or your decks to anyone.** There is no analytics, no usage
tracking, no update ping and no crash reporting unless you turn them on. A fresh install with no
network and no provider starts and serves the app. CI proves it on every pull request with
`scripts/check_offline.py`, which runs the servers in a network namespace with no route
out and fails if any process even tries to connect (see "How it is checked").

## What leaves the machine, and when

| What | When | Where it goes |
|---|---|---|
| Your prompt, outline and slide text | When you generate, and only to the LLM provider **you** configured | That provider (`[llm]` in `chatppt.toml`) |
| Image prompts | When an image provider is configured and `features.images` is on | That image provider |
| Web fonts | When the browser renders a template or theme that uses a Google Font | `fonts.googleapis.com`, requested by your browser, not the server (being moved into the image) |
| Error reports | Only if you set `server.error_reporting_dsn` (legacy `SENTRY_DSN`) **and** install `sentry-sdk` | The Sentry-compatible endpoint **you** named. No PII unless `SENTRY_SEND_DEFAULT_PII=true`; no tracing unless `SENTRY_TRACES_SAMPLE_RATE` is set |
| Desktop update check | Only if `CHATPPT_FEATURES__UPDATE_CHECK=true` **and** `UPDATE_SERVER_URL` is set | The `version.json` URL **you** named; there is no default host |

## What was removed or turned off (compared with upstream Presenton)

- **Mixpanel** browser analytics with a hard-coded token, the "Usage analytics" settings and
  onboarding toggles, `/api/telemetry-status` and the `mixpanel-browser` dependency: deleted.
  `DISABLE_ANONYMOUS_TRACKING` no longer does anything.
- **Sentry in the desktop app** with a hard-coded DSN, on by default: deleted, along with the
  `@sentry/electron` dependency and the sourcemap upload script. The main process reports
  only if you set `SENTRY_DSN` and install `@sentry/electron` yourself.
- **Backend Sentry** defaulted to `send_default_pii=True` and full tracing: now PII off,
  tracing off, and nothing at all without a DSN.
- **Update checker** polled upstream's GitHub and linked to upstream's site: now off, with no
  default URL.
- **mem0 memory** (`features.memory`) is off by default. mem0's own PostHog telemetry is
  forced off (`MEM0_TELEMETRY=False`), and if the spaCy model is not installed, memory turns
  itself off with one warning instead of running `spacy download`.
- **Icon search** loads its embedding model from the local cache only (`HF_HUB_OFFLINE=1`).
  If the weights are missing it logs once and slides get placeholder icons; nothing is fetched.
- **Ollama** is no longer installed with `curl | sh` at container start. `START_OLLAMA=true`
  starts a binary already in the image; otherwise point `OLLAMA_URL` at a daemon.
- `next.config.mjs` no longer whitelists upstream's S3, R2 and Supabase hosts for image
  optimisation.

## Build time is different

Building an image or the desktop app downloads packages and model weights
(`servers/fastapi/scripts/warm_fastembed_cache.py`, add `--memory` for mem0's embedder). That
is the only place a download is allowed, and the result is baked in.

## How it is checked

`python3 scripts/check_offline.py` (CI: `.github/workflows/offline.yml`):

1. **Static:** greps tracked source for `mixpanel`, `sentry.io`, `presenton.ai`,
   `huggingface.co`, `ollama.com/install` and `googleapis.com`. Any hit outside a short,
   justified allowlist in the script fails the build, so a new tracker cannot sneak in.
2. **Runtime:** starts FastAPI and the Next.js server inside `unshare -rn` (loopback only),
   with an empty environment (no keys, no proxy, no opt-out flags), calls auth status, icon
   search, themes, create presentation, the template layouts and the home page, idles, then
   checks that both processes are still up. Every `connect`/`sendto`/`sendmsg` is recorded
   with `strace -f`; any attempt to reach a non-loopback address, or DNS, fails the check.
   Recording the attempt matters because in a namespace with no network an outbound call
   fails instantly and would otherwise go unnoticed.
