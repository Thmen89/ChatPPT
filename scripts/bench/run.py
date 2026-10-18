#!/usr/bin/env python3
"""ChatPPT benchmark: the scoreboard numbers, measured end to end.

Starts the full stack the way the container does (``node start.js``: Next.js on the
public port :5000 in that process, FastAPI on 127.0.0.1:8000 as its child, MCP inside
FastAPI), in a throwaway copy of the image's /app layout, points it at the mock LLM
(``scripts/bench/mock_llm.py``) or at a real provider, then measures:

  cold start          first 200 from FastAPI, Next.js and the public /healthz after spawn
  idle RAM            RSS of every process in the stack after it settles
  outline             POST create + SSE outline stream (what the UI does first)
  time to first slide prepare + first slide chunk on the presentation stream
  time to full deck   the stream's ``complete`` event
  PPTX export         POST /api/export-presentation (Chromium + converter)
  API deck            POST /api/v1/ppt/presentation/generate (outline → export in one call)
  tokens per deck     approximate prompt + completion tokens the mock LLM saw
  image size          compressed size of a container image (``--image REF``)

Usage:
  python scripts/bench/run.py                       # mock LLM, 10 slides
  python scripts/bench/run.py --latency-ms 800      # mock paced like a fast hosted model
  python scripts/bench/run.py --real                # provider from your environment
  python scripts/bench/run.py --image <image>  # e.g. the upstream ghcr.io/presenton/presenton:v0.8.7-beta for comparison

Requires: the Next.js build (``npm run build`` in servers/nextjs), the FastAPI
venv (``uv sync``), the presentation-export runtime and a Chromium at
``PUPPETEER_EXECUTABLE_PATH``. Nothing here needs network access with the mock.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FASTAPI_DIR = REPO / "servers" / "fastapi"
NEXTJS_DIR = REPO / "servers" / "nextjs"

def _standalone_dir() -> Path:
    """Next's standalone output nests under the workspace root when a lockfile sits above the app."""
    root = NEXTJS_DIR / ".next-build" / "standalone"
    for candidate in (root, root / "servers" / "nextjs"):
        if (candidate / "server.js").exists():
            return candidate
    return root


STANDALONE_DIR = _standalone_dir()
EXPORT_DIR = REPO / "presentation-export"

MOCK_PORT = 9900
PUBLIC_PORT = 5000  # start.js serves Next.js here and forwards the API to FastAPI
FASTAPI_PORT = 8000

PROMPT = (
    "A 10-slide investment memo on a mid-cap European industrial automation company: "
    "thesis, market, unit economics, competition, risks, valuation, catalysts, exit."
)


# ----------------------------------------------------------------------------- helpers

def http(method: str, url: str, body: dict | None = None, timeout: float = 600, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from None


def sse(url: str, on_event, timeout: float = 900) -> None:
    """Consume a text/event-stream, calling on_event(dict) for every ``data:`` line."""
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    try:
                        on_event(json.loads(payload))
                    except json.JSONDecodeError:
                        pass


def wait_for(url: str, deadline: float, ok=(200,)) -> float | None:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status in ok:
                    return time.monotonic()
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return time.monotonic()
        except Exception:
            pass
        time.sleep(0.05)
    return None


def rss_tree(root_pids: list[int]) -> dict[int, int]:
    """RSS in bytes for every process under the given roots (inclusive)."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                stat = f.read()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            children.setdefault(ppid, []).append(int(entry))
        except Exception:
            continue
    out: dict[int, int] = {}
    stack = list(root_pids)
    while stack:
        pid = stack.pop()
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        out[pid] = int(line.split()[1]) * 1024
                        break
        except Exception:
            pass
        stack.extend(children.get(pid, []))
    return out


def proc_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
    except OSError:
        return "?"
    if comm.startswith("python"):
        return "python"
    # Next.js renames its process title to "next-server (vX)"; it is start.js's node.
    return "node" if comm.startswith("next-server") else comm


def mb(n: float) -> float:
    return round(n / 1e6, 1)


def image_compressed_size(ref: str) -> float | None:
    try:
        raw = subprocess.run(["docker", "buildx", "imagetools", "inspect", ref, "--raw"],
                             capture_output=True, text=True, check=True, timeout=120).stdout
        manifest = json.loads(raw)
        if "manifests" in manifest:  # index: take the first linux/amd64 entry
            for m in manifest["manifests"]:
                plat = m.get("platform", {})
                if plat.get("os") == "linux" and plat.get("architecture") == "amd64":
                    return image_compressed_size(f"{ref.split('@')[0]}@{m['digest']}")
            return None
        return sum(l["size"] for l in manifest["layers"])
    except Exception:
        return None


# ----------------------------------------------------------------------------- stack

class Stack:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.procs: dict[str, subprocess.Popen] = {}
        self.tmp = Path(tempfile.mkdtemp(prefix="chatppt-bench-"))
        self.app_data = self.tmp / "app_data"
        self.app_data.mkdir()
        self.logs = self.tmp / "logs"
        self.logs.mkdir()

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM", "CUSTOM_", "OPENAI_", "ANTHROPIC_", "GOOGLE_"))} \
            if not self.args.real else dict(os.environ)
        env.update({
            "APP_DATA_DIRECTORY": str(self.app_data),
            "TEMP_DIRECTORY": str(self.tmp / "tmp"),
            "USER_CONFIG_PATH": str(self.app_data / "userConfig.json"),
            "CAN_CHANGE_KEYS": "false",
            "DISABLE_AUTH": "true",
            "DISABLE_IMAGE_GENERATION": env.get("DISABLE_IMAGE_GENERATION", "true"),
            "NEXT_TELEMETRY_DISABLED": "1",
            "NODE_ENV": "production",
            "PORT": str(PUBLIC_PORT),
            "CHATPPT_PYTHON": str(FASTAPI_DIR / ".venv" / "bin" / "python"),
            "EXPORT_RUNTIME_DIR": str(EXPORT_DIR),
            "EXPORT_PACKAGE_ROOT": str(EXPORT_DIR),
            "BUILT_PYTHON_MODULE_PATH": str(EXPORT_DIR / "py" / "convert-linux-x64"),
            "CHATPPT_APP_ROOT": str(REPO),
            "PUPPETEER_EXECUTABLE_PATH": env.get("PUPPETEER_EXECUTABLE_PATH", "/usr/bin/chromium"),
        })
        if not self.args.real:
            env.update({
                "LLM": "custom",
                "CUSTOM_LLM_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
                "CUSTOM_LLM_API_KEY": "mock",
                "CUSTOM_MODEL": "mock",
            })
        return env

    def spawn(self, name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
        log = open(self.logs / f"{name}.log", "w")
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        self.procs[name] = proc
        return proc

    def start_mock(self) -> None:
        env = dict(os.environ, MOCK_LLM_PORT=str(MOCK_PORT),
                   MOCK_LLM_LATENCY_MS=str(self.args.latency_ms))
        self.spawn("mock_llm", [sys.executable, str(REPO / "scripts" / "bench" / "mock_llm.py")], REPO, env)
        if wait_for(f"http://127.0.0.1:{MOCK_PORT}/healthz", time.monotonic() + 10) is None:
            raise SystemExit("mock LLM did not start")

    def start(self) -> dict:
        env = self.env()
        python = FASTAPI_DIR / ".venv" / "bin" / "python"
        if not python.exists():
            raise SystemExit(f"missing {python}; run `uv sync` in servers/fastapi")
        server_js = STANDALONE_DIR / "server.js"
        if not server_js.exists():
            raise SystemExit("missing Next.js standalone build; run `npm run build` in servers/nextjs")
        # The standalone server expects public/ and the static chunks next to it, as in the Dockerfile.
        for link, target in ((STANDALONE_DIR / "public", NEXTJS_DIR / "public"),
                             (STANDALONE_DIR / ".next-build" / "static", NEXTJS_DIR / ".next-build" / "static")):
            if not link.exists():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target, target_is_directory=True)

        # The image's /app layout: start.js + banner, servers/fastapi, and the Next.js
        # standalone build at servers/nextjs (start.js imports its server.js).
        app = self.tmp / "app"
        (app / "scripts").mkdir(parents=True)
        (app / "servers").mkdir()
        shutil.copy(REPO / "start.js", app)
        shutil.copy(REPO / "package.json", app)  # "type": "module"
        for name in ("chatppt-banner.mjs", "chatppt-ascii.txt"):
            shutil.copy(REPO / "scripts" / name, app / "scripts")
        (app / "servers" / "fastapi").symlink_to(FASTAPI_DIR, target_is_directory=True)
        (app / "servers" / "nextjs").symlink_to(STANDALONE_DIR, target_is_directory=True)

        t0 = time.monotonic()
        # Same command as the Dockerfile's CMD.
        self.spawn("chatppt", ["node", "--max-semi-space-size=1", str(app / "start.js")], app, env)

        deadline = time.monotonic() + 120
        ready = {
            "fastapi": wait_for(f"http://127.0.0.1:{FASTAPI_PORT}/healthz", deadline),
            "nextjs": wait_for(f"http://127.0.0.1:{PUBLIC_PORT}/", deadline, ok=(200, 307, 308)),
            "public": wait_for(f"http://127.0.0.1:{PUBLIC_PORT}/api/v1/auth/status", deadline),
        }
        for name, t in ready.items():
            if t is None:
                raise SystemExit(f"{name} did not become ready; see {self.logs}/chatppt.log")
        return {f"cold_start_{k}_s": round(v - t0, 2) for k, v in ready.items()} | {
            "cold_start_s": round(max(ready.values()) - t0, 2)}

    def idle_ram(self) -> dict:
        time.sleep(self.args.settle)
        by_group: dict[str, int] = {}
        for name, proc in self.procs.items():
            if name == "mock_llm":
                continue
            # Every process under start.js, named by what it runs: node (start.js with
            # Next.js in-process) and python (FastAPI with MCP inside).
            for pid, rss in rss_tree([proc.pid]).items():
                label = {"node": "nextjs", "python": "fastapi"}.get(proc_name(pid), proc_name(pid))
                by_group[label] = by_group.get(label, 0) + rss
        return {"idle_ram_mb": mb(sum(by_group.values())),
                "idle_ram_by_process_mb": {k: mb(v) for k, v in by_group.items()}}

    def stop(self) -> None:
        for name, proc in reversed(list(self.procs.items())):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(1)
        for proc in self.procs.values():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if not self.args.keep_tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- flows

def mock_stats(reset: bool = False) -> dict:
    if reset:
        http("POST", f"http://127.0.0.1:{MOCK_PORT}/stats/reset", {})
    return http("GET", f"http://127.0.0.1:{MOCK_PORT}/stats") or {}


def ui_flow(base: str, n_slides: int, template: str, export: bool, want_tokens: bool) -> dict:
    """The clicks a user makes: create → outline → prepare → stream → export."""
    r: dict = {}
    if want_tokens:
        mock_stats(reset=True)

    t0 = time.monotonic()
    created = http("POST", f"{base}/api/v1/ppt/presentation/create",
                   {"content": PROMPT, "n_slides": n_slides, "language": "English"})
    pid = created["id"]
    outline: dict = {}

    def on_outline(ev):
        if ev.get("type") == "complete":
            outline.update(ev["presentation"])
        elif ev.get("type") == "error":
            raise SystemExit(f"outline stream error: {ev.get('detail')}")

    sse(f"{base}/api/v1/ppt/outlines/stream/{pid}", on_outline)
    r["outline_s"] = round(time.monotonic() - t0, 2)

    t1 = time.monotonic()
    layout = http("GET", f"{base}/api/template?group={template}")
    r["layout_fetch_s"] = round(time.monotonic() - t1, 2)

    t2 = time.monotonic()
    http("POST", f"{base}/api/v1/ppt/presentation/prepare", {
        "presentation_id": pid, "outlines": outline["outlines"]["slides"],
        "layout": layout, "title": outline.get("title")})
    r["prepare_s"] = round(time.monotonic() - t2, 2)

    first = {"t": None, "n": 0}

    def on_slide(ev):
        kind = ev.get("type")
        chunk = ev.get("chunk", "") if kind == "chunk" else ""
        if kind == "chunk" and chunk.strip() not in ('{ "slides": [', '] }', ''):
            first["n"] += 1
            if first["t"] is None:
                first["t"] = time.monotonic()
        elif kind == "error":
            raise SystemExit(f"presentation stream error: {ev.get('detail')}")

    sse(f"{base}/api/v1/ppt/presentation/stream/{pid}", on_slide)
    t3 = time.monotonic()
    r["first_slide_after_outline_s"] = round((first["t"] or t3) - t2, 2)
    r["full_deck_after_outline_s"] = round(t3 - t2, 2)
    r["full_deck_total_s"] = round(t3 - t0, 2)
    r["slides_streamed"] = first["n"]

    if export:
        t4 = time.monotonic()
        try:
            res = http("POST", f"{base}/api/export-presentation",
                       {"format": "pptx", "id": pid, "title": outline.get("title") or "bench"})
            r["pptx_export_s"] = round(time.monotonic() - t4, 2)
            r["pptx_path"] = res.get("path") if isinstance(res, dict) else None
        except RuntimeError as e:
            r["pptx_export_s"] = None
            r["pptx_export_error"] = str(e)
            print(f"  export failed: {e}", flush=True)
    if want_tokens:
        s = mock_stats()
        r["llm_requests"] = s["requests"]
        r["tokens_per_deck"] = s["prompt_tokens"] + s["completion_tokens"]
        r["prompt_tokens"] = s["prompt_tokens"]
        r["completion_tokens"] = s["completion_tokens"]
    return r


def api_flow(base: str, n_slides: int, template: str, want_tokens: bool) -> dict:
    """One call, as a script or the MCP server would do it."""
    if want_tokens:
        mock_stats(reset=True)
    t0 = time.monotonic()
    try:
        res = http("POST", f"{base}/api/v1/ppt/presentation/generate", {
            "content": PROMPT, "n_slides": n_slides, "template": template,
            "language": "English", "export_as": "pptx"})
        out = {"api_deck_pptx_s": round(time.monotonic() - t0, 2), "api_path": res.get("path")}
    except RuntimeError as e:
        out = {"api_deck_pptx_s": None, "api_error": str(e)}
        print(f"  api flow failed: {e}", flush=True)
    if want_tokens:
        s = mock_stats()
        out["api_tokens_per_deck"] = s["prompt_tokens"] + s["completion_tokens"]
        out["api_llm_requests"] = s["requests"]
    return out


def median_of(runs: list[dict]) -> dict:
    out: dict = {}
    for key in runs[0]:
        vals = [r[key] for r in runs if isinstance(r.get(key), (int, float))]
        if len(vals) == len(runs):
            out[key] = round(statistics.median(vals), 2)
        else:
            out[key] = runs[-1][key]
    return out


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="store_true", help="use the LLM provider from the environment instead of the mock")
    ap.add_argument("--latency-ms", type=int, default=0, help="mock LLM latency per request")
    ap.add_argument("--slides", type=int, default=10)
    ap.add_argument("--template", default="general")
    ap.add_argument("--repeat", type=int, default=1, help="repeat the deck flows and report medians")
    ap.add_argument("--skip-export", action="store_true")
    ap.add_argument("--skip-api", action="store_true")
    ap.add_argument("--settle", type=float, default=5.0, help="seconds to wait before sampling idle RAM")
    ap.add_argument("--image", action="append", default=[], help="container image ref to size (repeatable)")
    ap.add_argument("--out", default="bench-results.json")
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    stack = Stack(args)
    results: dict = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
        "provider": "real" if args.real else f"mock (latency {args.latency_ms} ms)",
        "slides": args.slides, "template": args.template,
    }
    try:
        if not args.real:
            stack.start_mock()
        print("starting stack...", flush=True)
        results.update(stack.start())
        print(f"cold start {results['cold_start_s']} s", flush=True)
        results.update(stack.idle_ram())
        print(f"idle RAM {results['idle_ram_mb']} MB {results['idle_ram_by_process_mb']}", flush=True)

        base = f"http://127.0.0.1:{PUBLIC_PORT}"
        ui_runs, api_runs = [], []
        for i in range(args.repeat):
            print(f"ui flow {i + 1}/{args.repeat}...", flush=True)
            ui_runs.append(ui_flow(base, args.slides, args.template, not args.skip_export, not args.real))
            print(f"  {ui_runs[-1]}", flush=True)
            if not args.skip_api:
                print(f"api flow {i + 1}/{args.repeat}...", flush=True)
                api_runs.append(api_flow(base, args.slides, args.template, not args.real))
                print(f"  {api_runs[-1]}", flush=True)
        results["ui"] = median_of(ui_runs)
        if api_runs:
            results["api"] = median_of(api_runs)
        results["busy_ram_peak_hint_mb"] = mb(sum(sum(rss_tree([p.pid]).values())
                                                 for n, p in stack.procs.items() if n != "mock_llm"))
    finally:
        stack.stop()

    for ref in args.image:
        size = image_compressed_size(ref)
        results.setdefault("images", {})[ref] = {"compressed_mb": mb(size) if size else None}

    Path(args.out).write_text(json.dumps(results, indent=2))
    print_table(results)
    print(f"\nwrote {args.out}")


def print_table(r: dict) -> None:
    ui, api = r.get("ui", {}), r.get("api", {})
    rows = [
        ("Cold start (all ready)", f"{r.get('cold_start_s')} s"),
        ("Idle RAM (whole stack)", f"{r.get('idle_ram_mb')} MB"),
        ("Outline (create + stream)", f"{ui.get('outline_s')} s"),
        ("Time to first slide (after outline)", f"{ui.get('first_slide_after_outline_s')} s"),
        ("Time to full deck (after outline)", f"{ui.get('full_deck_after_outline_s')} s"),
        ("Time to full deck (prompt → editor)", f"{ui.get('full_deck_total_s')} s"),
        ("PPTX export", f"{ui.get('pptx_export_s')} s"),
        ("API deck incl. PPTX", f"{api.get('api_deck_pptx_s')} s"),
        ("LLM requests per deck (UI / API)", f"{ui.get('llm_requests')} / {api.get('api_llm_requests')}"),
        ("Tokens per deck (UI / API)", f"{ui.get('tokens_per_deck')} / {api.get('api_tokens_per_deck')}"),
    ]
    for ref, info in r.get("images", {}).items():
        rows.append((f"Image {ref} (compressed)", f"{info['compressed_mb']} MB"))
    print(f"\n| Metric | {r['provider']}, {r['slides']} slides, {r['template']} |\n|---|---|")
    for k, v in rows:
        print(f"| {k} | {v} |")


if __name__ == "__main__":
    main()
