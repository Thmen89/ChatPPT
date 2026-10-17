"""Provider registry and per-step model routing.

An OpenAI-compatible backend needs only a ``[llm.providers.<id>]`` table with ``base_url``
in chatppt.toml. Any other backend is one file in ``<data>/providers/`` that calls
``register_llm(LLMProviderSpec(...))`` or ``register_image(ImageProviderSpec(..., generate=...))``.
"""

from chatppt.providers.base import ImageProviderSpec, LLMProviderSpec, ProviderConfigError
from chatppt.providers.registry import (
    get_image_provider,
    get_llm_provider,
    image_providers,
    llm_providers,
    register_image,
    register_llm,
)
from chatppt.providers.routing import ResolvedLLM, llm_for_step, resolve_llm

__all__ = [
    "ImageProviderSpec",
    "LLMProviderSpec",
    "ProviderConfigError",
    "ResolvedLLM",
    "get_image_provider",
    "get_llm_provider",
    "image_providers",
    "llm_for_step",
    "llm_providers",
    "register_image",
    "register_llm",
    "resolve_llm",
]
