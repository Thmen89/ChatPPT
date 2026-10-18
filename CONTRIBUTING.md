# Contributing to ChatPPT

Thanks for helping. ChatPPT aims to be simple, fast and customisable, so the best contributions
are small, focused, and leave the default lighter or faster than they found it.

## Run it locally

Prerequisites: Python 3.11, [uv](https://docs.astral.sh/uv/), Node.js LTS and npm.

Backend (FastAPI, port 8000):

```bash
cd servers/fastapi
uv sync
uv run python server.py --port 8000
```

Frontend (Next.js, port 3000), in a second terminal:

```bash
cd servers/nextjs
npm ci
NEXT_PUBLIC_FAST_API=http://127.0.0.1:8000 npm run dev
```

Or run the whole stack in one container: `docker build -t chatppt . && docker run -p 5000:5000 -v ./chatppt:/data chatppt`.

The desktop app lives in `electron/` (`npm run setup:env`, then `npm run dev`).

## Tests and checks

```bash
cd servers/fastapi && .venv/bin/python -m pytest tests/unit tests/regression -q
cd servers/nextjs && npx tsc --noEmit && npm run lint
```

`python scripts/bench/run.py` measures speed and footprint; include its numbers when a change
could affect either.

## Pull requests

- One concern per PR, with a short "before / after" description.
- Add or update tests for behaviour you change.
- Don't make the default heavier or slower, add a required service, or add a setting a new
  user has to understand.
- AI-assisted PRs are welcome; say so, and say how you tested.
- By contributing you agree your work is licensed under Apache-2.0.

See `docs/roadmap.md` for the plan and `docs/upstream.md` for how we track Presenton.
