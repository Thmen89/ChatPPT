"""Signed links: what the headless exporter and API clients get instead of an open
``/app_data/images/`` path."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from chatppt.auth import store
from chatppt.auth.web import sign_app_data_urls
from models.presentation_and_path import PresentationPathAndEditPath
from tests.unit.test_auth import client, data  # noqa: F401  (fixtures)


def test_export_deck_links_are_signed_for_the_cookieless_converter(client: TestClient) -> None:  # noqa: F811
    store.create_user("alice", "correct-horse", is_admin=True)
    deck = {
        "slides": [
            {"content": {"image": {"__image_url__": "http://127.0.0.1:5000/app_data/images/slide.png"}}},
            {"content": {"logo": "/app_data/images/slide.png", "icon": "/static/icons/x.png"}},
            {"content": {"already": "/app_data/images/slide.png?exp=1&sig=x"}},
        ]
    }
    signed = sign_app_data_urls(deck)
    first = signed["slides"][0]["content"]["image"]["__image_url__"]
    second = signed["slides"][1]["content"]["logo"]
    assert first.startswith("http://127.0.0.1:5000/app_data/images/slide.png?exp=")
    assert signed["slides"][1]["content"]["icon"] == "/static/icons/x.png"
    assert signed["slides"][2]["content"]["already"] == "/app_data/images/slide.png?exp=1&sig=x"
    assert TestClient(client.app).get(second).status_code == 200


def test_generation_response_carries_a_signed_download_link(data: Path, client: TestClient) -> None:  # noqa: F811
    store.create_user("alice", "correct-horse", is_admin=True)
    (data / "exports" / "deck.pptx").write_bytes(b"PK")
    result = PresentationPathAndEditPath(
        presentation_id=uuid.uuid4(), path=str(data / "exports" / "deck.pptx"), edit_path="/presentation?id=x"
    )
    link = result.model_dump()["download_url"]
    assert link.startswith("/app_data/exports/deck.pptx?exp=")
    assert TestClient(client.app).get(link).status_code == 200
    outside = PresentationPathAndEditPath(presentation_id=uuid.uuid4(), path="/etc/passwd", edit_path="/")
    assert outside.download_url is None
