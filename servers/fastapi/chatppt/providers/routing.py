"""Per-step model routing: ``llm_for_step("outline")`` returns the client and model to use.

Order of resolution for a step:

1. ``[llm.routing].<step>`` provider/model.
2. ``[llm]`` provider/model.
3. ``[llm.providers.<id>].model``, then the provider's default model.

A provider id that is not registered but has a ``base_url`` under ``[llm.providers.<id>]``
is an OpenAI-compatible endpoint; nothing else is needed.

When neither ``chatppt.toml`` nor ``CHATPPT_*`` sets ``llm.provider``, the legacy
``utils.llm_config``/``utils.llm_provider`` path is used unchanged, so installs that
still configure themselves through the settings UI and env vars behave as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from llmai import get_client

from chatppt.providers.base import ProviderConfigError
from chatppt.providers.llm import openai_compatible_spec
from chatppt.providers.registry import get_llm_provider
from chatppt.settings import STEPS, ProviderCredentials, Settings, StepRoute, get_settings


@dataclass(frozen=True)
class ResolvedLLM:
    provider: str
    model: str
    config: Any
    source: str  # "routing", "settings" or "legacy"


def uses_settings(settings: Settings, step: str | None) -> bool:
    """True when chatppt.toml (or CHATPPT_*) picks the LLM for this step."""
    if step and (
        settings.is_explicit(f"llm.routing.{step}.provider") or settings.is_explicit(f"llm.routing.{step}.model")
    ):
        return True
    return settings.is_explicit("llm.provider")


def _legacy() -> ResolvedLLM:
    from utils.llm_config import get_llm_config
    from utils.llm_provider import get_llm_provider as legacy_provider
    from utils.llm_provider import get_model

    return ResolvedLLM(legacy_provider().value, get_model(), get_llm_config(), "legacy")


def resolve_llm(step: str | None = None, settings: Settings | None = None) -> ResolvedLLM:
    if step is not None and step not in STEPS:
        raise ValueError(f"unknown step '{step}'; known: {', '.join(STEPS)}")
    settings = settings or get_settings()
    if not uses_settings(settings, step):
        return _legacy()

    route = settings.llm.routing.get(step, StepRoute()) if step else StepRoute()
    provider_id = route.provider or settings.llm.provider
    if not provider_id:
        raise HTTPException(status_code=400, detail="No LLM provider configured. Set llm.provider in chatppt.toml.")
    creds = settings.llm.providers.get(provider_id, ProviderCredentials())
    try:
        spec = get_llm_provider(provider_id)
    except KeyError as exc:
        if not creds.base_url:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        spec = openai_compatible_spec(provider_id)  # declared in chatppt.toml alone
    model = (
        route.model
        or (settings.llm.model if provider_id == settings.llm.provider else None)
        or creds.model
        or spec.default_model
    )
    if not model:
        raise HTTPException(
            status_code=400, detail=f"{provider_id}: set llm.providers.{provider_id}.model in chatppt.toml"
        )
    try:
        config = spec.build(creds)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return ResolvedLLM(provider_id, model, config, "routing" if route.provider or route.model else "settings")


def llm_for_step(step: str) -> tuple[Any, str]:
    """``(client, model)`` for one generation step. Drop-in for
    ``get_client(config=get_llm_config()), get_model()``."""
    resolved = resolve_llm(step)
    return get_client(config=resolved.config), resolved.model
