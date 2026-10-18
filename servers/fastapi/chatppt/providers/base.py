from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from chatppt.settings import ProviderCredentials


class ProviderConfigError(ValueError):
    """Raised when a provider is selected but its credentials are incomplete.

    The message is user-facing: it names the missing key in chatppt.toml terms.
    """


@dataclass(frozen=True)
class LLMProviderSpec:
    id: str
    label: str
    default_model: str | None
    build: Callable[[ProviderCredentials], Any]
    """Return an ``llmai`` ClientConfig for these credentials or raise ProviderConfigError."""
    needs: tuple[str, ...] = ("api_key",)
    """Credential fields a new user has to fill in (for docs and the settings UI)."""
    openai_compatible: bool = False
    local: bool = False
    """Runs on the user's machine or network (Ollama, LM Studio): no key, no outbound call."""


ImageGenerate = Callable[[str, str], Awaitable[str] | str]
"""``generate(prompt, output_dir)`` -> a file path under ``output_dir`` or an http(s) URL."""


@dataclass(frozen=True)
class ImageProviderSpec:
    id: str
    label: str
    kind: Literal["stock", "generative"]
    needs: tuple[str, ...] = ("api_key",)
    default_model: str | None = None
    generate: ImageGenerate | None = None
    """Set by providers added in ``<data>/providers/``; the built-ins are still dispatched by
    ``services/image_generation_service.py``."""
