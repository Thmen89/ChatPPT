"""Download FastEmbed weights at image/app BUILD time, never at runtime.

Icon search uses AllMiniLML6V2 (``CHATPPT_FASTEMBED_ICON_CACHE_DIR``). When
``--memory`` is passed, also warms mem0's default embedder (``BAAI/bge-small-en-v1.5``
under ``HF_HOME``) for images that ship with ``features.memory`` on.

The running server sets ``HF_HUB_OFFLINE=1`` so it can only read what this script
cached; this script is the one place allowed to fetch, so it turns that off.
"""

import os
import sys
from pathlib import Path

# Must be set before fastembed / huggingface_hub are imported.
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

FASTAPI_ROOT = Path(__file__).resolve().parents[1]
if str(FASTAPI_ROOT) not in sys.path:
    sys.path.insert(0, str(FASTAPI_ROOT))


def _warm_icons() -> None:
    from fastembed_vectorstore import FastembedEmbeddingModel, FastembedVectorstore

    from services.icon_finder_service import ICON_FINDER_SERVICE

    cache_dir = ICON_FINDER_SERVICE.cache_directory
    os.makedirs(cache_dir, exist_ok=True)
    store = FastembedVectorstore(FastembedEmbeddingModel.AllMiniLML6V2, cache_directory=cache_dir)
    store.embed_documents(["warmup"])
    print(f"Icon search model cached at {cache_dir}")


def _warm_mem0_default_fastembed() -> None:
    model = (os.getenv("MEM0_EMBEDDER_MODEL") or "BAAI/bge-small-en-v1.5").strip()
    from fastembed import TextEmbedding

    next(TextEmbedding(model_name=model).embed(["warmup"]))
    print(f"Memory embedder cached: {model}")


def main() -> None:
    # The Dockerfile copies HF_HOME out of the build stage; keep it present even when
    # only icon weights are warmed (they live in their own cache dir).
    if os.getenv("HF_HOME"):
        os.makedirs(os.environ["HF_HOME"], exist_ok=True)
    _warm_icons()
    if "--memory" in sys.argv[1:]:
        _warm_mem0_default_fastembed()


if __name__ == "__main__":
    main()
