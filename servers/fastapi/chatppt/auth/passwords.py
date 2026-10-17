"""Password hashes: PBKDF2-SHA256, stored as ``pbkdf2_sha256$<iterations>$<salt>$<digest>``.

The format is the one upstream wrote to ``userConfig.json``, so a migrated hash verifies
unchanged; hashes with fewer iterations than today's are upgraded on the next sign-in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ITERATIONS = 600_000
MIN_LENGTH = 8
MAX_LENGTH = 256
_DUMMY = f"pbkdf2_sha256${ITERATIONS}$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def check_new_password(password: str) -> None:
    """Raise ValueError (message shown to the user) when a new password is unacceptable."""
    if len(password or "") < MIN_LENGTH:
        raise ValueError(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise ValueError(f"Password must be at most {MAX_LENGTH} characters")


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Constant-time check. A missing hash still costs one derivation, so timing does not
    reveal whether a username exists."""
    try:
        algorithm, iterations, salt, digest = (encoded or _DUMMY).split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), _b64d(salt), int(iterations))
        return hmac.compare_digest(actual, _b64d(digest)) and encoded is not None
    except (ValueError, TypeError):
        return False


def needs_rehash(encoded: str) -> bool:
    try:
        return int(encoded.split("$")[1]) < ITERATIONS
    except (IndexError, ValueError):
        return True
