#!/usr/bin/env python3
"""Prove ChatPPT starts and works with no network and phones nobody.

Two checks, both run by default:

static   Grep the tracked source for hosts that mean telemetry or a runtime download
         (mixpanel, sentry.io, presenton.ai, huggingface.co, ollama.com/install,
         googleapis.com). Any hit outside ALLOW fails. ALLOW is a ratchet: each entry
         says why it is there and who removes it; new hits are never allowed silently.

runtime  Start FastAPI and the Next.js standalone server inside a fresh network
         namespace (`unshare -rn`: loopback only, no route anywhere) with no provider
         configured, wait for both, call a few endpoints (auth status, icon search,
         themes, create presentation, template layouts, the home page), let it idle,
         then assert both processes are still up AND that no process even *tried* to
         reach a non-loopback address or DNS. Attempts are recorded with
         `strace -f -e trace=connect,sendto,sendmsg` on the whole process tree; in a
         namespace with no network an outbound call fails fast with ENETUNREACH, so
         readiness alone would hide it. strace makes the attempt itself the failure.
         Without strace the check still runs but can only prove "starts offline".

Usage:
  python3 scripts/check_offline.py                 # static + runtime
  python3 scripts/check_offline.py --static-only
  python3 scripts/check_offline.py --runtime-only [--settle 5] [--keep-tmp]

Needs (runtime): servers/fastapi/.venv (`uv sync`), the Next.js standalone build
(`npm run build` in servers/nextjs), `unshare` (util-linux), `ip` (iproute2), and
optionally `strace` (required with --require-strace, as CI uses).
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FASTAPI_DIR = REPO / "servers" / "fastapi"
NEXTJS_DIR = REPO / "servers" / "nextjs"
FASTAPI_PORT = 8000
NEXT_PORT = 3000
INNER_FLAG = "--_inside-netns"

# --------------------------------------------------------------------------- static

PATTERNS = {
    "mixpanel": r"mixpanel",
    "sentry.io": r"sentry\.io",
    "presenton.ai": r"presenton\.ai",
    "huggingface.co": r"huggingface\.co",
    "ollama.com/install": r"ollama\.com/install",
    "googleapis.com": r"googleapis\.com",
}

# (pattern or "*", path glob, reason). `*` in a glob also matches "/".
ALLOW: list[tuple[str, str, str]] = [
    ("*", "scripts/check_offline.py", "this check names the hosts it looks for"),
    ("*", "docs/*", "documentation says what is and is not contacted"),
    ("*", "NOTICE", "third-party licence texts name their projects"),
    ("*", "*package-lock.json", "npm registry metadata, not runtime code"),
    ("*", "*uv.lock", "PyPI metadata, not runtime code"),
    # Google Fonts: loaded by the *browser* when a deck/theme uses a web font. Not a
    # server call and not telemetry, but it is an outbound request; tracked here until
    # fonts ship in the image (templates: Agent E, theme UI: Agent H).
    ("googleapis.com", "servers/nextjs/app/presentation-templates/*", "template web fonts; Agent E"),
    ("googleapis.com", "servers/nextjs/app/(presentation-generator)/(dashboard)/theme/components/ThemePanel/*", "theme font picker; Agent H"),
    ("googleapis.com", "servers/fastapi/services/chat/memory_layer.py", "theme presets carry font URLs; Agent E"),
    ("googleapis.com", "servers/fastapi/templates/*", "PPTX import maps fonts to Google Fonts URLs; Agent E"),
    ("googleapis.com", "servers/fastapi/api/v1/ppt/endpoints/pptx_slides.py", "PPTX import font URLs; Agent E"),
    ("googleapis.com", "servers/fastapi/tests/*", "tests of the font helpers above"),
]


def static_check() -> bool:
    combined = "|".join(f"({p})" for p in PATTERNS.values())
    out = subprocess.run(
        ["git", "grep", "-I", "-n", "-i", "-E", combined, "--", "."],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    used: set[int] = set()
    bad: list[str] = []
    for line in out.splitlines():
        path, _, rest = line.partition(":")
        _, _, text = rest.partition(":")
        for key, rx in PATTERNS.items():
            if not re.search(rx, text, re.I):
                continue
            idx = next((i for i, (k, glob, _) in enumerate(ALLOW)
                        if k in ("*", key) and fnmatch.fnmatch(path, glob)), None)
            if idx is None:
                bad.append(f"  {key:<20} {path}: {text.strip()[:140]}")
            else:
                used.add(idx)
    stale = [f"  {k} {g}" for i, (k, g, _) in enumerate(ALLOW) if i not in used and k != "*"]
    if stale:
        print("static: allowlist entries that no longer match (remove them):\n" + "\n".join(stale))
    if bad:
        print(f"static: FAIL, {len(bad)} hit(s) outside the allowlist:\n" + "\n".join(bad))
        return False
    print(f"static: ok ({len(PATTERNS)} patterns, {len(used)} allowlist entries in use)")
    return True


# --------------------------------------------------------------------------- runtime

def standalone_dir() -> Path:
    """Next nests the standalone app under the workspace root it inferred (any lockfile
    above the app), so find its server.js rather than assume a depth."""
    root = NEXTJS_DIR / ".next-build" / "standalone"
    found = sorted((p for p in root.glob("**/server.js")
                    if "node_modules" not in p.parts and p.parent.name == "nextjs"),
                   key=lambda p: len(p.parts))
    if (root / "server.js").exists():
        return root
    return found[0].parent if found else root


def http(method: str, url: str, body: dict | None = None, auth: tuple[str, str] | None = None,
         timeout: float = 30) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_for(url: str, deadline: float, ok=(200,)) -> bool:
    while time.monotonic() < deadline:
        try:
            if http("GET", url, timeout=2)[0] in ok:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


SOCKADDR = re.compile(
    r"sa_family=(AF_INET6?)"
    r".*?(?:sin6?_port)=htons\((\d+)\)"
    r".*?(?:inet_addr\(\"([^\"]+)\"\)|inet_pton\(AF_INET6, \"([^\"]+)\")"
)


def outbound_attempts(strace_log: Path) -> list[str]:
    """Socket calls to anything but loopback, plus any DNS (port 53) even on loopback,
    since a stub resolver at 127.0.0.53 would otherwise hide a lookup."""
    hits = []
    if not strace_log.exists():
        return hits
    for line in strace_log.read_text(errors="replace").splitlines():
        m = SOCKADDR.search(line)
        if not m:
            continue
        port = int(m.group(2))
        addr = m.group(3) or m.group(4) or ""
        loopback = (addr.startswith("127.") or addr in ("::1", "0.0.0.0", "::")
                    or addr.startswith("::ffff:127."))
        if not loopback or port == 53:
            hits.append(line.strip()[:220])
    return hits


def runtime_inner(args: argparse.Namespace) -> bool:
    """Runs inside `unshare -rn`: bring up loopback, start the stack, exercise it."""
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    import socket
    try:
        socket.create_connection(("192.0.2.1", 80), timeout=2).close()
        print("runtime: FAIL, namespace has a route out; refusing to call this offline")
        return False
    except OSError:
        pass  # expected: no route

    python = FASTAPI_DIR / ".venv" / "bin" / "python"
    server_js = standalone_dir() / "server.js"
    for need, hint in ((python, "uv sync in servers/fastapi"), (server_js, "npm run build in servers/nextjs")):
        if not need.exists():
            print(f"runtime: missing {need} ({hint})")
            return False
    sa = standalone_dir()
    for link, target in ((sa / "public", NEXTJS_DIR / "public"),
                         (sa / ".next-build" / "static", NEXTJS_DIR / ".next-build" / "static")):
        if not link.exists():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target, target_is_directory=True)

    tmp = Path(tempfile.mkdtemp(prefix="chatppt-offline-"))
    (tmp / "data").mkdir()
    user, password = "offline", "offline-check-password"
    # A clean environment: nothing inherited, so no provider key, proxy or
    # telemetry opt-out can leak in. This is what a fresh install looks like.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp),
        "LANG": "C.UTF-8",
        "APP_DATA_DIRECTORY": str(tmp / "data"),
        "TEMP_DIRECTORY": str(tmp / "tmp"),
        "USER_CONFIG_PATH": str(tmp / "data" / "userConfig.json"),
        "AUTH_USERNAME": user,
        "AUTH_PASSWORD": password,
        "NEXT_PUBLIC_FAST_API": f"http://127.0.0.1:{FASTAPI_PORT}",
        "FAST_API_INTERNAL_URL": f"http://127.0.0.1:{FASTAPI_PORT}",
        "NEXT_PUBLIC_URL": f"http://127.0.0.1:{NEXT_PORT}",
        "NODE_ENV": "production",
    }
    strace = shutil.which("strace")
    if args.require_strace and not strace:
        print("runtime: FAIL, strace is required (--require-strace) but not installed")
        return False
    procs: dict[str, subprocess.Popen] = {}
    logs: dict[str, Path] = {}
    traces: dict[str, Path] = {}

    def spawn(name: str, cmd: list[str], cwd: Path, extra: dict[str, str] | None = None) -> None:
        logs[name] = tmp / f"{name}.log"
        if strace:
            traces[name] = tmp / f"{name}.strace"
            cmd = [strace, "-f", "-qq", "-e", "trace=connect,sendto,sendmsg", "-o", str(traces[name]), *cmd]
        procs[name] = subprocess.Popen(cmd, cwd=cwd, env={**env, **(extra or {})},
                                       stdout=open(logs[name], "w"), stderr=subprocess.STDOUT,
                                       start_new_session=True)

    ok = True
    try:
        t0 = time.monotonic()
        spawn("fastapi", [str(python), "server.py", "--port", str(FASTAPI_PORT), "--reload", "false"], FASTAPI_DIR)
        spawn("nextjs", ["node", "server.js"], sa, {"HOSTNAME": "127.0.0.1", "PORT": str(NEXT_PORT)})
        deadline = time.monotonic() + args.timeout
        fa = f"http://127.0.0.1:{FASTAPI_PORT}"
        nx = f"http://127.0.0.1:{NEXT_PORT}"
        ready = {"fastapi": wait_for(f"{fa}/api/v1/auth/status", deadline),
                 "nextjs": wait_for(f"{nx}/", deadline, ok=(200, 307, 308))}
        for name, up in ready.items():
            if not up:
                print(f"runtime: FAIL, {name} not ready within {args.timeout}s")
                ok = False
        if ok:
            print(f"runtime: both servers answering after {time.monotonic() - t0:.1f}s, offline")
            auth = (user, password)
            checks = [
                ("GET", f"{fa}/api/v1/auth/status", None, None),
                ("GET", f"{fa}/api/v1/ppt/icons/search?query=growth%20chart&limit=1", None, auth),
                ("GET", f"{fa}/api/v1/ppt/themes/default", None, auth),
                ("POST", f"{fa}/api/v1/ppt/presentation/create",
                 {"content": "Offline check deck", "n_slides": 5, "language": "English"}, auth),
                ("GET", f"{nx}/api/template?group=general", None, None),
                ("GET", f"{nx}/", None, None),
            ]
            for method, url, body, a in checks:
                status, raw = http(method, url, body, a, timeout=60)
                good = status in ((200, 307, 308) if url == f"{nx}/" else (200,))
                print(f"  {'ok  ' if good else 'FAIL'} {status} {method} {url.split('127.0.0.1')[1]}")
                if not good:
                    print(f"       {raw[:300]!r}")
                    ok = False
            time.sleep(args.settle)  # let any background/first-run work happen
        for name, proc in procs.items():
            if proc.poll() is not None:
                print(f"runtime: FAIL, {name} exited with {proc.returncode}")
                ok = False
    finally:
        for proc in procs.values():
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(1)
        for proc in procs.values():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    if strace:
        for name, path in traces.items():
            hits = outbound_attempts(path)
            if hits:
                ok = False
                print(f"runtime: FAIL, {name} attempted {len(hits)} outbound connection(s):")
                print("\n".join(f"  {h}" for h in hits[:20]))
            else:
                print(f"runtime: {name} made no outbound connection attempt (strace)")
    else:
        print("runtime: strace not found; proved offline start only, not zero attempts")
    if not ok:
        for name, path in logs.items():
            print(f"--- {name} log (tail) ---")
            print("\n".join(path.read_text(errors="replace").splitlines()[-40:]))
    if args.keep_tmp:
        print(f"runtime: logs kept in {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def runtime_check(args: argparse.Namespace) -> bool:
    if not shutil.which("unshare"):
        print("runtime: unshare (util-linux) is required")
        return False
    cmd = ["unshare", "-rn", sys.executable, str(Path(__file__).resolve()), INNER_FLAG,
           "--settle", str(args.settle), "--timeout", str(args.timeout)]
    if args.keep_tmp:
        cmd.append("--keep-tmp")
    if args.require_strace:
        cmd.append("--require-strace")
    return subprocess.run(cmd).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--runtime-only", action="store_true")
    ap.add_argument("--settle", type=float, default=5.0, help="seconds to idle after the calls")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for readiness")
    ap.add_argument("--require-strace", action="store_true", help="fail if strace is missing (CI)")
    ap.add_argument("--keep-tmp", action="store_true")
    ap.add_argument(INNER_FLAG, dest="inner", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.inner:
        sys.exit(0 if runtime_inner(args) else 1)
    ok = True
    if not args.runtime_only:
        ok = static_check() and ok
    if not args.static_only:
        ok = runtime_check(args) and ok
    print("offline check: PASS" if ok else "offline check: FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
