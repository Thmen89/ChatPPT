from __future__ import annotations

from chatppt.providers.base import ImageProviderSpec, LLMProviderSpec

_LLM: dict[str, LLMProviderSpec] = {}
_IMAGES: dict[str, ImageProviderSpec] = {}


def register_llm(spec: LLMProviderSpec) -> LLMProviderSpec:
    _LLM[spec.id] = spec
    return spec


def register_image(spec: ImageProviderSpec) -> ImageProviderSpec:
    _IMAGES[spec.id] = spec
    return spec


def _ensure_loaded() -> None:
    # Importing the modules registers the built-in providers; files in <data>/providers/
    # register theirs (re-imported when they change).
    import chatppt.providers.images  # noqa: F401
    import chatppt.providers.llm  # noqa: F401
    from chatppt.providers.plugins import load_plugins

    load_plugins()


def llm_providers() -> dict[str, LLMProviderSpec]:
    _ensure_loaded()
    return dict(_LLM)


def image_providers() -> dict[str, ImageProviderSpec]:
    _ensure_loaded()
    return dict(_IMAGES)


def get_llm_provider(provider_id: str) -> LLMProviderSpec:
    _ensure_loaded()
    try:
        return _LLM[provider_id]
    except KeyError:
        raise KeyError(f"unknown LLM provider '{provider_id}'; known: {', '.join(sorted(_LLM))}") from None


def get_image_provider(provider_id: str) -> ImageProviderSpec:
    _ensure_loaded()
    try:
        return _IMAGES[provider_id]
    except KeyError:
        raise KeyError(f"unknown image provider '{provider_id}'; known: {', '.join(sorted(_IMAGES))}") from None
