# bench

The scoreboard in `docs/roadmap.md` comes from here.

```bash
# one-time: build what the container ships
(cd servers/fastapi && uv sync)
(cd servers/nextjs && npm ci && npm run build)
NODE_USE_ENV_PROXY=1 node scripts/sync-presentation-export.cjs   # export runtime
(cd presentation-export && npm init -y && npm i sharp@^0.34.5 --include=optional --omit=dev --no-package-lock)

# measure
python scripts/bench/run.py                       # mock LLM, instant answers
python scripts/bench/run.py --latency-ms 800      # mock paced like a fast hosted model
python scripts/bench/run.py --real                # provider from your environment (LLM=..., keys)
python scripts/bench/run.py --repeat 3 --image ghcr.io/presenton/presenton:v0.8.7-beta
```

Needs `nginx` on `$PATH` and a Chromium at `PUPPETEER_EXECUTABLE_PATH` (default
`/usr/bin/chromium`). Ports 80, 3000, 8000, 8001 and 9900 must be free. Results go to
`bench-results.json` and a markdown table on stdout.

`mock_llm.py` is also usable on its own (`LLM=custom CUSTOM_LLM_URL=http://127.0.0.1:9900/v1`):
it returns a valid instance of any JSON schema it is asked for, so CI needs no keys.
