from pathlib import Path

from chatppt.settings import (
    Settings,
    apply_to_environ,
    load_settings,
    render_reference,
    to_legacy_env,
)


def write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "chatppt.toml"
    path.write_text(text)
    return path


def test_defaults_without_file(tmp_path):
    s = load_settings(tmp_path / "missing.toml", environ={"APP_DATA_DIRECTORY": str(tmp_path)})
    assert s.source_path is None
    assert s.server.data_dir == str(tmp_path)
    assert s.llm.provider is None
    assert s.templates_dir == tmp_path / "templates"
    assert s.prompts_dir == tmp_path / "prompts"
    assert s.features.memory is False
    assert not s.is_explicit("llm.provider")


def test_toml_values_and_routing(tmp_path):
    path = write_toml(tmp_path, """
[llm]
provider = "openai"
model = "gpt-4.1"
[llm.providers.openai]
api_key = "sk-test"
[llm.providers.anthropic]
api_key = "sk-ant"
[llm.routing]
outline = { model = "gpt-4.1-mini" }
content = { provider = "anthropic", model = "claude-sonnet-4-20250514" }
[features]
memory = true
""")
    s = load_settings(path, environ={})
    assert s.source_path == str(path)
    assert s.llm.provider == "openai"
    assert s.llm.providers["openai"].api_key == "sk-test"
    assert s.llm.routing["outline"].model == "gpt-4.1-mini"
    assert s.llm.routing["content"].provider == "anthropic"
    assert s.features.memory is True
    assert s.is_explicit("llm.provider") and s.is_explicit("llm.routing.content.provider")


def test_env_overrides_file(tmp_path):
    path = write_toml(tmp_path, '[llm]\nprovider = "openai"\n[server]\nlog_level = "info"\n')
    env = {
        "CHATPPT_LLM__PROVIDER": "anthropic",
        "CHATPPT_LLM__PROVIDERS__ANTHROPIC__API_KEY": "sk-ant",
        "CHATPPT_FEATURES__CHAT": "false",
        "CHATPPT_DEFAULTS__N_SLIDES": "7",
    }
    s = load_settings(path, environ=env)
    assert s.llm.provider == "anthropic"
    assert s.llm.providers["anthropic"].api_key == "sk-ant"
    assert s.features.chat is False
    assert s.defaults.n_slides == 7
    assert s.server.log_level == "info"


def test_legacy_env_is_mapped_but_not_explicit(tmp_path):
    env = {
        "APP_DATA_DIRECTORY": str(tmp_path),
        "LLM": "google",
        "GOOGLE_API_KEY": "g-key",
        "GOOGLE_MODEL": "models/gemini-2.5-pro",
        "DISABLE_IMAGE_GENERATION": "true",
        "DISABLE_THINKING": "true",
        "MEM0_ENABLED": "false",
    }
    s = load_settings(tmp_path / "none.toml", environ=env)
    assert s.llm.provider == "google"
    assert s.llm.providers["google"].api_key == "g-key"
    assert s.llm.providers["google"].model == "models/gemini-2.5-pro"
    assert s.features.images is False
    assert s.llm.thinking is False
    assert s.features.memory is False
    # Legacy values are not "explicit": routing keeps using the upstream path for them.
    assert not s.is_explicit("llm.provider")


def test_file_wins_over_legacy_env(tmp_path):
    path = write_toml(tmp_path, '[llm]\nprovider = "openai"\n')
    s = load_settings(path, environ={"LLM": "google"})
    assert s.llm.provider == "openai"


def test_legacy_round_trip(tmp_path):
    path = write_toml(tmp_path, """
[llm]
provider = "openai"
thinking = false
[llm.providers.openai]
api_key = "sk-test"
model = "gpt-4.1"
[images]
provider = "pexels"
[images.providers.pexels]
api_key = "px"
[features]
images = false
[auth]
disabled = true
""")
    s = load_settings(path, environ={})
    legacy = to_legacy_env(s)
    assert legacy["LLM"] == "openai"
    assert legacy["OPENAI_API_KEY"] == "sk-test"
    assert legacy["OPENAI_MODEL"] == "gpt-4.1"
    assert legacy["DISABLE_THINKING"] == "true"
    assert legacy["IMAGE_PROVIDER"] == "pexels"
    assert legacy["PEXELS_API_KEY"] == "px"
    assert legacy["DISABLE_IMAGE_GENERATION"] == "true"
    assert legacy["DISABLE_AUTH"] == "true"

    environ: dict[str, str] = {}
    written = apply_to_environ(s, environ)
    assert set(written) == {"LLM", "DISABLE_THINKING", "OPENAI_API_KEY", "OPENAI_MODEL", "IMAGE_PROVIDER",
                            "PEXELS_API_KEY", "DISABLE_IMAGE_GENERATION", "DISABLE_AUTH"}
    # Defaults are not exported: only what the file set.
    assert "MEM0_ENABLED" not in environ


def test_reference_lists_every_leaf_and_legacy_name():
    text = render_reference()
    assert "| `llm.provider` |" in text and "legacy `LLM`" in text
    assert "`llm.providers.<id>.api_key`" in text
    assert "`CHATPPT_FEATURES__MEMORY`" in text
    for field in Settings.model_fields:
        if field not in {"source_path", "explicit"}:
            assert f"`{field}." in text
