"""Speed-path behaviour: parallel slide generation, streaming order, schema-once, layout cache."""

import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.v1.ppt.endpoints import presentation as presentation_endpoint
from chatppt.prompts import BUILTIN_DIR, render_prompt
from models.generate_presentation_request import GeneratePresentationRequest
from models.presentation_and_path import PresentationAndPath
from models.presentation_outline_model import PresentationOutlineModel, SlideOutlineModel
from models.presentation_structure_model import PresentationStructureModel
from models.sql.presentation import PresentationModel
from templates import get_layout_by_name as layout_lookup
from templates.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from tests.conftest import FakeAsyncSession
from utils.llm_calls import generate_slide_content as slide_content


def _layout(n: int = 3, ordered: bool = False) -> PresentationLayoutModel:
    return PresentationLayoutModel(
        name="general",
        ordered=ordered,
        slides=[
            SlideLayoutModel(
                id=f"general:l{i}",
                name=f"L{i}",
                description="d",
                json_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )
            for i in range(n)
        ],
    )


# --------------------------------------------------------------------------- parallel stream


def _prepared_presentation(n_slides: int) -> PresentationModel:
    now = datetime.now()
    presentation = PresentationModel(
        id=uuid.uuid4(), content="deck", n_slides=n_slides, language="English", created_at=now, updated_at=now
    )
    presentation.outlines = PresentationOutlineModel(
        slides=[SlideOutlineModel(content=f"## Slide {i}") for i in range(n_slides)]
    ).model_dump()
    presentation.set_layout(_layout())
    presentation.set_structure(PresentationStructureModel(slides=[i % 3 for i in range(n_slides)]))
    return presentation


def _collect_sse(response) -> list[dict]:
    async def collect():
        out = []
        async for raw in response.body_iterator:
            text = raw.decode() if isinstance(raw, bytes) else raw
            for line in text.splitlines():
                if line.startswith("data:"):
                    out.append(json.loads(line[5:].strip()))
        return out

    return asyncio.run(collect())


def test_stream_generates_slides_in_parallel_and_streams_them_as_they_land(monkeypatch):
    n_slides = 5
    presentation = _prepared_presentation(n_slides)
    session = FakeAsyncSession({presentation.id: presentation})
    running = {"now": 0, "peak": 0}

    async def fake_content(slide_layout, outline, *_args):
        running["now"] += 1
        running["peak"] = max(running["peak"], running["now"])
        index = int(outline.content.split()[-1])
        # Later slides finish first, so arrival order is the reverse of slide order.
        await asyncio.sleep(0.01 * (n_slides - index))
        running["now"] -= 1
        return {"title": f"t{index}", "__speaker_note__": "note"}

    monkeypatch.setattr(presentation_endpoint, "get_slide_content_from_type_and_outline", fake_content)
    monkeypatch.setattr(presentation_endpoint, "process_slide_and_fetch_assets", AsyncMock(return_value=[]))
    monkeypatch.setattr(presentation_endpoint, "ImageGenerationService", Mock())
    monkeypatch.setattr(presentation_endpoint, "get_images_directory", lambda: "/tmp")
    monkeypatch.setattr(presentation_endpoint, "_slide_concurrency", lambda: 3)

    response = asyncio.run(presentation_endpoint.stream_presentation(presentation.id, sql_session=session))
    events = _collect_sse(response)

    chunks = [e["chunk"] for e in events if e.get("type") == "chunk"]
    slide_chunks = [json.loads(c.lstrip(", ")) for c in chunks if c.lstrip(", ").startswith("{") and "index" in c]
    assert running["peak"] == 3  # bounded by llm.concurrency
    assert sorted(s["index"] for s in slide_chunks) == list(range(n_slides))
    assert [s["index"] for s in slide_chunks] != list(range(n_slides))  # streamed out of order
    # The concatenated chunks are still one valid JSON document.
    assert len(json.loads("".join(chunks))["slides"]) == n_slides
    # Every slide's assets event names its index, after that slide's chunk.
    asset_indices = [e["slide_index"] for e in events if e.get("type") == "slide_assets"]
    assert sorted(asset_indices) == list(range(n_slides))
    complete = events[-1]
    assert complete["type"] == "complete"
    assert [s["index"] for s in complete["presentation"]["slides"]] == list(range(n_slides))
    assert [s.index for s in session.added_all] == list(range(n_slides))


def test_stream_reports_a_failed_slide_as_an_error_event(monkeypatch):
    from fastapi import HTTPException

    presentation = _prepared_presentation(3)
    session = FakeAsyncSession({presentation.id: presentation})

    async def fake_content(_layout, outline, *_args):
        if outline.content.endswith("1"):
            raise HTTPException(status_code=429, detail="rate limited")
        await asyncio.sleep(0.05)
        return {"title": "t"}

    monkeypatch.setattr(presentation_endpoint, "get_slide_content_from_type_and_outline", fake_content)
    monkeypatch.setattr(presentation_endpoint, "process_slide_and_fetch_assets", AsyncMock(return_value=[]))
    monkeypatch.setattr(presentation_endpoint, "ImageGenerationService", Mock())
    monkeypatch.setattr(presentation_endpoint, "get_images_directory", lambda: "/tmp")

    response = asyncio.run(presentation_endpoint.stream_presentation(presentation.id, sql_session=session))
    events = _collect_sse(response)
    assert any(e.get("type") == "error" and e.get("detail") == "rate limited" for e in events)
    assert session.added_all == []


# --------------------------------------------------------------------------- API path: one call fewer


def _run_api(outline_payload: dict, layout: PresentationLayoutModel, structure_mock: AsyncMock):
    request = GeneratePresentationRequest(
        content="deck", n_slides=2, language="English", export_as="pptx", template="general"
    )
    presentation_id = uuid.uuid4()
    seen_layout = {}

    async def fake_outline(*args, **_kwargs):
        seen_layout["layout"] = args[-1]
        yield json.dumps(outline_payload)

    session: Any = FakeAsyncSession()
    with (
        patch.object(
            presentation_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generation_context", new=AsyncMock()
        ),
        patch.object(
            presentation_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generated_outlines", new=AsyncMock()
        ),
        patch.object(presentation_endpoint, "generate_ppt_outline", side_effect=fake_outline),
        patch.object(presentation_endpoint, "get_layout_by_name", new=AsyncMock(return_value=layout)),
        patch.object(presentation_endpoint, "generate_presentation_structure", new=structure_mock),
        patch.object(
            presentation_endpoint,
            "get_slide_content_from_type_and_outline",
            new=AsyncMock(return_value={"title": "x"}),
        ),
        patch.object(presentation_endpoint, "process_slide_and_fetch_assets", new=AsyncMock(return_value=[])),
        patch.object(presentation_endpoint, "get_images_directory", return_value="/tmp"),
        patch.object(presentation_endpoint, "ImageGenerationService", return_value=Mock()),
        patch.object(
            presentation_endpoint,
            "export_presentation",
            new=AsyncMock(return_value=PresentationAndPath(presentation_id=presentation_id, path="/tmp/d.pptx")),
        ),
        patch.object(presentation_endpoint.CONCURRENT_SERVICE, "run_task", new=Mock()),
    ):
        asyncio.run(
            presentation_endpoint.generate_presentation_handler(
                request=request, presentation_id=presentation_id, async_status=None, sql_session=session
            )
        )
    return session, seen_layout["layout"]


def test_api_outline_picks_layouts_and_skips_the_structure_call():
    structure = AsyncMock(return_value=PresentationStructureModel(slides=[0, 0]))
    payload = {"slides": [{"content": "## A", "layout": 2}, {"content": "## B", "layout": 1}]}
    session, outline_layout = _run_api(payload, _layout(3), structure)
    assert outline_layout is not None
    structure.assert_not_awaited()
    assert [s.layout for s in session.added_all] == ["general:l2", "general:l1"]


def test_api_falls_back_to_the_structure_call_when_the_outline_has_no_layouts():
    structure = AsyncMock(return_value=PresentationStructureModel(slides=[1, 0]))
    payload = {"slides": [{"content": "## A"}, {"content": "## B", "layout": 9}]}
    session, _ = _run_api(payload, _layout(3), structure)
    structure.assert_awaited_once()
    assert [s.layout for s in session.added_all] == ["general:l1", "general:l0"]


def test_api_ordered_template_needs_no_layout_choice():
    structure = AsyncMock()
    payload = {"slides": [{"content": "## A"}, {"content": "## B"}]}
    _, outline_layout = _run_api(payload, _layout(3, ordered=True), structure)
    assert outline_layout is None
    structure.assert_not_awaited()


# --------------------------------------------------------------------------- UI path: template first


def test_ui_create_with_template_stores_its_layout():
    session: Any = FakeAsyncSession()
    with patch.object(presentation_endpoint, "get_layout_by_name", new=AsyncMock(return_value=_layout(3))):
        presentation = asyncio.run(
            presentation_endpoint.create_presentation(content="deck", template="general", sql_session=session)
        )
    assert presentation.get_layout().name == "general"


def test_ui_outline_stream_picks_layouts_when_the_template_is_known():
    from api.v1.ppt.endpoints import outlines as outlines_endpoint

    now = datetime.now()
    presentation = PresentationModel(
        id=uuid.uuid4(), content="deck", n_slides=2, language="English", created_at=now, updated_at=now
    )
    presentation.set_layout(_layout(3))
    session = FakeAsyncSession({presentation.id: presentation})
    seen = {}

    async def fake_outline(*args, **_kwargs):
        seen["layout"] = args[-1]
        yield json.dumps({"slides": [{"content": "## A " + "x" * 100, "layout": 2}, {"content": "## B", "layout": 0}]})

    with (
        patch.object(outlines_endpoint, "generate_ppt_outline", side_effect=fake_outline),
        patch.object(outlines_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generation_context", new=AsyncMock()),
        patch.object(outlines_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generated_outlines", new=AsyncMock()),
    ):
        response = asyncio.run(outlines_endpoint.stream_outlines(presentation.id, sql_session=session))
        events = _collect_sse(response)
    assert seen["layout"] is not None
    complete = next(e for e in events if e.get("type") == "complete")
    assert complete["presentation"]["structure"] == {"slides": [2, 0]}


def test_ui_prepare_uses_the_outline_layouts_and_skips_the_structure_call():
    now = datetime.now()
    presentation = PresentationModel(
        id=uuid.uuid4(), content="deck", n_slides=2, language="English", created_at=now, updated_at=now
    )
    presentation.set_layout(_layout(3))
    session = FakeAsyncSession({presentation.id: presentation})
    structure = AsyncMock(return_value=PresentationStructureModel(slides=[0, 0]))
    outlines = [SlideOutlineModel(content="## A"), SlideOutlineModel(content="## B")]
    with (
        patch.object(presentation_endpoint, "generate_presentation_structure", new=structure),
        patch.object(
            presentation_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generated_outlines", new=AsyncMock()
        ),
    ):
        asyncio.run(
            presentation_endpoint.prepare_presentation(
                presentation_id=presentation.id, outlines=outlines, layouts=[2, 1], sql_session=session
            )
        )
        structure.assert_not_awaited()
        assert presentation.get_structure().slides == [2, 1]

        # An outline edited into a different shape (no layout per slide) falls back to the call.
        asyncio.run(
            presentation_endpoint.prepare_presentation(
                presentation_id=presentation.id, outlines=outlines, layouts=[2], sql_session=session
            )
        )
        structure.assert_awaited_once()


# --------------------------------------------------------------------------- schema sent once


class _Client:
    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.replies.pop(0))


def _slide_layout() -> SlideLayoutModel:
    return SlideLayoutModel(
        id="l",
        json_schema={
            "type": "object",
            "properties": {"title": {"type": "string", "maxLength": 40}, "body": {"type": "string"}},
            "required": ["title", "body"],
        },
    )


def _system_text(call: dict) -> str:
    return call["messages"][0].content


def test_slide_schema_goes_only_in_response_format(monkeypatch):
    client = _Client([{"title": "t", "body": "b", "__speaker_note__": "n" * 120}])
    monkeypatch.setattr(slide_content, "llm_for_step", lambda _step: (client, "m-schema-once"))
    monkeypatch.setattr(slide_content, "_SCHEMA_IN_PROMPT", set())
    monkeypatch.setattr("utils.llm_utils.get_extra_body", lambda: None)

    asyncio.run(
        slide_content.get_slide_content_from_type_and_outline(
            _slide_layout(), SlideOutlineModel(content="x"), "English"
        )
    )

    call = client.calls[0]
    assert '"maxLength": 40' not in _system_text(call)
    assert call["response_format"].json_schema["properties"]["title"]["maxLength"] == 40


def test_provider_that_ignores_response_format_gets_the_schema_in_the_prompt(monkeypatch):
    good = {"title": "t", "body": "b", "__speaker_note__": "n" * 120}
    client = _Client([{"text": "free-form answer"}, good, good])
    monkeypatch.setattr(slide_content, "llm_for_step", lambda _step: (client, "m-ignores-schema"))
    monkeypatch.setattr(slide_content, "_SCHEMA_IN_PROMPT", set())
    monkeypatch.setattr("utils.llm_utils.get_extra_body", lambda: None)
    layout, outline = _slide_layout(), SlideOutlineModel(content="x")

    asyncio.run(slide_content.get_slide_content_from_type_and_outline(layout, outline, "English"))
    retry_text = client.calls[1]["messages"][-1].content
    assert '"maxLength": 40' in retry_text  # the correction carries the schema

    asyncio.run(slide_content.get_slide_content_from_type_and_outline(layout, outline, "English"))
    assert '"maxLength": 40' in _system_text(client.calls[2])  # and later calls embed it up front


# --------------------------------------------------------------------------- layout cache


def test_layout_lookup_compiles_once_per_fingerprint(monkeypatch):
    fingerprint = {"value": "general:1:3:100"}
    fetch = AsyncMock(return_value=_layout().model_dump())
    monkeypatch.setattr(layout_lookup, "_template_fingerprint", lambda _name: fingerprint["value"])
    monkeypatch.setattr(layout_lookup, "_fetch_template_payload", fetch)
    layout_lookup.clear_layout_cache()

    async def run():
        first = await layout_lookup.get_layout_by_name("general")
        first.slides.pop()  # callers get a copy; mutating it must not touch the cache
        second = await layout_lookup.get_layout_by_name("general")
        assert len(second.slides) == 3
        assert fetch.await_count == 1
        fingerprint["value"] = "general:1:3:200"  # a layout file changed
        await layout_lookup.get_layout_by_name("general")
        assert fetch.await_count == 2

    asyncio.run(run())
    layout_lookup.clear_layout_cache()


def test_layout_lookup_calls_nextjs_directly(monkeypatch):
    monkeypatch.setenv("CHATPPT_NEXTJS_URL", "http://127.0.0.1:3999/")
    from utils.internal_urls import nextjs_base_url

    assert nextjs_base_url() == "http://127.0.0.1:3999"
    monkeypatch.delenv("CHATPPT_NEXTJS_URL")
    assert nextjs_base_url() == "http://127.0.0.1:3000"


# --------------------------------------------------------------------------- prompts as files


@pytest.mark.parametrize(
    "name",
    [
        "outline.system",
        "outline.user",
        "outline.layouts",
        "structure.system",
        "structure.user",
        "structure_from_markdown.system",
        "edit_slide.system",
        "edit_slide.user",
        "edit_slide_html.system",
        "edit_slide_html.user",
        "select_slide_layout.system",
        "select_slide_layout.user",
    ],
)
def test_generation_prompts_ship_as_files(name):
    assert (BUILTIN_DIR / f"{name}.md").is_file()
    assert render_prompt(name, override_dir=BUILTIN_DIR / "__none__").strip()


def test_llm_calls_have_no_inline_prompts():
    from pathlib import Path

    calls_dir = Path(slide_content.__file__).parent
    for path in calls_dir.glob("*.py"):
        assert 'prompt = """' not in path.read_text(), path.name
