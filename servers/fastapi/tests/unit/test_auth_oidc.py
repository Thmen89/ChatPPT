"""OIDC sign-in against a fake provider (no network)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

import chatppt.settings as settings_mod
from chatppt.auth import oidc, store
from tests.unit.test_auth import PUBLIC, _app, data  # noqa: F401  (fixture)

ISSUER = "https://idp.test/realms/x"


def _jwt(claims: dict[str, Any]) -> str:
    def part(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


@pytest.fixture()
def provider(data: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    monkeypatch.setenv("CHATPPT_AUTH__OIDC__ISSUER", ISSUER)
    monkeypatch.setenv("CHATPPT_AUTH__OIDC__CLIENT_ID", "chatppt")
    monkeypatch.setenv("CHATPPT_AUTH__OIDC__CLIENT_SECRET", "s")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    oidc._discovery.clear()
    state: dict[str, Any] = {"claims": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                },
            )
        form = parse_qs(request.content.decode())
        state["form"] = form
        return httpx.Response(200, json={"id_token": _jwt(state["claims"])})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


def _sign_in(client: TestClient, provider: dict[str, Any], **claims: Any) -> httpx.Response:
    start = client.get("/api/v1/auth/oidc/start", follow_redirects=False)
    assert start.status_code == 303
    params = parse_qs(urlsplit(start.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [f"{PUBLIC}/api/v1/auth/oidc/callback"]
    provider["claims"] = {
        "iss": ISSUER,
        "aud": "chatppt",
        "exp": int(time.time()) + 60,
        "nonce": params["nonce"][0],
        **claims,
    }
    return client.get(
        "/api/v1/auth/oidc/callback", params={"code": "c", "state": params["state"][0]}, follow_redirects=False
    )


def test_oidc_sign_in_creates_the_user_and_a_session(data: Path, provider: dict[str, Any]) -> None:  # noqa: F811
    client = TestClient(_app(data))
    assert client.get("/api/v1/auth/status").json()["oidc"]["enabled"] is True
    done = _sign_in(client, provider, preferred_username="Dana")
    assert done.status_code == 303 and done.headers["location"] == "/"
    assert provider["form"]["code_verifier"]  # PKCE
    assert client.get("/api/v1/ppt/presentation/all").status_code == 200
    user = store.get_user_by_username("dana")
    assert user is not None and user.source == "oidc"


@pytest.mark.parametrize(
    "bad",
    [{"iss": "https://evil.test"}, {"aud": "someone-else"}, {"exp": 1}, {"nonce": "replayed"}],
)
def test_oidc_rejects_bad_id_tokens(data: Path, provider: dict[str, Any], bad: dict[str, Any]) -> None:  # noqa: F811
    client = TestClient(_app(data))
    done = _sign_in(client, provider, preferred_username="dana", **bad)
    assert done.headers["location"].startswith("/?reason=sso_failed")
    assert store.get_user_by_username("dana") is None


def test_oidc_rejects_a_state_from_another_browser(data: Path, provider: dict[str, Any]) -> None:  # noqa: F811
    client = TestClient(_app(data))
    client.get("/api/v1/auth/oidc/start", follow_redirects=False)
    done = client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert done.headers["location"].startswith("/?reason=sso_failed")


def test_oidc_without_auto_create_needs_an_existing_user(
    data: Path,  # noqa: F811
    provider: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHATPPT_AUTH__OIDC__CREATE_USERS", "false")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    store.create_user("root", "root-password", is_admin=True)
    client = TestClient(_app(data))
    assert _sign_in(client, provider, email="newbie@corp.test").headers["location"] == "/?reason=sso_no_user"
