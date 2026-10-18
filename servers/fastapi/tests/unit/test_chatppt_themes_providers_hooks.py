"""Theme files, provider files in <data>/providers, and <data>/hooks.py."""

import asyncio
import logging
import os
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import chatppt.settings as settings_mod
from chatppt import config_store, hooks
from chatppt.providers import plugins, registry
from chatppt.providers.routing import resolve_llm
from chatppt.settings import apply_to_environ, reload_settings
from chatppt.themes import default_presentation_theme


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("CHATPPT_") or name in config_store.UI_KEYS or name == "USER_CONFIG_PATH":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(settings_mod, "_loaded", None)
    monkeypatch.setattr(settings_mod, "RECHECK_SECONDS", 0.0)
    monkeypatch.setitem(settings_mod._bridge, "active", False)
    registry.llm_providers()  # built-ins in, so the snapshot below holds only them
    monkeypatch.setattr(registry, "_LLM", dict(registry._LLM))
    monkeypatch.setattr(registry, "_IMAGES", dict(registry._IMAGES))
    yield tmp_path
    settings_mod.restore_environ()
    settings_mod._loaded = None


def write(path: Path, text: str) -> Path:
    """Write and move the mtime forward, so mtime-based reloads see the change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    later = time.time() + 10 + len(text) % 7
    os.utime(path, (later, later))
    return path


# ---- themes ------------------------------------------------------------------------------


def test_defaults_theme_applies_to_new_decks(data_dir):
    assert default_presentation_theme() is None  # no theme: each template keeps its colours
    write(data_dir / "themes" / "desk.json", '{"name": "Desk", "colors": {"primary": "#ff8800"}}')
    write(data_dir / "chatppt.toml", '[defaults]\ntheme = "desk"\n')
    theme = default_presentation_theme()
    assert theme is not None and theme["id"] == "desk"
    assert theme["data"]["colors"]["primary"] == "#ff8800" and "graph_9" in theme["data"]["colors"]

    write(data_dir / "chatppt.toml", '[defaults]\ntheme = "missing"\n')
    assert default_presentation_theme() is None


def test_theme_files_are_served_with_the_built_in_shape(data_dir):
    from api.v1.ppt.endpoints.theme import get_default_themes

    write(data_dir / "themes" / "desk.json", '{"name": "Desk", "font": {"name": "IBM Plex Sans"}}')
    served = {t.id: t for t in asyncio.run(get_default_themes())}
    assert {"graphite", "desk"} <= set(served)
    assert served["desk"].data["fonts"]["textFont"] == {"name": "IBM Plex Sans", "url": ""}
    assert served["desk"].user == "system"


# ---- providers ---------------------------------------------------------------------------

PROVIDER_FILE = """
from pathlib import Path

from chatppt.providers import ImageProviderSpec, LLMProviderSpec, register_image, register_llm
from llmai.shared import OpenAIClientConfig


def build(creds):
    return OpenAIClientConfig(base_url=creds.base_url or "http://lab.invalid/v1", api_key=creds.api_key or "x")


async def generate(prompt, output_dir):
    path = Path(output_dir) / "lab.png"
    path.write_text(prompt)
    return str(path)


register_llm(LLMProviderSpec("lab", "Lab model", "lab-1", build))
register_image(ImageProviderSpec("lab-images", "Lab images", "generative", generate=generate))
"""


def test_provider_file_registers_llm_and_image_backends(data_dir, tmp_path):
    write(data_dir / "providers" / "lab.py", PROVIDER_FILE)
    write(
        data_dir / "chatppt.toml",
        '[llm]\nprovider = "lab"\n[llm.providers.lab]\napi_key = "k"\n[images]\nprovider = "lab-images"\n',
    )
    assert "lab" in registry.llm_providers() and "lab-images" in registry.image_providers()

    resolved = resolve_llm("outline")
    assert (resolved.provider, resolved.model, resolved.config.api_key) == ("lab", "lab-1", "k")
    assert plugins.plugin_llm_selected()

    run = plugins.selected_image_plugin()
    assert run is not None
    out = tmp_path / "out"
    out.mkdir()
    assert Path(asyncio.run(run("a chart", str(out)))).read_text() == "a chart"

    # Upstream code never sees an id it cannot parse.
    written = apply_to_environ(reload_settings())
    assert "LLM" not in written and "IMAGE_PROVIDER" not in written


def test_image_service_uses_provider_file(data_dir, monkeypatch):
    from services.image_generation_service import ImageGenerationService

    write(data_dir / "providers" / "lab.py", PROVIDER_FILE)
    write(data_dir / "chatppt.toml", '[images]\nprovider = "lab-images"\n')
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", "false")
    service = ImageGenerationService(str(data_dir))
    assert service.image_gen_func is not None
    assert Path(asyncio.run(service.image_gen_func("x", str(data_dir)))).name == "lab.png"


def test_openai_compatible_backend_needs_only_toml(data_dir):
    write(
        data_dir / "chatppt.toml",
        '[llm]\nprovider = "vllm-box"\nmodel = "qwen"\n'
        '[llm.providers.vllm-box]\nbase_url = "http://10.0.0.5:8000/v1"\napi_key = "secret"\n',
    )
    resolved = resolve_llm("content")
    assert (resolved.provider, resolved.model) == ("vllm-box", "qwen")
    assert resolved.config.base_url == "http://10.0.0.5:8000/v1"
    assert not plugins.plugin_llm_selected()  # bridged to upstream's "custom" provider instead
    env: dict[str, str] = {}
    apply_to_environ(reload_settings(), env)
    assert env["LLM"] == "custom" and env["CUSTOM_LLM_URL"] == "http://10.0.0.5:8000/v1"


def test_unknown_provider_without_base_url_is_a_clear_error(data_dir):
    write(data_dir / "chatppt.toml", '[llm]\nprovider = "nope"\n')
    with pytest.raises(HTTPException) as err:
        resolve_llm("outline")
    assert err.value.status_code == 400 and "nope" in str(err.value.detail)


def test_broken_provider_file_is_skipped(data_dir, caplog):
    write(data_dir / "providers" / "bad.py", "raise RuntimeError('boom')\n")
    with caplog.at_level(logging.ERROR):
        providers = registry.llm_providers()
    assert "openai" in providers
    assert "bad.py failed to load" in caplog.text


# ---- hooks -------------------------------------------------------------------------------


def test_missing_hooks_file_is_a_no_op(data_dir):
    slide = {"title": "x"}
    assert asyncio.run(hooks.run_hook("after_slide", slide)) is slide


def test_hooks_change_values_and_reload_when_edited(data_dir):
    path = write(
        data_dir / "hooks.py",
        "def after_slide(slide):\n    slide['title'] = slide['title'].upper()\n",
    )
    assert asyncio.run(hooks.run_hook("after_slide", {"title": "q3"})) == {"title": "Q3"}

    write(path, "async def after_slide(slide):\n    return {'replaced': True}\n")
    assert asyncio.run(hooks.run_hook("after_slide", {"title": "q3"})) == {"replaced": True}


def test_hook_errors_are_logged_never_raised(data_dir, caplog):
    write(data_dir / "hooks.py", "def before_export(deck):\n    raise ValueError('nope')\n")
    deck = {"slides": []}
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(hooks.run_hook("before_export", deck)) is deck
    assert "before_export raised" in caplog.text

    write(data_dir / "hooks.py", "def after_export(path:\n")  # syntax error
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(hooks.run_hook("after_export", "/x.pptx")) == "/x.pptx"
    assert "failed to load" in caplog.text


def test_before_outline_decorator_rewrites_the_request(data_dir):
    write(
        data_dir / "hooks.py",
        "def before_outline(request):\n"
        "    request['instructions'] = 'House style: no adjectives.'\n"
        "    request['unknown'] = 1\n"
        "    return request\n",
    )
    seen = {}

    @hooks.before_outline
    async def outline(content, n_slides, instructions=None):
        seen.update(content=content, n_slides=n_slides, instructions=instructions)
        yield "chunk"

    async def collect():
        return [chunk async for chunk in outline("Q3 review", 5)]

    assert asyncio.run(collect()) == ["chunk"]
    assert seen == {"content": "Q3 review", "n_slides": 5, "instructions": "House style: no adjectives."}


def test_after_export_endpoint_only_accepts_exported_files(data_dir):
    from api.v1.hooks.router import after_export

    write(
        data_dir / "hooks.py", f"def after_export(path):\n    open({str(data_dir / 'seen.txt')!r}, 'w').write(path)\n"
    )
    exported = write(data_dir / "exports" / "deck.pptx", "pptx")
    asyncio.run(after_export(path=str(exported)))
    assert (data_dir / "seen.txt").read_text() == str(exported.resolve())
    with pytest.raises(HTTPException):
        asyncio.run(after_export(path=str(data_dir / "hooks.py")))
