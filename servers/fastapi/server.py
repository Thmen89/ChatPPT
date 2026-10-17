import argparse
import os

import uvicorn

from chatppt.settings import apply_to_environ, get_settings

# chatppt.toml / CHATPPT_* must reach the legacy env readers before the app is imported:
# some read at import time (the database engine reads DATABASE_URL when its module loads).
apply_to_environ(get_settings())

from api.main import app  # noqa: E402, F401  (keeps the app in the PyInstaller bundle)
from api.observability import uvicorn_log_config  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI server")
    parser.add_argument(
        "--port", type=int, required=True, help="Port number to run the server on"
    )
    parser.add_argument(
        "--reload", type=str, default="false", help="Reload the server on code changes"
    )
    args = parser.parse_args()
    reload = args.reload == "true"
    # Loopback only: the public port is Next.js, which forwards /api/v1, /app_data,
    # /static, /mcp and /docs here (see next.config.mjs).
    host = "127.0.0.1"

    # Bind asset/base URL generation to the active runtime port (same env name as Next/Electron).
    os.environ["NEXT_PUBLIC_FAST_API"] = f"http://{host}:{args.port}"

    uvicorn.run(
        "api.main:app",
        host=host,
        port=args.port,
        reload=reload,
        log_config=uvicorn_log_config(get_settings().server.log_level),
        access_log=False,
        # Longer than the proxy's idle keep-alive, so Next.js never reuses a pooled
        # connection that uvicorn has just closed (a sporadic "socket hang up").
        timeout_keep_alive=75,
    )
