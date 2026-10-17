import json
import os
import tomllib
from pathlib import Path

import pytest

import chatppt.settings as settings_mod
from chatppt import config_store
from chatppt.config_store import (
    dump_toml,
    migrate_user_config_json,
    save_ui_values,
    ui_changes,
    ui_values,
    update_config,
)
from chatppt.settings import apply_to_environ, get_settings, load_settings, reload_settings


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """An isolated data folder, with the env bridge and settings cache reset afterwards."""
    for name in list(os.environ):
        if name.startswith("CHATPPT_") or name in config_store.UI_KEYS or name == "USER_CONFIG_PATH":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(settings_mod, "_loaded", None)
    monkeypatch.setitem(settings_mod._bridge, "active", False)
    yield tmp_path
    settings_mod.restore_environ()
    settings_mod._loaded = None


def test_dump_toml_round_trips():
    data = {
        "llm": {
            "provider": "openai",
            "thinking": False,
            "providers": {"openai": {"api_key": 'sk-"quoted"'}},
            "routing": {"outline": {"model": "mini"}},
        },
        "images": {"providers": {"gpt-image-1.5": {"quality": "high"}}},
        "defaults": {"n_slides": 8},
    }
    assert tomllib.loads(dump_toml(data)) == data


def test_update_config_writes_atomically_keeps_backup_and_reloads(data_dir):
    path = data_dir / "chatppt.toml"
    path.write_text('# hand-written\n[llm]\nprovider = "anthropic"\n')
    settings = update_config({"llm.provider": "openai", "llm.providers.openai.api_key": "sk-1"})
    assert settings.llm.provider == "openai"
    assert get_settings().llm.providers["openai"].api_key == "sk-1"
    assert (data_dir / "chatppt.toml.bak").read_text().startswith("# hand-written")
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    update_config({"llm.providers.openai.api_key": None})
    raw = tomllib.loads(path.read_text())
    assert "providers" not in raw["llm"]  # emptied tables are pruned


def test_settings_reload_when_file_changes(data_dir, monkeypatch):
    path = data_dir / "chatppt.toml"
    path.write_text('[defaults]\ntemplate = "general"\n')
    assert get_settings().defaults.template == "general"
    path.write_text('[defaults]\ntemplate = "house"\n')
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    monkeypatch.setattr(settings_mod, "RECHECK_SECONDS", 0.0)
    assert get_settings().defaults.template == "house"


def test_bridge_exports_and_withdraws_keys(data_dir):
    path = data_dir / "chatppt.toml"
    path.write_text('[llm]\nprovider = "openai"\n[llm.providers.openai]\napi_key = "sk-toml"\n')
    apply_to_environ(reload_settings())
    assert os.environ["OPENAI_API_KEY"] == "sk-toml"
    update_config({"llm.providers.openai.api_key": None})
    assert "OPENAI_API_KEY" not in os.environ  # not left behind as a stale legacy variable
    assert os.environ["LLM"] == "openai"


def test_bridge_restores_a_real_legacy_env_value(data_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    (data_dir / "chatppt.toml").write_text('[llm.providers.openai]\nmodel = "from-toml"\n')
    apply_to_environ(reload_settings())
    assert os.environ["OPENAI_MODEL"] == "from-toml"
    update_config({"llm.providers.openai.model": None})
    assert os.environ["OPENAI_MODEL"] == "from-env"
    assert get_settings().llm.providers["openai"].model == "from-env"


def test_toml_only_openai_compatible_provider_is_exported_as_custom(data_dir):
    (data_dir / "chatppt.toml").write_text(
        """
[llm]
provider = "vllm"
model = "qwen3"
[llm.providers.vllm]
base_url = "http://gpu-box:8000/v1"
api_key = "local"
[images]
provider = "flux"
[images.providers.flux]
base_url = "http://gpu-box:9000/v1"
api_key = "local"
model = "flux-dev"
"""
    )
    written = apply_to_environ(reload_settings())
    assert os.environ["LLM"] == "custom"
    assert os.environ["CUSTOM_LLM_URL"] == "http://gpu-box:8000/v1"
    assert os.environ["CUSTOM_MODEL"] == "qwen3"
    assert os.environ["IMAGE_PROVIDER"] == "openai_compatible"
    assert os.environ["OPENAI_COMPAT_IMAGE_MODEL"] == "flux-dev"
    assert "CUSTOM_LLM_API_KEY" in written


def test_ui_values_and_changes_only_write_what_differs(data_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    settings = reload_settings()
    view = ui_values(settings)
    assert view["ANTHROPIC_API_KEY"] == "sk-ant-env"
    assert view["DISABLE_IMAGE_GENERATION"] is False

    incoming = dict(view, LLM="openai", OPENAI_API_KEY="sk-new", DISABLE_IMAGE_GENERATION=True, USE_CUSTOM_URL=True)
    changes = ui_changes(incoming, settings)
    assert changes == {"llm.provider": "openai", "llm.providers.openai.api_key": "sk-new", "features.images": False}

    saved = save_ui_values(incoming)
    assert saved.llm.provider == "openai" and saved.features.images is False
    raw = tomllib.loads((data_dir / "chatppt.toml").read_text())
    assert "anthropic" not in raw["llm"].get("providers", {})  # env-provided value stays in env

    cleared = save_ui_values({"OPENAI_API_KEY": ""})
    assert cleared.llm.providers.get("openai") is None or cleared.llm.providers["openai"].api_key is None


def test_migrate_user_config_json_once(data_dir, monkeypatch):
    source = data_dir / "userConfig.json"
    source.write_text(
        json.dumps(
            {
                "LLM": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant-ui",
                "OPENAI_API_KEY": "sk-from-env-copy",
                "DISABLE_IMAGE_GENERATION": True,
                "AUTH_USERNAME": "admin",
                "CODEX_ACCESS_TOKEN": "tok",
            }
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-copy")
    migrated = migrate_user_config_json(reload_settings())
    assert migrated == ["llm.provider", "llm.providers.anthropic.api_key"]
    raw = tomllib.loads((data_dir / "chatppt.toml").read_text())
    assert raw == {"llm": {"provider": "anthropic", "providers": {"anthropic": {"api_key": "sk-ant-ui"}}}}
    assert (data_dir / "userConfig.json.migrated").is_file()
    assert source.is_file()  # login and Codex tokens still live there

    source.write_text(json.dumps({"LLM": "google"}))
    assert migrate_user_config_json(get_settings()) == []
    assert get_settings().llm.provider == "anthropic"


def test_migration_never_overrides_the_toml(data_dir):
    (data_dir / "chatppt.toml").write_text('[llm]\nprovider = "openai"\n')
    (data_dir / "userConfig.json").write_text(json.dumps({"LLM": "anthropic", "ANTHROPIC_MODEL": "x"}))
    assert migrate_user_config_json(reload_settings()) == ["llm.providers.anthropic.model"]
    assert get_settings().llm.provider == "openai"


def test_load_settings_reads_written_file(tmp_path: Path):
    path = tmp_path / "chatppt.toml"
    config_store.write_toml(path, {"server": {"log_level": "debug"}})
    assert load_settings(path, environ={}).server.log_level == "debug"
