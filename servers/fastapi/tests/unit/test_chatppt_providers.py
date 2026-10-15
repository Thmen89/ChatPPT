import pytest
from fastapi import HTTPException

from chatppt.providers import llm_providers, image_providers, resolve_llm
from chatppt.settings import load_settings


def settings_from(tmp_path, text: str, environ: dict | None = None):
    path = tmp_path / "chatppt.toml"
    path.write_text(text)
    return load_settings(path, environ=environ or {})


def test_registry_covers_upstream_providers():
    ids = set(llm_providers())
    assert {"openai", "anthropic", "google", "vertex", "azure", "bedrock", "openrouter", "fireworks",
            "together", "cerebras", "litellm", "lmstudio", "ollama", "custom", "codex"} <= ids
    assert {"pexels", "pixabay", "gemini_flash", "dall-e-3", "gpt-image-1.5", "comfyui",
            "open_webui", "openai_compatible", "nanobanana_pro"} <= set(image_providers())


def test_resolve_default_and_routed_steps(tmp_path):
    s = settings_from(tmp_path, """
[llm]
provider = "openai"
model = "gpt-4.1"
[llm.providers.openai]
api_key = "sk-test"
[llm.providers.anthropic]
api_key = "sk-ant"
[llm.providers.ollama]
model = "llama3"
[llm.routing]
outline = { model = "gpt-4.1-mini" }
content = { provider = "anthropic" }
edit = { provider = "ollama" }
""")
    default = resolve_llm(None, s)
    assert (default.provider, default.model, default.source) == ("openai", "gpt-4.1", "settings")
    assert default.config.api_key == "sk-test"

    outline = resolve_llm("outline", s)
    assert (outline.provider, outline.model, outline.source) == ("openai", "gpt-4.1-mini", "routing")

    content = resolve_llm("content", s)
    assert content.provider == "anthropic"
    assert content.model == "claude-sonnet-4-20250514"  # provider default, not [llm].model
    assert content.config.provider == "anthropic"

    edit = resolve_llm("edit", s)
    assert edit.provider == "ollama" and edit.model == "llama3"
    assert edit.config.base_url == "http://localhost:11434/v1"

    structure = resolve_llm("structure", s)
    assert (structure.provider, structure.model) == ("openai", "gpt-4.1")


def test_missing_credentials_are_a_plain_400(tmp_path):
    s = settings_from(tmp_path, '[llm]\nprovider = "anthropic"\n')
    with pytest.raises(HTTPException) as exc:
        resolve_llm("content", s)
    assert exc.value.status_code == 400
    assert "llm.providers.anthropic.api_key" in exc.value.detail


def test_unknown_provider_and_step(tmp_path):
    s = settings_from(tmp_path, '[llm]\nprovider = "nope"\n')
    with pytest.raises(HTTPException) as exc:
        resolve_llm(None, s)
    assert "unknown LLM provider" in exc.value.detail
    with pytest.raises(ValueError):
        resolve_llm("bogus", s)


def test_legacy_env_falls_back_to_upstream_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM", "custom")
    monkeypatch.setenv("CUSTOM_LLM_URL", "http://127.0.0.1:9900/v1")
    monkeypatch.setenv("CUSTOM_MODEL", "mock")
    s = load_settings(tmp_path / "none.toml")  # reads os.environ: legacy names only
    assert not s.is_explicit("llm.provider")
    resolved = resolve_llm("content", s)
    assert resolved.source == "legacy"
    assert resolved.provider == "custom" and resolved.model == "mock"
    assert resolved.config.base_url == "http://127.0.0.1:9900/v1"
