"""ChatPPT's own modules: configuration, templates, prompts, themes and providers.

Everything under ``chatppt/`` is the contract the rest of the backend builds on.
Upstream (Presenton) code lives beside it untouched where possible; see
``docs/contracts.md`` and ``docs/upstream.md``.
"""

from chatppt.settings import Settings, get_settings, reload_settings

__all__ = ["Settings", "get_settings", "reload_settings"]
