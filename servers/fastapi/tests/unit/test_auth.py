"""Sign-in: users, sessions, API tokens, admin-only routes, CSRF, /app_data and the
upgrade from the single ``userConfig.json`` login. Each security fix has a test here."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

import chatppt.settings as settings_mod
from api.v1.auth.router import API_V1_AUTH_ROUTER
from chatppt.auth import bootstrap, passwords, ratelimit, signing, store
from chatppt.auth.middleware import SESSION_COOKIE, SecurityMiddleware
from chatppt.auth.web import signed_path

PUBLIC = "http://chatppt.test:5000"


@pytest.fixture()
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in ("DISABLE_AUTH", "DATABASE_URL", "AUTH_USERNAME", "AUTH_PASSWORD", "RESET_AUTH"):
        monkeypatch.delenv(name, raising=False)
    for name in [n for n in __import__("os").environ if n.startswith("CHATPPT_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("USER_CONFIG_PATH", str(tmp_path / "userConfig.json"))
    monkeypatch.setenv("CHATPPT_SERVER__PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("CHATPPT_SERVER__MAX_UPLOAD_MB", "1")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    monkeypatch.setattr(passwords, "ITERATIONS", 1000)
    ratelimit.reset_all()
    for folder in ("images", "exports"):
        (tmp_path / folder).mkdir()
    (tmp_path / "images" / "slide.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (tmp_path / "fastapi.db.txt").write_text("secret")
    (tmp_path / "chatppt.toml").write_text('[llm.providers.openai]\napi_key = "sk-secret"\n')
    yield tmp_path
    store.dispose()
    ratelimit.reset_all()


def _app(data_dir: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(API_V1_AUTH_ROUTER)

    @app.get("/api/v1/ppt/presentation/all")
    def decks() -> list[str]:
        return []

    @app.post("/api/v1/ppt/presentation/create")
    def create() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/config")
    def config() -> dict[str, str]:
        return {"OPENAI_API_KEY": "sk-secret"}

    @app.post("/api/v1/ppt/files/upload")
    async def upload() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/mcp")
    def mcp() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/app_data", StaticFiles(directory=data_dir), name="app_data")
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=[PUBLIC], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )
    return app


@pytest.fixture()
def client(data: Path) -> TestClient:
    return TestClient(_app(data))


def _login(client: TestClient, username: str = "alice", password: str = "correct-horse") -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- upgrade


def _legacy_hash(password: str) -> str:
    return passwords.hash_password(password, iterations=500)  # fewer than today: upgraded on sign-in


def test_existing_single_login_becomes_the_first_admin(data: Path, client: TestClient) -> None:
    (data / "userConfig.json").write_text(
        json.dumps(
            {
                "AUTH_USERNAME": "Alice",
                "AUTH_PASSWORD_HASH": _legacy_hash("old-pass1"),
                "AUTH_SECRET_KEY": "s3cret",
                "CODEX_MODEL": "x",
            }
        )
    )
    bootstrap.run_startup()

    user = store.get_user_by_username("alice")
    assert user is not None and user.is_admin
    left = json.loads((data / "userConfig.json").read_text())
    assert left == {"CODEX_MODEL": "x"}  # the login moved out; other keys stay
    _login(client, "Alice", "old-pass1")  # same credentials, any case
    assert client.get("/api/v1/ppt/presentation/all").status_code == 200
    # Old hashes are upgraded on sign-in.
    from sqlmodel import select

    from models.sql.user import UserModel

    with store.session() as s:
        row = s.exec(select(UserModel).where(UserModel.username == "alice")).one()
    assert row.password_hash and not passwords.needs_rehash(row.password_hash)


def test_old_session_tokens_are_signed_out_once(data: Path, client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    payload = base64.urlsafe_b64encode(json.dumps({"v": 1, "u": "alice", "exp": int(time.time()) + 99}).encode())
    client.cookies.set(SESSION_COOKIE, payload.decode().rstrip("=") + ".sig")
    assert client.get("/api/v1/ppt/presentation/all").status_code == 401


def test_migration_runs_once_and_never_overwrites_users(data: Path) -> None:
    store.create_user("bob", "bob-password", is_admin=True)
    (data / "userConfig.json").write_text(
        json.dumps({"AUTH_USERNAME": "alice", "AUTH_PASSWORD_HASH": _legacy_hash("x-pass12")})
    )
    assert bootstrap.migrate_legacy_login() is None
    assert store.get_user_by_username("alice") is None


def test_env_preseed_and_override(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "first-pass")
    bootstrap.run_startup()
    assert store.authenticate("admin", "first-pass")
    monkeypatch.setenv("AUTH_PASSWORD", "second-pass")
    bootstrap.run_startup()
    assert store.authenticate("admin", "first-pass")  # no override: unchanged
    monkeypatch.setenv("AUTH_OVERRIDE_FROM_ENV", "true")
    bootstrap.run_startup()
    assert store.authenticate("admin", "second-pass")


# --------------------------------------------------------------------------- sign-in


def test_setup_then_login_then_logout(client: TestClient) -> None:
    assert client.get("/api/v1/ppt/presentation/all").status_code == 428
    assert client.get("/api/v1/auth/status").json()["configured"] is False
    assert client.post("/api/v1/auth/setup", json={"username": "alice", "password": "short"}).status_code == 400
    assert client.post("/api/v1/auth/setup", json={"username": "alice", "password": "correct-horse"}).status_code == 200
    # Setup is only for the very first user.
    assert client.post("/api/v1/auth/setup", json={"username": "eve", "password": "correct-horse"}).status_code == 409
    assert client.get("/api/v1/ppt/presentation/all").status_code == 401
    _login(client)
    status = client.get("/api/v1/auth/status").json()
    assert status["authenticated"] and status["is_admin"] and status["username"] == "alice"
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/ppt/presentation/all").status_code == 401


def test_session_cookie_is_httponly_lax_and_secure_behind_https(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    plain = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"})
    cookie = plain.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    tls = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "correct-horse"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "secure" in tls.headers["set-cookie"].lower()


def test_failed_logins_are_rate_limited(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


def test_basic_auth_failures_are_rate_limited(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    bad = "Basic " + base64.b64encode(b"alice:nope").decode()
    good = "Basic " + base64.b64encode(b"alice:correct-horse").decode()
    assert client.get("/api/v1/ppt/presentation/all", headers={"Authorization": good}).status_code == 200
    for _ in range(10):
        client.get("/api/v1/ppt/presentation/all", headers={"Authorization": bad})
    assert client.get("/api/v1/ppt/presentation/all", headers={"Authorization": good}).status_code == 401


def test_password_change_and_sign_out_everywhere_revoke_sessions(data: Path) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    first, second = TestClient(_app(data)), TestClient(_app(data))
    _login(first)
    _login(second)
    changed = first.post(
        "/api/v1/auth/password", json={"current_password": "correct-horse", "new_password": "battery-staple"}
    )
    assert changed.status_code == 200
    assert first.get("/api/v1/ppt/presentation/all").status_code == 200  # this session renewed
    assert second.get("/api/v1/ppt/presentation/all").status_code == 401  # the other one is out
    first.post("/api/v1/auth/logout-all")
    assert first.get("/api/v1/ppt/presentation/all").status_code == 401


def test_disabled_user_is_locked_out(client: TestClient) -> None:
    store.create_user("root", "root-password", is_admin=True)
    bob = store.create_user("bob", "bob-password")
    _login(client, "bob", "bob-password")
    raw, _ = store.create_token(bob.id, "ci")
    store.update_user(bob.id, is_active=False)
    assert client.get("/api/v1/ppt/presentation/all").status_code == 401
    assert client.get("/api/v1/ppt/presentation/all", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


# --------------------------------------------------------------------------- tokens and MCP


def test_api_token_works_for_rest_and_mcp_until_revoked(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    assert client.get("/mcp").status_code == 401  # MCP needs a user now
    _login(client)
    created = client.post("/api/v1/auth/tokens", json={"name": "laptop"}).json()
    raw = created["token"]
    assert raw.startswith("cpt_") and created["prefix"] == raw[:12]
    listed = client.get("/api/v1/auth/tokens").json()
    assert [t["name"] for t in listed] == ["laptop"] and "token" not in listed[0]

    api = TestClient(client.app)
    bearer = {"Authorization": f"Bearer {raw}"}
    assert api.get("/api/v1/ppt/presentation/all", headers=bearer).status_code == 200
    assert api.get("/mcp", headers=bearer).status_code == 200
    # Token requests are not cookie-borne, so no Origin is needed for writes.
    assert api.post("/api/v1/ppt/presentation/create", headers=bearer).status_code == 200

    assert client.delete(f"/api/v1/auth/tokens/{created['id']}").status_code == 204
    store.invalidate()
    assert api.get("/api/v1/ppt/presentation/all", headers=bearer).status_code == 401


def test_tokens_are_stored_hashed(client: TestClient) -> None:
    alice = store.create_user("alice", "correct-horse", is_admin=True)
    raw, _ = store.create_token(alice.id, "x")
    with store.session() as s:
        from sqlmodel import select

        from models.sql.user import ApiTokenModel

        row = s.exec(select(ApiTokenModel)).one()
    assert raw not in row.token_hash and row.token_hash == store.hash_token(raw)


def test_users_cannot_revoke_each_others_tokens(client: TestClient) -> None:
    store.create_user("root", "root-password", is_admin=True)
    bob = store.create_user("bob", "bob-password")
    store.create_user("carol", "carol-password")
    _, token = store.create_token(bob.id, "bob's")
    _login(client, "carol", "carol-password")
    assert client.delete(f"/api/v1/auth/tokens/{token.id}").status_code == 404


def test_token_creation_is_rate_limited(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    _login(client)
    for _ in range(20):
        assert client.post("/api/v1/auth/tokens", json={"name": "t"}).status_code == 200
    assert client.post("/api/v1/auth/tokens", json={"name": "t"}).status_code == 429


# --------------------------------------------------------------------------- admins


def test_provider_keys_and_users_are_admin_only(client: TestClient) -> None:
    store.create_user("root", "root-password", is_admin=True)
    store.create_user("bob", "bob-password")
    _login(client, "bob", "bob-password")
    assert client.get("/api/v1/config").status_code == 403
    assert client.get("/api/v1/auth/users").status_code == 403
    assert client.post("/api/v1/auth/users", json={"username": "eve", "password": "eve-password"}).status_code == 403
    assert client.get("/api/v1/ppt/presentation/all").status_code == 200  # decks are shared

    admin = TestClient(client.app)
    _login(admin, "root", "root-password")
    assert admin.get("/api/v1/config").status_code == 200
    made = admin.post("/api/v1/auth/users", json={"username": "Eve", "password": "eve-password"})
    assert made.status_code == 200 and made.json()["username"] == "eve"


def test_the_last_admin_cannot_be_removed(client: TestClient) -> None:
    root = store.create_user("root", "root-password", is_admin=True)
    _login(client, "root", "root-password")
    assert client.patch(f"/api/v1/auth/users/{root.id}", json={"is_admin": False}).status_code == 400
    assert client.patch(f"/api/v1/auth/users/{root.id}", json={"is_active": False}).status_code == 400
    with pytest.raises(store.AuthError):
        store.delete_user(root.id)


# --------------------------------------------------------------------------- CSRF and CORS


def test_cross_site_cookie_writes_are_refused(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    _login(client)
    url = "/api/v1/ppt/presentation/create"
    assert client.post(url, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post(url, headers={"Origin": "null"}).status_code == 403
    assert client.post(url, headers={"Origin": PUBLIC}).status_code == 200
    # Same origin through the public port (Next.js forwards the host it was asked for).
    assert (
        client.post(url, headers={"Origin": "http://10.0.0.5:5000", "X-Forwarded-Host": "10.0.0.5:5000"}).status_code
        == 200
    )
    assert client.post(url).status_code == 200  # not a browser


def test_login_csrf_is_refused(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "correct-horse"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_cors_allows_only_the_public_url(client: TestClient) -> None:
    ok = client.options("/api/v1/auth/status", headers={"Origin": PUBLIC, "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == PUBLIC
    bad = client.get("/api/v1/auth/status", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_disabled_auth_keeps_working_and_still_refuses_cross_site_writes(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    client = TestClient(_app(data))
    assert client.get("/api/v1/ppt/presentation/all").status_code == 200
    assert client.get("/api/v1/config").status_code == 200
    assert client.get("/api/v1/auth/status").json()["authenticated"] is True
    assert client.post("/api/v1/ppt/presentation/create").status_code == 200
    assert client.post("/api/v1/ppt/presentation/create", headers={"Origin": "https://evil.example"}).status_code == 403


# --------------------------------------------------------------------------- /app_data


@pytest.mark.parametrize(
    "path",
    [
        "/app_data/chatppt.toml",
        "/app_data/userConfig.json",
        "/app_data/fastapi.db.txt",
        "/app_data/images/../chatppt.toml",
        "/app_data/images/%2e%2e/chatppt.toml",
        "/app_data/hooks.py",
    ],
)
def test_app_data_serves_media_folders_only(client: TestClient, path: str) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    _login(client)
    response = client.get(path)
    assert response.status_code == 404
    assert b"sk-secret" not in response.content


def test_slide_images_need_a_session_or_a_signed_link(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    anonymous = TestClient(client.app)
    assert anonymous.get("/app_data/images/slide.png").status_code == 401  # no longer public
    link = signed_path("/app_data/images/slide.png")
    assert anonymous.get(link).status_code == 200
    tampered = link.replace("slide.png", "other.png")
    assert anonymous.get(tampered).status_code == 401
    expired = signing.sign_path("/app_data/images/slide.png", -10)
    assert anonymous.get(expired).status_code == 401
    _login(client)
    response = client.get("/app_data/images/slide.png")
    assert response.status_code == 200
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_exporter_token_is_read_only(client: TestClient) -> None:
    alice = store.create_user("alice", "correct-horse", is_admin=True)
    exporter = TestClient(client.app)
    exporter.cookies.set(SESSION_COOKIE, signing.issue_export_token(alice.id))
    assert exporter.get("/api/v1/ppt/presentation/all").status_code == 200
    assert exporter.get("/app_data/images/slide.png").status_code == 200
    assert exporter.post("/api/v1/ppt/presentation/create").status_code == 403
    assert exporter.get("/api/v1/config").status_code == 403  # never an admin


def test_export_token_endpoint_issues_a_short_lived_read_only_cookie(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    _login(client)
    cookie = client.post("/api/v1/auth/export-token").json()["cookie"]
    name, _, value = cookie.partition("=")
    assert name == SESSION_COOKIE and signing.export_token_user_id(value) is not None
    assert signing.session_user(value) is None


# --------------------------------------------------------------------------- headers and limits


def test_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/auth/status")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]


def test_oversized_bodies_are_refused(client: TestClient) -> None:
    store.create_user("alice", "correct-horse", is_admin=True)
    _login(client)
    response = client.post("/api/v1/ppt/files/upload", content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413


# --------------------------------------------------------------------------- SSO


def test_trusted_proxy_header_with_secret(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATPPT_AUTH__PROXY_HEADER", "Remote-User")
    monkeypatch.setenv("CHATPPT_AUTH__PROXY_SECRET", "proxy-shared-secret")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    client = TestClient(_app(data))
    assert client.get("/api/v1/ppt/presentation/all", headers={"Remote-User": "dana"}).status_code == 428
    headers = {"Remote-User": "dana", "X-ChatPPT-Proxy-Secret": "proxy-shared-secret"}
    assert client.get("/api/v1/ppt/presentation/all", headers=headers).status_code == 200
    dana = store.get_user_by_username("dana")
    assert dana is not None and dana.is_admin and dana.source == "proxy"  # first user of the install
    headers2 = {"Remote-User": "erin", "X-ChatPPT-Proxy-Secret": "proxy-shared-secret"}
    assert client.get("/api/v1/config", headers=headers2).status_code == 403  # later users are not admins
