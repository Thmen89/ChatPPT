"""Built-in LLM providers: how each one turns credentials into an ``llmai`` client config.

Each entry is a few lines. A new backend is another ``register_llm`` call (in this file or
a new one imported from ``registry._ensure_loaded``).
"""

from __future__ import annotations

from llmai import (
    BedrockClientConfig,
    FireworksClientConfig,
    LMStudioClientConfig,
    TogetherAIClientConfig,
)
from llmai.shared import (
    AnthropicClientConfig,
    AzureOpenAIClientConfig,
    CerebrasClientConfig,
    GoogleClientConfig,
    LiteLLMClientConfig,
    OpenAIApiType,
    OpenAIClientConfig,
    OpenRouterClientConfig,
    VertexAIClientConfig,
)

from chatppt.providers.base import LLMProviderSpec, ProviderConfigError
from chatppt.providers.registry import register_llm
from chatppt.settings import ProviderCredentials


def _need(creds: ProviderCredentials, provider: str, *fields: str) -> None:
    missing = [f for f in fields if not (getattr(creds, f, None) or "").strip()]
    if missing:
        keys = ", ".join(f"llm.providers.{provider}.{f}" for f in missing)
        raise ProviderConfigError(f"{provider}: set {keys} in chatppt.toml")


def _strip(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _openai(creds: ProviderCredentials):
    _need(creds, "openai", "api_key")
    return OpenAIClientConfig(api_key=creds.api_key, base_url=_strip(creds.base_url), api_type=OpenAIApiType.COMPLETIONS)


def _anthropic(creds: ProviderCredentials):
    _need(creds, "anthropic", "api_key")
    return AnthropicClientConfig(api_key=creds.api_key, base_url=_strip(creds.base_url))


def _google(creds: ProviderCredentials):
    _need(creds, "google", "api_key")
    return GoogleClientConfig(api_key=creds.api_key, base_url=_strip(creds.base_url))


def _vertex(creds: ProviderCredentials):
    api_key, project, location = _strip(creds.api_key), _strip(creds.project), _strip(creds.location)
    if api_key and (project or location):
        raise ProviderConfigError("vertex: set either api_key or project/location, not both")
    if api_key:
        return VertexAIClientConfig(api_key=api_key, base_url=_strip(creds.base_url))
    if not project:
        raise ProviderConfigError("vertex: set llm.providers.vertex.api_key or llm.providers.vertex.project")
    return VertexAIClientConfig(project=project, location=location, base_url=_strip(creds.base_url))


def _azure(creds: ProviderCredentials):
    _need(creds, "azure", "api_key", "api_version")
    if not (_strip(creds.endpoint) or _strip(creds.base_url)):
        raise ProviderConfigError("azure: set llm.providers.azure.endpoint or llm.providers.azure.base_url")
    return AzureOpenAIClientConfig(api_key=creds.api_key, api_version=creds.api_version,
                                   endpoint=_strip(creds.endpoint), base_url=_strip(creds.base_url),
                                   deployment=_strip(creds.deployment))


def _bedrock(creds: ProviderCredentials):
    key_id, secret = _strip(creds.aws_access_key_id), _strip(creds.aws_secret_access_key)
    if not _strip(creds.api_key) and not (key_id and secret):
        raise ProviderConfigError("bedrock: set llm.providers.bedrock.api_key, or aws_access_key_id and aws_secret_access_key")
    return BedrockClientConfig(region=_strip(creds.region) or "us-east-1", api_key=_strip(creds.api_key),
                               aws_access_key_id=key_id, aws_secret_access_key=secret,
                               aws_session_token=_strip(creds.aws_session_token),
                               profile_name=_strip(creds.profile_name))


def _keyed(provider: str, config_cls):
    def build(creds: ProviderCredentials):
        _need(creds, provider, "api_key")
        return config_cls(api_key=creds.api_key, base_url=_strip(creds.base_url))
    return build


def _litellm(creds: ProviderCredentials):
    _need(creds, "litellm", "base_url")
    base = creds.base_url.strip().rstrip("/")
    return LiteLLMClientConfig(base_url=base if base.endswith("/v1") else base + "/v1", api_key=_strip(creds.api_key))


def _lmstudio(creds: ProviderCredentials):
    return LMStudioClientConfig(base_url=_strip(creds.base_url), api_key=_strip(creds.api_key))


def _ollama(creds: ProviderCredentials):
    base = (_strip(creds.base_url) or "http://localhost:11434").rstrip("/")
    return OpenAIClientConfig(base_url=base if base.endswith("/v1") else base + "/v1", api_key="ollama")


def _custom(creds: ProviderCredentials):
    _need(creds, "custom", "base_url")
    return OpenAIClientConfig(base_url=creds.base_url.strip(), api_key=_strip(creds.api_key) or "null")


def _codex(creds: ProviderCredentials):
    # Codex signs in with OAuth tokens kept by the app, not with a key in the config file.
    from utils.llm_config import get_llm_config

    return get_llm_config()


register_llm(LLMProviderSpec("openai", "OpenAI", "gpt-4.1", _openai))
register_llm(LLMProviderSpec("anthropic", "Anthropic", "claude-sonnet-4-20250514", _anthropic))
register_llm(LLMProviderSpec("google", "Google Gemini", "models/gemini-2.5-flash", _google))
register_llm(LLMProviderSpec("vertex", "Google Vertex AI", "gemini-2.5-flash", _vertex, needs=("project", "location")))
register_llm(LLMProviderSpec("azure", "Azure OpenAI", "gpt-4.1", _azure, needs=("api_key", "endpoint", "api_version", "deployment")))
register_llm(LLMProviderSpec("bedrock", "Amazon Bedrock", "us.anthropic.claude-3-5-haiku-20241022-v1:0", _bedrock, needs=("region", "api_key")))
register_llm(LLMProviderSpec("openrouter", "OpenRouter", "openai/gpt-4o", _keyed("openrouter", OpenRouterClientConfig), openai_compatible=True))
register_llm(LLMProviderSpec("fireworks", "Fireworks", "accounts/fireworks/models/llama-v3p1-8b-instruct", _keyed("fireworks", FireworksClientConfig), openai_compatible=True))
register_llm(LLMProviderSpec("together", "Together AI", "openai/gpt-oss-20b", _keyed("together", TogetherAIClientConfig), openai_compatible=True))
register_llm(LLMProviderSpec("cerebras", "Cerebras", "llama-3.3-70b", _keyed("cerebras", CerebrasClientConfig), openai_compatible=True))
register_llm(LLMProviderSpec("litellm", "LiteLLM proxy", "gpt-4.1", _litellm, needs=("base_url",), openai_compatible=True))
register_llm(LLMProviderSpec("lmstudio", "LM Studio", "openai/gpt-oss-20b", _lmstudio, needs=("base_url",), openai_compatible=True, local=True))
register_llm(LLMProviderSpec("ollama", "Ollama", None, _ollama, needs=("base_url", "model"), openai_compatible=True, local=True))
register_llm(LLMProviderSpec("custom", "OpenAI-compatible endpoint", None, _custom, needs=("base_url", "model"), openai_compatible=True))
register_llm(LLMProviderSpec("codex", "ChatGPT (Codex sign-in)", "gpt-5.2", _codex, needs=()))
