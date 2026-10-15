#!/usr/bin/env python3
"""Mock OpenAI-compatible LLM server for benchmarks and CI.

Speaks enough of the Chat Completions API for ChatPPT's `custom` provider:

* ``GET  /v1/models``                — one model, ``mock``
* ``POST /v1/chat/completions``      — streaming or not; when the request carries
  ``response_format.type == "json_schema"`` the reply is a valid instance of that
  schema, otherwise a short paragraph of text
* ``GET  /stats`` / ``POST /stats/reset`` — request count and approximate
  prompt/completion tokens since the last reset (what the bench reports as
  "tokens per deck")

Deterministic (seeded) and dependency-free (stdlib only), so CI needs no keys.

Environment:
  MOCK_LLM_PORT         port to listen on (default 9900)
  MOCK_LLM_LATENCY_MS   fixed delay per request, to imitate a real provider
                        (default 0 = measure only ChatPPT's own overhead)
  MOCK_LLM_TOKENS_PER_S when streaming, pace output at this rate (0 = no pacing)
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("MOCK_LLM_PORT", "9900"))
LATENCY_S = int(os.getenv("MOCK_LLM_LATENCY_MS", "0")) / 1000
TOKENS_PER_S = float(os.getenv("MOCK_LLM_TOKENS_PER_S", "0"))

WORDS = (
    "alpha beta gamma delta growth margin revenue pipeline capital quarter "
    "market signal risk return yield allocation strategy momentum liquidity "
    "position hedge forecast outlook model data insight summary metric trend"
).split()

_stats_lock = threading.Lock()
_stats = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "stream_requests": 0}


def approx_tokens(text: str) -> int:
    # Close enough for a scoreboard: ~4 characters per token.
    return max(1, len(text) // 4)


class SchemaFiller:
    """Produce an instance of a JSON Schema that satisfies its constraints."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.depth = 0

    def words(self, min_len: int, max_len: int) -> str:
        if max_len < 1:
            return ""
        out = ""
        target = self.rng.randint(min(min_len, max_len), max_len)
        while len(out) < target:
            w = self.rng.choice(WORDS)
            candidate = f"{out} {w}".strip()
            if len(candidate) > max_len:
                break
            out = candidate
        if len(out) < min_len:
            out = (out + " " + "x" * min_len)[:max_len].rstrip() or "x" * min_len
            if len(out) < min_len:
                out = out + "x" * (min_len - len(out))
        return out or "x" * max(1, min_len)

    def fill(self, schema: dict, root: dict | None = None, key: str | None = None):
        root = root if root is not None else schema
        if not isinstance(schema, dict):
            return None
        if "$ref" in schema:
            return self.fill(self.resolve(schema["$ref"], root), root, key)
        for combo in ("anyOf", "oneOf", "allOf"):
            if combo in schema and schema[combo]:
                options = [o for o in schema[combo] if o.get("type") != "null"] or schema[combo]
                return self.fill(options[0], root, key)
        if "const" in schema:
            return schema["const"]
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]
        t = schema.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), t[0])
        if t == "object" or "properties" in schema:
            return self.fill_object(schema, root)
        if t == "array":
            return self.fill_array(schema, root, key)
        if t == "integer":
            lo = schema.get("minimum", 0)
            hi = schema.get("maximum", max(lo, 9))
            return self.rng.randint(int(lo), int(hi))
        if t == "number":
            lo = float(schema.get("minimum", 0))
            hi = float(schema.get("maximum", max(lo + 1, 100)))
            return round(self.rng.uniform(lo, hi), 1)
        if t == "boolean":
            return True
        if t == "null":
            return None
        return self.fill_string(schema, key)

    def resolve(self, ref: str, root: dict):
        node = root
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return node

    def fill_object(self, schema: dict, root: dict) -> dict:
        self.depth += 1
        out = {}
        props = schema.get("properties", {})
        required = set(schema.get("required", props.keys()))
        for name, sub in props.items():
            if name in required or self.depth < 4:
                out[name] = self.fill(sub, root, name)
        self.depth -= 1
        return out

    def fill_array(self, schema: dict, root: dict, key: str | None) -> list:
        lo = int(schema.get("minItems", 1))
        hi = int(schema.get("maxItems", max(lo, 3)))
        n = lo if lo == hi else min(hi, max(lo, 3))
        items = schema.get("items", {"type": "string"})
        if isinstance(items, list):
            return [self.fill(s, root, key) for s in items[:n]]
        return [self.fill(items, root, key) for _ in range(n)]

    def fill_string(self, schema: dict, key: str | None) -> str:
        fmt = schema.get("format")
        if fmt in ("uri", "url") or (key and key.endswith("_url__")):
            return "https://example.com/" + uuid.uuid4().hex[:8]
        if fmt == "date":
            return "2026-01-01"
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        lo = int(schema.get("minLength", 1))
        hi = int(schema.get("maxLength", max(lo + 20, 60)))
        default = schema.get("default")
        # Real models echo the schema's example text; keep it only when it is actually valid.
        if isinstance(default, str) and lo <= len(default) <= hi:
            return default
        if key == "content" and lo >= 100:
            # Outline slide: markdown with a title, like the real model is told to write.
            body = self.words(max(1, lo - 20), hi - 20)
            return f"## {self.words(8, 40)}\n\n{body}"[:hi]
        return self.words(lo, hi)


def build_reply(body: dict) -> str:
    seed = sum(len(json.dumps(m.get("content", ""))) for m in body.get("messages", []))
    rf = body.get("response_format") or {}
    if rf.get("type") == "json_schema":
        schema = rf.get("json_schema", {}).get("schema", {})
        return json.dumps(SchemaFiller(seed).fill(schema), ensure_ascii=False)
    if rf.get("type") == "json_object":
        return json.dumps({"result": SchemaFiller(seed).words(20, 120)})
    return SchemaFiller(seed).words(40, 300)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:  # quiet
        pass

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/v1/models") or self.path == "/models":
            return self._json(200, {"object": "list", "data": [{"id": "mock", "object": "model", "owned_by": "chatppt"}]})
        if self.path == "/stats":
            with _stats_lock:
                return self._json(200, dict(_stats))
        if self.path in ("/", "/healthz"):
            return self._json(200, {"ok": True})
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path == "/stats/reset":
            with _stats_lock:
                for k in _stats:
                    _stats[k] = 0
            return self._json(200, {"ok": True})
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": f"unsupported path {self.path}"})
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        if LATENCY_S:
            time.sleep(LATENCY_S)
        reply = build_reply(body)
        prompt_text = json.dumps(body.get("messages", []))
        with _stats_lock:
            _stats["requests"] += 1
            _stats["prompt_tokens"] += approx_tokens(prompt_text)
            _stats["completion_tokens"] += approx_tokens(reply)
            if body.get("stream"):
                _stats["stream_requests"] += 1

        usage = {
            "prompt_tokens": approx_tokens(prompt_text),
            "completion_tokens": approx_tokens(reply),
            "total_tokens": approx_tokens(prompt_text) + approx_tokens(reply),
        }
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = body.get("model") or "mock"
        if body.get("stream"):
            return self._stream(cid, model, reply, usage)
        self._json(200, {
            "id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": reply}}],
            "usage": usage,
        })

    def _stream(self, cid: str, model: str, reply: str, usage: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(obj) -> None:
            line = f"data: {json.dumps(obj)}\n\n".encode()
            self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.flush()

        base = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
        send({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]})
        step = 24
        for i in range(0, len(reply), step):
            send({**base, "choices": [{"index": 0, "delta": {"content": reply[i:i + step]}, "finish_reason": None}]})
            if TOKENS_PER_S:
                time.sleep(approx_tokens(reply[i:i + step]) / TOKENS_PER_S)
        send({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage})
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode() + done + b"\r\n0\r\n\r\n")
        self.wfile.flush()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"mock llm listening on http://127.0.0.1:{PORT}/v1 (latency {LATENCY_S*1000:.0f} ms)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
