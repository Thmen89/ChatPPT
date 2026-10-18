from utils.simple_auth import get_internal_auth_headers


def internal_request_headers() -> dict[str, str]:
    """Headers for trusted loopback calls between FastAPI and Next.js (a read-only token,
    as both ``Authorization`` and the session cookie Next.js's proxy checks)."""
    return dict(get_internal_auth_headers())
