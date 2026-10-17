"""In-process rate limits (no Redis): a sliding window of timestamps per key.

Login failures are counted per username and per client, token creation per user. One
FastAPI process serves an install, so process memory is the right place; a restart resets
the counters, which is fine for slowing down guessing.
"""

from __future__ import annotations

import threading
import time
from collections import deque

MAX_KEYS = 10_000


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again (0 means it may now)."""
        now = time.monotonic()
        with self._lock:
            hits = self._trim(key, now)
            if len(hits) < self.limit:
                return 0
            return max(1, int(hits[0] + self.window - now) + 1)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= MAX_KEYS:
                self._prune(now)
            self._trim(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            del self._hits[key]
        if len(self._hits) >= MAX_KEYS:  # still full: drop the oldest half
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[: MAX_KEYS // 2]:
                del self._hits[key]


# Failed sign-ins: 10 per username and 30 per client in 15 minutes.
LOGIN_FAILURES_PER_USER = SlidingWindow(10, 15 * 60)
LOGIN_FAILURES_PER_CLIENT = SlidingWindow(30, 15 * 60)
# New API tokens and first-admin setup attempts.
TOKEN_CREATION = SlidingWindow(20, 60 * 60)


def reset_all() -> None:
    for limiter in (LOGIN_FAILURES_PER_USER, LOGIN_FAILURES_PER_CLIENT, TOKEN_CREATION):
        limiter.clear()
