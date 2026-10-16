# Upstream: Presenton

ChatPPT is derived from [Presenton](https://github.com/presenton/presenton) (Apache-2.0),
forked at 0.8.7-beta. We keep Presenton's `LICENSE` and its notices in `NOTICE`, and credit it
in the README. This page says where we deliberately differ and how to bring upstream changes in.

## Where ChatPPT intentionally diverges

| Area | Presenton | ChatPPT |
|---|---|---|
| Name and branding | Presenton, presenton.ai, Discord, YouTube | ChatPPT; links point at this repository only |
| Session cookie | `presenton_session` | `chatppt_session` (old name still read for one release) |
| Env vars | `PRESENTON_*` | `CHATPPT_*` (old names still read for one release); config in `chatppt.toml`, see `docs/contracts.md` |
| Temp dir | `/tmp/presenton` | `/tmp/chatppt` |
| Template placeholder assets | hot-linked from Presenton's S3 bucket | served by Next.js from `servers/nextjs/public/` |
| fastembed model | committed to git (87 MB) | downloaded at image build (`scripts/warm_fastembed_cache.py`), ignored by git |
| Marketing | README banners, cloud/desktop promos, deploy buttons, funding, R2 release sync | removed |
| Desktop identifiers | `com.presenton.presenton`, Store identity | `io.github.thmen89.chatppt`; Store identity is `TODO(owner)` |
| Telemetry, size, speed, customisation | see `docs/roadmap.md` | the rebuild's workstreams |

Things we did **not** rename, to keep data and APIs compatible: database tables and columns,
API paths, `userConfig.json` keys, and the Electron `chatppt-runtime.json` manifests (renamed,
but only written and read by our own build scripts).

## Real upstream dependencies

- **`presenton/presenton-export`** release archives. The export runtime (Puppeteer plus a
  PyInstaller PPTX/PDF converter) is downloaded from
  `https://github.com/presenton/presenton-export/releases` by
  `scripts/sync-presentation-export.cjs` (Docker) and `electron/scripts/sync-export-runtime.cjs`
  (desktop). These URLs are intentional; they are not branding. Replacing or vendoring that
  runtime is the export-speed workstream's call.

## Porting upstream changes

```bash
git remote add upstream https://github.com/presenton/presenton
git fetch upstream
git log --oneline upstream/main -- servers/   # see what changed
git cherry-pick -x <sha>                       # bring in one fix, keeping the reference
```

- Prefer cherry-picking specific fixes over merging `upstream/main`; the trees have diverged.
- Expect conflicts on branding strings, deleted files and anything the rebuild rewrote.
  Resolve them in ChatPPT's favour and keep the upstream fix.
- Keep `-x` so the commit message records the upstream SHA.
- If a ported file adds new `Presenton` strings or `presenton.ai` links, rebrand them in the
  same PR: `grep -ri presenton` should only hit attribution.
