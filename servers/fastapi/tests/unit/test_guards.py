"""Upload validation, path-traversal guards and the SSRF guard on server-side fetches.
Each fix has a regression test here."""

from __future__ import annotations

import asyncio
import io
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

import chatppt.settings as settings_mod
from chatppt import guards
from services.database import get_async_session

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TTF = b"\x00\x01\x00\x00" + b"\x00" * 32


@pytest.fixture()
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    data, temp = tmp_path / "data", tmp_path / "temp"
    data.mkdir()
    temp.mkdir()
    for name in [n for n in __import__("os").environ if n.startswith("CHATPPT_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(data))
    monkeypatch.setenv("TEMP_DIRECTORY", str(temp))
    monkeypatch.setenv("USER_CONFIG_PATH", str(data / "userConfig.json"))
    monkeypatch.setattr(settings_mod, "_loaded", None)
    from services.temp_file_service import TEMP_FILE_SERVICE

    monkeypatch.setattr(TEMP_FILE_SERVICE, "base_dir", str(temp))
    (data / "chatppt.toml").write_text('[llm.providers.openai]\napi_key = "sk-secret"\n')
    yield data, temp


class _NoDb:
    def add(self, _: Any) -> None:  # never reached by a rejected upload
        raise AssertionError("database touched")


def _client(*routers: Any) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    app.dependency_overrides[get_async_session] = lambda: _NoDb()
    return TestClient(app)


# --------------------------------------------------------------------------- names and paths


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\boot.ini", "boot.ini"),
        ("..", "file"),
        ("", "file"),
        (None, "file"),
        (".bashrc", "bashrc"),
        ("my font (bold).ttf", "my font (bold).ttf"),
        ("a\x00b.png", "a_b.png"),
    ],
)
def test_safe_filename_strips_paths(name: str | None, expected: str) -> None:
    assert guards.safe_filename(name) == expected


def test_inside_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_text("x")
    assert guards.inside(root / "ok.txt", [root]) == (root / "ok.txt").resolve()
    with pytest.raises(HTTPException) as exc:
        guards.inside(root / ".." / "secret", [root])
    assert exc.value.status_code == 400
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(HTTPException):
        guards.inside(root / "link" / "secret", [root])


def test_files_decompose_refuses_paths_outside_uploads(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.files import FILES_ROUTER

    data, _ = dirs
    client = _client(FILES_ROUTER)
    for path in (str(data / "chatppt.toml"), "/etc/passwd", str(dirs[1] / ".." / "data" / "chatppt.toml")):
        response = client.post("/files/decompose", json={"file_paths": [path]})
        assert response.status_code == 400, path


def test_files_update_cannot_write_outside_uploads(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.files import FILES_ROUTER

    data, temp = dirs
    client = _client(FILES_ROUTER)
    target = data / "chatppt.toml"
    response = client.post(
        "/files/update", data={"file_path": str(target)}, files={"file": ("x.txt", b"pwned", "text/plain")}
    )
    assert response.status_code == 400
    assert "sk-secret" in target.read_text()

    (temp / "doc.txt").write_text("old")
    response = client.post(
        "/files/update", data={"file_path": str(temp / "doc.txt")}, files={"file": ("x.txt", b"new", "text/plain")}
    )
    assert response.status_code == 200
    assert (temp / "doc.txt").read_text() == "new"


def test_files_upload_keeps_files_in_the_temp_folder(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.files import FILES_ROUTER

    data, temp = dirs
    response = _client(FILES_ROUTER).post(
        "/files/upload", files={"files": ("../../data/evil.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 200, response.text
    (saved,) = response.json()
    assert Path(saved).resolve().is_relative_to(temp.resolve())
    assert not (data / "evil.txt").exists()


def test_documents_loader_refuses_paths_outside_uploads(dirs: tuple[Path, Path]) -> None:
    from services.documents_loader import DocumentsLoader

    loader = DocumentsLoader(file_paths=[str(dirs[0] / "chatppt.toml")])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(loader.load_documents())
    assert exc.value.status_code == 400


def test_app_path_resolver_stays_in_media_folders(dirs: tuple[Path, Path]) -> None:
    from utils.asset_directory_utils import resolve_app_path_to_filesystem

    data, temp = dirs
    (data / "images").mkdir()
    (data / "images" / "a.png").write_bytes(PNG)
    assert resolve_app_path_to_filesystem("/app_data/images/a.png") == str(data / "images" / "a.png")
    assert resolve_app_path_to_filesystem("/app_data/chatppt.toml") is None
    assert resolve_app_path_to_filesystem("/app_data/images/../chatppt.toml") is None
    assert resolve_app_path_to_filesystem("file:///etc/passwd") is None
    assert resolve_app_path_to_filesystem("/etc/passwd") is None
    (temp / "out.html").write_text("x")
    assert resolve_app_path_to_filesystem(str(temp / "out.html")) == str(temp / "out.html")


def test_font_delete_rejects_traversal(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.fonts import FONTS_ROUTER

    data, _ = dirs
    response = _client(FONTS_ROUTER).delete("/fonts/delete/..%2Fchatppt.toml")
    assert response.status_code in (400, 404)
    assert (data / "chatppt.toml").exists()


def test_pptx_font_install_uses_a_safe_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.v1.ppt.endpoints import pptx_slides

    monkeypatch.setattr(pptx_slides.subprocess, "run", lambda *a, **k: None)
    upload = UploadFile(io.BytesIO(TTF), filename="../../escaped.ttf")
    asyncio.run(pptx_slides._install_fonts([upload], str(tmp_path / "work")))
    assert (tmp_path / "work" / "fonts" / "escaped.ttf").exists()
    assert not (tmp_path / "escaped.ttf").exists()


# --------------------------------------------------------------------------- upload type and size


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(content), filename=name, size=len(content))


def test_check_upload_accepts_real_images_and_fonts(dirs: tuple[Path, Path]) -> None:
    assert asyncio.run(guards.check_upload(_upload("a.png", PNG), "image")) == "a.png"
    assert asyncio.run(guards.check_upload(_upload("x.svg", b"<svg xmlns='...'/>"), "image")) == "x.svg"
    assert asyncio.run(guards.check_upload(_upload("../f.ttf", TTF), "font")) == "f.ttf"


@pytest.mark.parametrize(
    ("name", "content", "kind", "status"),
    [
        ("shell.php", PNG, "image", 400),
        ("fake.png", b"<html><script>alert(1)</script>", "image", 400),
        ("page.svg", b"<html>hi</html>", "image", 400),
        ("font.ttf", b"MZ\x90\x00", "font", 400),
        ("big.png", PNG + b"\x00" * (2 * 1024 * 1024), "image", 413),
    ],
)
def test_check_upload_rejects(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, name: str, content: bytes, kind: str, status: int
) -> None:
    monkeypatch.setenv("CHATPPT_SERVER__MAX_UPLOAD_MB", "1")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(guards.check_upload(_upload(name, content), kind))
    assert exc.value.status_code == status


def test_image_upload_endpoint_rejects_non_images(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.images import IMAGES_ROUTER

    response = _client(IMAGES_ROUTER).post(
        "/images/upload", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")}
    )
    assert response.status_code == 400


def test_font_upload_endpoint_rejects_bad_content_and_keeps_name_local(dirs: tuple[Path, Path]) -> None:
    from api.v1.ppt.endpoints.fonts import FONTS_ROUTER

    data, _ = dirs
    client = _client(FONTS_ROUTER)
    bad = client.post("/fonts/upload", files={"font_file": ("x.ttf", b"MZ\x90\x00 not a font", "font/ttf")})
    assert bad.status_code == 400
    ok = client.post("/fonts/upload", files={"font_file": ("../../evil.ttf", TTF, "font/ttf")})
    if ok.status_code == 200:  # fontTools may reject the stub; the name must stay local either way
        assert Path(ok.json()["font_path"]).resolve().parent == (data / "fonts").resolve()
    assert not (data / "evil.ttf").exists()
    assert not (data.parent / "evil.ttf").exists()


# --------------------------------------------------------------------------- SSRF


def _resolve_to(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    async def fake(self: Any, host: str, port: Any, **_: Any) -> list[Any]:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "getaddrinfo", fake)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "::ffff:127.0.0.1", "0.0.0.0"]
)
def test_outbound_url_blocks_private_addresses(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, ip: str
) -> None:
    _resolve_to(monkeypatch, ip)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(guards.check_outbound_url("http://hooks.example.com/x"))
    assert exc.value.status_code == 400


def test_outbound_url_allows_public_addresses(dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve_to(monkeypatch, "93.184.216.34")
    asyncio.run(guards.check_outbound_url("https://hooks.example.com/x"))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "http:///nohost", "ftp://example.com/"])
def test_outbound_url_rejects_other_schemes(dirs: tuple[Path, Path], url: str) -> None:
    with pytest.raises(HTTPException):
        asyncio.run(guards.check_outbound_url(url))


def test_outbound_url_allow_list_and_configured_providers(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolve_to(monkeypatch, "127.0.0.1")
    monkeypatch.setenv("CHATPPT_SERVER__FETCH_ALLOW_HOSTS", "n8n.internal, other:9000")
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setattr(settings_mod, "_loaded", None)
    asyncio.run(guards.check_outbound_url("http://n8n.internal/hook"))
    asyncio.run(guards.check_outbound_url("http://other:9000/hook"))
    asyncio.run(guards.check_outbound_url("http://localhost:11434/api/tags"))
    with pytest.raises(HTTPException):
        asyncio.run(guards.check_outbound_url("http://localhost:6379/"))  # same host, other port
    with pytest.raises(HTTPException):
        asyncio.run(guards.check_outbound_url("http://other:9001/"))


def test_webhook_subscribe_refuses_internal_targets(dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from api.v1.webhook.router import API_V1_WEBHOOK_ROUTER

    _resolve_to(monkeypatch, "169.254.169.254")
    response = _client(API_V1_WEBHOOK_ROUTER).post(
        "/api/v1/webhook/subscribe",
        json={"url": "http://metadata.example/latest", "event": "presentation.generation.completed"},
    )
    assert response.status_code == 400


def test_webhook_send_rechecks_the_target(dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from models.sql.webhook_subscription import WebhookSubscription
    from services import webhook_service

    _resolve_to(monkeypatch, "10.1.2.3")
    posted: list[str] = []

    class _Session:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        def post(self, url: str, **_: Any) -> Any:
            posted.append(url)
            raise AssertionError("request sent")

    monkeypatch.setattr(webhook_service.aiohttp, "ClientSession", _Session)
    sub = WebhookSubscription(url="http://rebound.example/hook", event="presentation.generation.completed")
    asyncio.run(webhook_service.WebhookService.send_request_to_webhook(sub, {"a": 1}))
    assert posted == []
