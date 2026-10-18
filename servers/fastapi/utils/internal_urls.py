"""Where the backend reaches the other in-container processes.

Loopback calls go straight to the process that answers them, never through a reverse
proxy, so they keep working when nothing listens on port 80.
"""

import os

DEFAULT_NEXTJS_URL = "http://127.0.0.1:3000"


def nextjs_base_url() -> str:
    """Base URL of the Next.js server (``CHATPPT_NEXTJS_URL``, default ``http://127.0.0.1:3000``)."""
    return (os.getenv("CHATPPT_NEXTJS_URL") or "").strip().rstrip("/") or DEFAULT_NEXTJS_URL
