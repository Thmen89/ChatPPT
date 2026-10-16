import asyncio
import logging
import os

from utils.asset_directory_utils import absolute_fastapi_asset_url
from utils.icon_weights import (
    ALLOWED_ICON_WEIGHTS,
    DEFAULT_ICON_WEIGHT,
    normalize_icon_weight,
)
from utils.path_helpers import get_resource_path, get_writable_path

LOGGER = logging.getLogger(__name__)

# Icon search never downloads anything: the embedding model must already be in the
# cache directory (baked into the image or shipped with the desktop app). These make
# fastembed / huggingface_hub fail fast instead of reaching out to the Hub.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def _icon_fastembed_cache_directory() -> str:
    """ONNX weights for icon search (MiniLM). Prefer a path outside ``APP_DATA_DIRECTORY``
    in Docker: ``./app_data`` is often bind-mounted and would hide weights baked at image build.
    Falls back to the weights shipped next to the code, then to ``<data>/fastembed_cache``.
    """
    override = (
        os.getenv("CHATPPT_FASTEMBED_ICON_CACHE_DIR")
        # Deprecated name, kept as a fallback for one release.
        or os.getenv("PRESENTON_FASTEMBED_ICON_CACHE_DIR")
        or ""
    ).strip()
    if override:
        return os.path.abspath(override)
    bundled = get_resource_path("fastembed_cache")
    if os.path.isdir(bundled):
        return bundled
    return get_writable_path("fastembed_cache")


class IconFinderService:
    """Semantic icon search over a prebuilt vectorstore (``assets/icons-vectorstore.json``).

    Offline only. If the vectorstore or the model weights are missing, it logs once and
    every search returns ``[]``, which callers turn into the placeholder icon.
    """

    def __init__(self):
        self.cache_directory = _icon_fastembed_cache_directory()
        self.vectorstore = None
        self._initialized = False
        self._initialization_failed = False
        self._init_lock: asyncio.Lock | None = None
        # Query -> icon names. Decks reuse the same few queries ("growth", "team"...),
        # and the lookup is deterministic for a given vectorstore.
        self._results: dict[tuple[str, int], list[str]] = {}

    def _initialize_icons_collection(self):
        if self._initialized or self._initialization_failed:
            return
        self._initialized = True

        vectorstore_path = get_resource_path("assets/icons-vectorstore.json")
        if not os.path.isfile(vectorstore_path):
            LOGGER.warning(
                "Icon search disabled: %s is missing; slides use placeholder icons.",
                vectorstore_path,
            )
            self._initialization_failed = True
            return

        try:
            from fastembed_vectorstore import FastembedEmbeddingModel, FastembedVectorstore

            self.vectorstore = FastembedVectorstore.load(
                FastembedEmbeddingModel.AllMiniLML6V2,
                vectorstore_path,
                cache_directory=self.cache_directory,
            )
        except Exception as exc:
            LOGGER.warning(
                "Icon search disabled: embedding model not found in %s (%s: %s). "
                "Nothing is downloaded at runtime; slides use placeholder icons.",
                self.cache_directory,
                type(exc).__name__,
                str(exc)[:200],
            )
            self.vectorstore = None
            self._initialization_failed = True

    def ensure_initialized(self) -> bool:
        if not self._initialized and not self._initialization_failed:
            self._initialize_icons_collection()
        return self.vectorstore is not None and not self._initialization_failed

    @staticmethod
    def _base_icon_name(icon_name: str) -> str:
        name = icon_name.split("||")[0]
        for weight in ALLOWED_ICON_WEIGHTS:
            suffix = f"-{weight}"
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    @staticmethod
    def _icon_filename_for_weight(base_name: str, weight: str) -> str:
        if weight == "regular":
            return f"{base_name}.svg"
        return f"{base_name}-{weight}.svg"

    def _icon_url_for_weight(self, icon_name: str, weight: str) -> str:
        normalized_weight = normalize_icon_weight(weight)
        base_name = self._base_icon_name(icon_name)
        filename = self._icon_filename_for_weight(base_name, normalized_weight)
        relative_path = f"static/icons/{normalized_weight}/{filename}"
        if not os.path.isfile(get_resource_path(relative_path)):
            normalized_weight = DEFAULT_ICON_WEIGHT
            filename = self._icon_filename_for_weight(base_name, normalized_weight)

        return absolute_fastapi_asset_url(
            f"/static/icons/{normalized_weight}/{filename}"
        )

    async def _ensure_initialized_async(self) -> bool:
        """Load the model in a worker thread (it takes ~1 s and must not stall the
        event loop while slides are streaming); concurrent first searches wait once."""
        if self._initialized or self._initialization_failed:
            return self.vectorstore is not None and not self._initialization_failed
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if not self._initialized and not self._initialization_failed:
                await asyncio.to_thread(self._initialize_icons_collection)
        return self.vectorstore is not None and not self._initialization_failed

    async def search_icons(self, query: str, k: int = 1, weight: str | None = None):
        if not await self._ensure_initialized_async():
            return []

        try:
            icon_weight = normalize_icon_weight(weight)
            key = (query, k)
            names = self._results.get(key)
            if names is None:
                result = await asyncio.to_thread(self.vectorstore.search, query, k)
                names = [each[0] for each in result]
                if len(self._results) >= 4096:
                    self._results.clear()
                self._results[key] = names
            return [self._icon_url_for_weight(name, icon_weight) for name in names]
        except Exception as e:
            LOGGER.warning("Icon search error: %s", e)
            return []


ICON_FINDER_SERVICE = IconFinderService()
