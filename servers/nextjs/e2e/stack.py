#!/usr/bin/env python3
"""Run the full ChatPPT stack on mock providers until SIGTERM, for the Playwright e2e test.

Reuses the benchmark's ``Stack`` (scripts/bench/run.py): ``node start.js`` as in the
container (Next.js on :5000 forwarding the API to FastAPI on 127.0.0.1:8000, MCP inside
FastAPI), mock LLM :9900, auth disabled, a throwaway data folder. On top of
that, image generation is switched on and pointed at the mock's PNG endpoint, so the flow
covers image assets too.

Needs what the bench needs: the FastAPI venv, the Next.js standalone build, the
presentation-export runtime and a Chromium at PUPPETEER_EXECUTABLE_PATH.
Logs go to $E2E_LOGS_DIR (default: a temp dir, printed on start).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "bench"))

import run  # noqa: E402
from run import MOCK_PORT, Stack  # noqa: E402

# Next nests the standalone output under the outermost lockfile's directory, which is
# deeper than run.py expects inside a git worktree. Find server.js wherever it landed.
if not (run.STANDALONE_DIR / "server.js").exists():
    found = sorted((run.NEXTJS_DIR / ".next-build" / "standalone").glob("**/servers/nextjs/server.js"))
    if found:
        run.STANDALONE_DIR = found[0].parent


class E2EStack(Stack):
    def __init__(self) -> None:
        super().__init__(argparse.Namespace(real=False, latency_ms=0, keep_tmp=False, settle=0))
        if logs := os.environ.get("E2E_LOGS_DIR"):
            self.logs = Path(logs)
            self.logs.mkdir(parents=True, exist_ok=True)

    def env(self) -> dict[str, str]:
        env = super().env()
        env.update(
            {
                "DISABLE_IMAGE_GENERATION": "false",
                "IMAGE_PROVIDER": "openai_compatible",
                "OPENAI_COMPAT_IMAGE_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
                "OPENAI_COMPAT_IMAGE_API_KEY": "mock",
                "OPENAI_COMPAT_IMAGE_MODEL": "mock",
            }
        )
        return env


def main() -> None:
    # Stream like a real provider, not instantly: the UI gates actions on streams finishing,
    # and an instant mock hides races that a slower machine exposes.
    os.environ.setdefault("MOCK_LLM_TOKENS_PER_S", "150")
    stack = E2EStack()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        stack.start_mock()
        timings = stack.start()
        print(f"stack ready in {timings['cold_start_s']} s; logs in {stack.logs}", flush=True)
        while all(p.poll() is None for p in stack.procs.values()):
            time.sleep(1)
        dead = [name for name, p in stack.procs.items() if p.poll() is not None]
        sys.exit(f"stack process exited: {', '.join(dead)}; see {stack.logs}")
    finally:
        stack.stop()


if __name__ == "__main__":
    main()
