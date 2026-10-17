"""Where the backend reaches the Next.js server from inside the container.

Stand-in with the same name and behaviour as the speed workstream's helper, so the
single-port layout (no nginx on :80) works on its own; whichever lands second keeps one copy.
"""

import os


def nextjs_base_url() -> str:
    """``CHATPPT_NEXTJS_URL`` (start.js sets it to the loopback public port), no trailing slash."""
    return (os.getenv("CHATPPT_NEXTJS_URL") or "http://127.0.0.1:3000").strip().rstrip("/")
