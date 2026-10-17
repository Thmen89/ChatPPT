"""One config file: ``<data>/chatppt.toml``.

Precedence, highest first:

1. ``CHATPPT_*`` environment variables (``CHATPPT_LLM__PROVIDER=openai``,
   ``CHATPPT_LLM__PROVIDERS__OPENAI__API_KEY=sk-...``; ``__`` separates levels).
2. ``chatppt.toml`` (path from ``CHATPPT_CONFIG`` or ``<data>/chatppt.toml``).
3. Legacy Presenton environment variables (``LLM``, ``OPENAI_API_KEY``, ...). They keep
   working and log one warning naming the new key.
4. Defaults below.

``python -m chatppt --reference`` prints the config reference that
``docs/config-reference.md`` is generated from.
"""

from __future__ import annotations

import logging
import os
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger(__name__)

ENV_PREFIX = "CHATPPT_"
CONFIG_FILE_NAME = "chatppt.toml"
STEPS = ("outline", "structure", "content", "edit", "chat", "template")
IconWeight = Literal["bold", "duotone", "fill", "light", "regular", "thin"]


# --------------------------------------------------------------------------- schema


class ProviderCredentials(BaseModel):
    """Credentials and endpoint for one LLM or image provider.

    Unknown keys are kept, so a provider added in one file can read its own settings.
    """

    model_config = ConfigDict(extra="allow")

    api_key: str | None = Field(default=None, description="API key or token.")
    base_url: str | None = Field(
        default=None, description="Endpoint override (OpenAI-compatible servers, proxies, Ollama, LM Studio)."
    )
    model: str | None = Field(default=None, description="Default model when this provider is used.")
    # Azure OpenAI
    endpoint: str | None = Field(default=None, description="Azure OpenAI resource endpoint.")
    api_version: str | None = Field(default=None, description="Azure OpenAI API version.")
    deployment: str | None = Field(default=None, description="Azure OpenAI deployment name.")
    # Vertex AI
    project: str | None = Field(default=None, description="Google Cloud project (Vertex).")
    location: str | None = Field(default=None, description="Google Cloud region (Vertex).")
    # Bedrock
    region: str | None = Field(default=None, description="AWS region (Bedrock).")
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    profile_name: str | None = Field(default=None, description="AWS profile name (Bedrock).")
    # Image providers
    quality: str | None = Field(default=None, description="Image quality preset where the provider has one.")
    workflow: str | None = Field(default=None, description="ComfyUI workflow JSON path.")


class StepRoute(BaseModel):
    """Which provider/model handles one generation step; unset fields fall back to [llm]."""

    provider: str | None = None
    model: str | None = None


class LLMSettings(BaseModel):
    provider: str | None = Field(
        default=None,
        description="Default LLM provider id: openai, anthropic, google, vertex, azure, bedrock, openrouter, fireworks, together, cerebras, litellm, lmstudio, ollama, custom, codex.",
    )
    model: str | None = Field(default=None, description="Default model for the default provider.")
    thinking: bool = Field(default=True, description="Allow reasoning/thinking on models that support it.")
    extended_reasoning: bool = Field(default=False, description="Ask for longer reasoning where supported.")
    providers: dict[str, ProviderCredentials] = Field(
        default_factory=dict, description="Per-provider credentials, keyed by provider id."
    )
    routing: dict[str, StepRoute] = Field(
        default_factory=dict, description=f"Per-step overrides, keys: {', '.join(STEPS)}."
    )


class ImageSettings(BaseModel):
    provider: str | None = Field(
        default=None,
        description="Image provider id: pexels, pixabay, gemini_flash, nanobanana_pro, dall-e-3, gpt-image-1.5, comfyui, open_webui, openai_compatible. Unset means placeholder images.",
    )
    providers: dict[str, ProviderCredentials] = Field(
        default_factory=dict, description="Per-image-provider credentials, keyed by provider id."
    )


class FeatureSettings(BaseModel):
    images: bool = Field(default=True, description="Generate or fetch images when an image provider is configured.")
    chat: bool = Field(default=True, description="Chat-with-deck panel.")
    memory: bool = Field(default=False, description="mem0 long-term memory for chat (needs spaCy/NLTK data; heavy).")
    ocr: bool = Field(default=False, description="OCR scanned PDFs with Tesseract when installed.")
    web_search: bool = Field(default=False, description="Provider-side web grounding when supported.")
    update_check: bool = Field(default=False, description="Desktop app checks for new releases.")


class ServerSettings(BaseModel):
    public_url: str = Field(
        default="http://localhost:5000", description="URL users open; used for links, CORS and the exporter."
    )
    data_dir: str = Field(
        default="/data", description="Where the database, uploads, exports, templates, prompts and this file live."
    )
    database_url: str | None = Field(
        default=None, description="SQLAlchemy URL. Default is SQLite in data_dir; set postgresql://... to opt in."
    )
    log_level: str = Field(default="info", description="debug, info, warning or error.")
    error_reporting_dsn: str | None = Field(
        default=None, description="Sentry-compatible DSN. Unset means no error reporting at all."
    )


class AuthSettings(BaseModel):
    disabled: bool = Field(default=False, description="Turn login off entirely (single-user, trusted network).")


class PathSettings(BaseModel):
    templates: str | None = Field(default=None, description="Template folders. Default <data>/templates.")
    prompts: str | None = Field(default=None, description="Prompt overrides. Default <data>/prompts.")
    themes: str | None = Field(default=None, description="Theme files. Default <data>/themes.")


class GenerationDefaults(BaseModel):
    template: str = Field(default="general", description="Template used when a request names none.")
    theme: str | None = Field(
        default=None,
        description="Theme applied to new decks (<data>/themes/<id>.json); unset keeps each template's colours.",
    )
    n_slides: int = Field(default=10, ge=1, le=50)
    language: str | None = Field(default=None, description="Default output language; unset lets the model detect it.")
    tone: str = Field(default="default")
    verbosity: str = Field(default="standard", description="concise, standard or text-heavy.")


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    images: ImageSettings = Field(default_factory=ImageSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    defaults: GenerationDefaults = Field(default_factory=GenerationDefaults)

    source_path: str | None = Field(default=None, exclude=True, description="File the settings were read from, if any.")
    explicit: set[str] = Field(
        default_factory=set,
        exclude=True,
        description="Dotted keys set by chatppt.toml or CHATPPT_* (not by legacy env or defaults).",
    )

    @property
    def data_dir(self) -> Path:
        return Path(self.server.data_dir)

    @property
    def templates_dir(self) -> Path:
        return Path(self.paths.templates) if self.paths.templates else self.data_dir / "templates"

    @property
    def prompts_dir(self) -> Path:
        return Path(self.paths.prompts) if self.paths.prompts else self.data_dir / "prompts"

    @property
    def themes_dir(self) -> Path:
        return Path(self.paths.themes) if self.paths.themes else self.data_dir / "themes"

    def is_explicit(self, dotted: str) -> bool:
        return dotted in self.explicit


# --------------------------------------------------------------------------- legacy env map


def _bool_from_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _inverted_bool(value: str) -> bool:
    return not _bool_from_env(value)


def _bool_to_env(value: Any) -> str:
    return "true" if value else "false"


def _inverted_bool_to_env(value: Any) -> str:
    return "false" if value else "true"


@dataclass(frozen=True)
class Legacy:
    env: str
    path: str
    parse: Callable[[str], Any] = str
    to_env: Callable[[Any], str] = str


def _provider_legacy(
    prefix: str, provider: str, *, model_env: str | None = None, base_url_env: str | None = None
) -> list[Legacy]:
    out = [Legacy(f"{prefix}_API_KEY", f"llm.providers.{provider}.api_key")]
    out.append(Legacy(model_env or f"{prefix}_MODEL", f"llm.providers.{provider}.model"))
    if base_url_env:
        out.append(Legacy(base_url_env, f"llm.providers.{provider}.base_url"))
    return out


LEGACY_ENV: tuple[Legacy, ...] = (
    Legacy("APP_DATA_DIRECTORY", "server.data_dir"),
    Legacy("NEXT_PUBLIC_URL", "server.public_url"),
    Legacy("DATABASE_URL", "server.database_url"),
    Legacy("LOG_LEVEL", "server.log_level"),
    Legacy("SENTRY_DSN", "server.error_reporting_dsn"),
    Legacy("DISABLE_AUTH", "auth.disabled", _bool_from_env, _bool_to_env),
    Legacy("LLM", "llm.provider"),
    Legacy("DISABLE_THINKING", "llm.thinking", _inverted_bool, _inverted_bool_to_env),
    Legacy("EXTENDED_REASONING", "llm.extended_reasoning", _bool_from_env, _bool_to_env),
    *_provider_legacy("OPENAI", "openai"),
    *_provider_legacy("ANTHROPIC", "anthropic"),
    *_provider_legacy("GOOGLE", "google"),
    *_provider_legacy("OPENROUTER", "openrouter", base_url_env="OPENROUTER_BASE_URL"),
    *_provider_legacy("FIREWORKS", "fireworks", base_url_env="FIREWORKS_BASE_URL"),
    *_provider_legacy("TOGETHER", "together", base_url_env="TOGETHER_BASE_URL"),
    *_provider_legacy("CEREBRAS", "cerebras", base_url_env="CEREBRAS_BASE_URL"),
    *_provider_legacy("LITELLM", "litellm", base_url_env="LITELLM_BASE_URL"),
    *_provider_legacy("LMSTUDIO", "lmstudio", base_url_env="LMSTUDIO_BASE_URL"),
    Legacy("OLLAMA_URL", "llm.providers.ollama.base_url"),
    Legacy("OLLAMA_MODEL", "llm.providers.ollama.model"),
    Legacy("CUSTOM_LLM_URL", "llm.providers.custom.base_url"),
    Legacy("CUSTOM_LLM_API_KEY", "llm.providers.custom.api_key"),
    Legacy("CUSTOM_MODEL", "llm.providers.custom.model"),
    Legacy("CODEX_MODEL", "llm.providers.codex.model"),
    Legacy("VERTEX_API_KEY", "llm.providers.vertex.api_key"),
    Legacy("VERTEX_MODEL", "llm.providers.vertex.model"),
    Legacy("VERTEX_PROJECT", "llm.providers.vertex.project"),
    Legacy("VERTEX_LOCATION", "llm.providers.vertex.location"),
    Legacy("VERTEX_BASE_URL", "llm.providers.vertex.base_url"),
    Legacy("AZURE_OPENAI_API_KEY", "llm.providers.azure.api_key"),
    Legacy("AZURE_OPENAI_MODEL", "llm.providers.azure.model"),
    Legacy("AZURE_OPENAI_ENDPOINT", "llm.providers.azure.endpoint"),
    Legacy("AZURE_OPENAI_BASE_URL", "llm.providers.azure.base_url"),
    Legacy("AZURE_OPENAI_API_VERSION", "llm.providers.azure.api_version"),
    Legacy("AZURE_OPENAI_DEPLOYMENT", "llm.providers.azure.deployment"),
    Legacy("BEDROCK_REGION", "llm.providers.bedrock.region"),
    Legacy("BEDROCK_API_KEY", "llm.providers.bedrock.api_key"),
    Legacy("BEDROCK_MODEL", "llm.providers.bedrock.model"),
    Legacy("BEDROCK_AWS_ACCESS_KEY_ID", "llm.providers.bedrock.aws_access_key_id"),
    Legacy("BEDROCK_AWS_SECRET_ACCESS_KEY", "llm.providers.bedrock.aws_secret_access_key"),
    Legacy("BEDROCK_AWS_SESSION_TOKEN", "llm.providers.bedrock.aws_session_token"),
    Legacy("BEDROCK_PROFILE_NAME", "llm.providers.bedrock.profile_name"),
    Legacy("IMAGE_PROVIDER", "images.provider"),
    Legacy("DISABLE_IMAGE_GENERATION", "features.images", _inverted_bool, _inverted_bool_to_env),
    Legacy("PEXELS_API_KEY", "images.providers.pexels.api_key"),
    Legacy("PIXABAY_API_KEY", "images.providers.pixabay.api_key"),
    Legacy("DALL_E_3_QUALITY", "images.providers.dall-e-3.quality"),
    Legacy("GPT_IMAGE_1_5_QUALITY", "images.providers.gpt-image-1.5.quality"),
    Legacy("COMFYUI_URL", "images.providers.comfyui.base_url"),
    Legacy("COMFYUI_WORKFLOW", "images.providers.comfyui.workflow"),
    Legacy("OPEN_WEBUI_IMAGE_URL", "images.providers.open_webui.base_url"),
    Legacy("OPEN_WEBUI_IMAGE_API_KEY", "images.providers.open_webui.api_key"),
    Legacy("OPENAI_COMPAT_IMAGE_BASE_URL", "images.providers.openai_compatible.base_url"),
    Legacy("OPENAI_COMPAT_IMAGE_API_KEY", "images.providers.openai_compatible.api_key"),
    Legacy("OPENAI_COMPAT_IMAGE_MODEL", "images.providers.openai_compatible.model"),
    Legacy("MEM0_ENABLED", "features.memory", _bool_from_env, _bool_to_env),
    Legacy("WEB_GROUNDING", "features.web_search", _bool_from_env, _bool_to_env),
)

LEGACY_BY_PATH: dict[str, Legacy] = {entry.path: entry for entry in LEGACY_ENV}


# --------------------------------------------------------------------------- loading


def _set_path(raw: dict[str, Any], dotted: str, value: Any) -> None:
    node = raw
    parts = dotted.split(".")
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _get_path(raw: Mapping[str, Any], dotted: str) -> Any:
    node: Any = raw
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _flatten(raw: Mapping[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in raw.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping):
            keys |= _flatten(value, dotted + ".")
        else:
            keys.add(dotted)
    return keys


def _apply_env_overrides(raw: dict[str, Any], environ: Mapping[str, str]) -> None:
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX) or name in {"CHATPPT_CONFIG"}:
            continue
        dotted = ".".join(part.lower() for part in name[len(ENV_PREFIX) :].split("__"))
        if dotted:
            _set_path(raw, dotted, value)


def _apply_legacy_env(raw: dict[str, Any], environ: Mapping[str, str], explicit: set[str]) -> list[str]:
    applied: list[str] = []
    for entry in LEGACY_ENV:
        value = environ.get(entry.env)
        if value is None or value == "" or entry.path in explicit:
            continue
        _set_path(raw, entry.path, entry.parse(value))
        applied.append(entry.env)
    return applied


def default_data_dir(environ: Mapping[str, str] = os.environ) -> str:
    configured = (environ.get("APP_DATA_DIRECTORY") or "").strip()
    if configured:
        return configured
    if Path("/data").is_dir():
        return "/data"
    return str(Path.cwd() / "app_data")


def config_path(environ: Mapping[str, str] = os.environ, data_dir: str | None = None) -> Path:
    override = (environ.get("CHATPPT_CONFIG") or "").strip()
    if override:
        return Path(override)
    return Path(data_dir or default_data_dir(environ)) / CONFIG_FILE_NAME


_warned_legacy: set[str] = set()


def load_settings(path: str | os.PathLike[str] | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    environ = os.environ if environ is None else environ
    data_dir = default_data_dir(environ)
    file_path = Path(path) if path else config_path(environ, data_dir)

    raw: dict[str, Any] = {}
    if file_path.is_file():
        with open(file_path, "rb") as fh:
            raw = tomllib.load(fh)
    _apply_env_overrides(raw, environ)
    explicit = _flatten(raw)

    raw.setdefault("server", {})
    raw["server"].setdefault("data_dir", data_dir)
    applied = _apply_legacy_env(raw, environ, explicit)

    settings = Settings.model_validate(raw)
    settings.source_path = str(file_path) if file_path.is_file() else None
    settings.explicit = explicit

    new = [env for env in applied if env not in _warned_legacy]
    if new:
        _warned_legacy.update(new)
        hints = ", ".join(f"{env} → {LEGACY_BY_PATH_ENV[env]}" for env in new[:8])
        more = f" (+{len(new) - 8} more)" if len(new) > 8 else ""
        LOGGER.warning("Legacy environment variables in use; move them to %s: %s%s", file_path, hints, more)
    return settings


LEGACY_BY_PATH_ENV: dict[str, str] = {entry.env: entry.path for entry in LEGACY_ENV}


@dataclass
class _Loaded:
    settings: Settings
    path: Path
    mtime: float | None
    checked: float


_loaded: _Loaded | None = None
RECHECK_SECONDS = 1.0


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def get_settings() -> Settings:
    """The current settings. Edits to ``chatppt.toml`` apply without a restart: the file's
    mtime is checked at most once a second and a change reloads (and re-exports) them."""
    global _loaded
    now = time.monotonic()
    if _loaded is not None and now - _loaded.checked < RECHECK_SECONDS:
        return _loaded.settings
    path = config_path()
    mtime = _mtime(path)
    if _loaded is not None and _loaded.path == path and _loaded.mtime == mtime:
        _loaded.checked = now
        return _loaded.settings
    return reload_settings() if _loaded is not None else _load_cached(path, mtime, now)


def _load_cached(path: Path, mtime: float | None, now: float) -> Settings:
    global _loaded
    settings = load_settings()
    _loaded = _Loaded(settings, path, mtime, now)
    return settings


def reload_settings() -> Settings:
    """Re-read env and ``chatppt.toml`` now, and refresh what ``apply_to_environ`` exported."""
    bridged = _bridge["active"]
    restore_environ()
    path = config_path()
    settings = _load_cached(path, _mtime(path), time.monotonic())
    if bridged:
        apply_to_environ(settings)
    return settings


# --------------------------------------------------------------------------- legacy bridge


def to_legacy_env(settings: Settings) -> dict[str, str]:
    """The legacy env vars equivalent to these settings (only for values that are set)."""
    dumped = settings.model_dump()
    out: dict[str, str] = {}
    for entry in LEGACY_ENV:
        value = _get_path(dumped, entry.path)
        if value is None or value == "" or value == {}:
            continue
        out[entry.env] = entry.to_env(value)
    return out


_exported: dict[str, str | None] = {}
"""Legacy env names ``apply_to_environ`` wrote to ``os.environ``, with their prior values."""
_bridge = {"active": False}

LEGACY_LLM_IDS = frozenset(e.path.split(".")[2] for e in LEGACY_ENV if e.path.startswith("llm.providers."))
LEGACY_IMAGE_IDS = frozenset(
    {"pexels", "pixabay", "gemini_flash", "nanobanana_pro", "dall-e-3", "gpt-image-1.5", "comfyui", "open_webui"}
    | {"openai_compatible"}
)


def _openai_compatible_aliases(settings: Settings) -> dict[str, str]:
    """A provider declared only in chatppt.toml (an id upstream code does not know, with a
    ``base_url``) is exported as upstream's generic OpenAI-compatible provider, so every
    code path, not just the routed ones, can use it."""
    out: dict[str, str] = {}
    llm_id = settings.llm.provider
    llm = settings.llm.providers.get(llm_id or "")
    if llm_id and llm_id not in LEGACY_LLM_IDS and llm and llm.base_url:
        out.update(LLM="custom", CUSTOM_LLM_URL=llm.base_url)
        if llm.api_key:
            out["CUSTOM_LLM_API_KEY"] = llm.api_key
        if settings.llm.model or llm.model:
            out["CUSTOM_MODEL"] = settings.llm.model or llm.model or ""
    image_id = settings.images.provider
    image = settings.images.providers.get(image_id or "")
    if image_id and image_id not in LEGACY_IMAGE_IDS and image and image.base_url:
        out.update(IMAGE_PROVIDER="openai_compatible", OPENAI_COMPAT_IMAGE_BASE_URL=image.base_url)
        if image.api_key:
            out["OPENAI_COMPAT_IMAGE_API_KEY"] = image.api_key
        if image.model:
            out["OPENAI_COMPAT_IMAGE_MODEL"] = image.model
    return out


def apply_to_environ(settings: Settings, environ: Any = os.environ) -> list[str]:
    """Export explicitly configured keys as legacy env vars so untouched upstream code
    (``utils/get_env.py`` readers) sees them. Returns the names written."""
    written = []
    legacy = to_legacy_env(settings)
    values = {e.env: legacy[e.env] for e in LEGACY_ENV if e.path in settings.explicit and e.env in legacy}
    # Upstream code cannot parse a provider id it does not know (toml-only or a plugin in
    # <data>/providers): keep it out of LLM / IMAGE_PROVIDER; the aliases below cover base_url.
    if settings.llm.provider not in LEGACY_LLM_IDS:
        values.pop("LLM", None)
    if settings.images.provider not in LEGACY_IMAGE_IDS:
        values.pop("IMAGE_PROVIDER", None)
    values.update(_openai_compatible_aliases(settings))
    if environ is os.environ:
        _bridge["active"] = True
    for name, value in values.items():
        if environ is os.environ and name not in _exported:
            _exported[name] = environ.get(name)
        environ[name] = value
        written.append(name)
    return written


def restore_environ() -> None:
    """Undo ``apply_to_environ`` on ``os.environ`` (before a reload, so a key removed from
    chatppt.toml does not linger as a stale legacy variable)."""
    for name, previous in _exported.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
    _exported.clear()


# --------------------------------------------------------------------------- reference


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Literal:
        return " | ".join(repr(a) for a in get_args(annotation))
    if origin is not None and type(None) in get_args(annotation):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        return _type_name(inner[0]) if len(inner) == 1 else "any"
    if origin is dict:
        return "table"
    return getattr(annotation, "__name__", str(annotation))


def reference_rows(model: type[BaseModel] = Settings, prefix: str = "") -> list[tuple[str, str, str, str, str]]:
    rows = []
    for name, field in model.model_fields.items():
        if field.exclude:
            continue
        dotted = f"{prefix}{name}"
        ann = field.annotation
        inner = ann
        if get_origin(ann) is not None and type(None) in get_args(ann):
            inner = [a for a in get_args(ann) if a is not type(None)][0]
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            rows.extend(reference_rows(inner, dotted + "."))
            continue
        if get_origin(inner) is dict:
            value_type = get_args(inner)[1]
            rows.extend(reference_rows(value_type, dotted + ".<id>."))
            continue
        default = field.get_default(call_default_factory=True)
        default_text = "" if default is None else repr(default)
        env = ENV_PREFIX + "__".join(p.upper() for p in dotted.split("."))
        legacy = LEGACY_BY_PATH.get(dotted)
        env_text = env + (f" (legacy `{legacy.env}`)" if legacy else "")
        rows.append((dotted, _type_name(ann), default_text, env_text, field.description or ""))
    return rows


def render_reference() -> str:
    lines = [
        "# Configuration reference",
        "",
        "Generated by `python -m chatppt --reference` (run in servers/fastapi); do not edit by hand.",
        "",
        f"ChatPPT reads `{CONFIG_FILE_NAME}` from the data directory (or `CHATPPT_CONFIG`). "
        "Every key can be set by environment variable instead: `CHATPPT_` + the key path upper-cased "
        "with `__` between levels. Environment wins over the file. Legacy Presenton variable names "
        "still work and log a warning.",
        "",
        "| Key | Type | Default | Environment | Description |",
        "|---|---|---|---|---|",
    ]
    for key, typ, default, env, desc in reference_rows():
        lines.append(
            f"| `{key}` | {typ} | {('`' + default + '`') if default else ''} | `{env.split(' ')[0]}`{env[len(env.split(' ')[0]) :]} | {desc} |"
        )
    lines += [
        "",
        "## Example",
        "",
        "```toml",
        EXAMPLE_TOML.strip(),
        "```",
        "",
    ]
    return "\n".join(lines)


EXAMPLE_TOML = """
[server]
public_url = "https://decks.example.internal"   # TODO(owner): your URL

[llm]
provider = "openai"
model = "gpt-4.1"

[llm.providers.openai]
api_key = "sk-..."

[llm.providers.anthropic]
api_key = "sk-ant-..."

[llm.routing]
outline = { model = "gpt-4.1-mini" }                    # cheap and fast for the outline
content = { provider = "anthropic", model = "claude-sonnet-4-20250514" }

[images]
provider = "pexels"

[images.providers.pexels]
api_key = "..."

[features]
chat = true
memory = false

[defaults]
template = "general"
theme = "house"
n_slides = 10
"""
