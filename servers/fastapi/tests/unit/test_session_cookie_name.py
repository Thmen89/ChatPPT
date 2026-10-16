"""The session cookie was renamed from `presenton_session` to `chatppt_session`.

The old name is still read for one release so sessions survive the upgrade, and logout clears both.
"""

from starlette.requests import Request
from starlette.responses import Response

from utils.simple_auth import (
    LEGACY_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    get_session_token_from_request,
)


def _request(cookie: str = "") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "headers": headers, "scheme": "http", "path": "/"})


def test_new_cookie_name():
    assert SESSION_COOKIE_NAME == "chatppt_session"
    assert get_session_token_from_request(_request("chatppt_session=new")) == "new"


def test_legacy_cookie_still_read():
    assert get_session_token_from_request(_request("presenton_session=old")) == "old"


def test_new_cookie_wins_over_legacy():
    request = _request("presenton_session=old; chatppt_session=new")
    assert get_session_token_from_request(request) == "new"


def test_logout_clears_both_names():
    response = Response()
    clear_session_cookie(response, _request())
    cleared = response.headers.getlist("set-cookie")
    assert any(c.startswith(f"{SESSION_COOKIE_NAME}=") for c in cleared)
    assert any(c.startswith(f"{LEGACY_SESSION_COOKIE_NAME}=") for c in cleared)
