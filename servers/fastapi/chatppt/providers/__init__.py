"""Provider registry and per-step model routing.

Adding an LLM backend is one file that calls ``register_llm(LLMProviderSpec(...))`` and is
imported from ``chatppt/providers/llm.py``. Image backends register an
``ImageProviderSpec`` the same way (``chatppt/providers/images.py``).
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
