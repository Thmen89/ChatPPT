# syntax=docker/dockerfile:1.7
#
# ChatPPT: one image, one port, one data folder.
#
#   docker build -t chatppt .                              # slim (default)
#   docker build --build-arg VARIANT=full -t chatppt:full .
#   docker run -p 5000:5000 -v ./chatppt:/data chatppt
#
# slim  UI, generation, icon search, PPTX/PDF export, PDF/text uploads.
# full  slim + LibreOffice (PPTX template import, DOCX/PPTX uploads), Tesseract OCR,
#       ImageMagick, mem0 chat memory (spaCy + embedder), Noto fonts.
#
# Everything the app needs is baked in here; nothing is downloaded when it starts.

ARG VARIANT=slim
ARG PYTHON_IMAGE=python:3.11-slim-trixie
ARG NODE_IMAGE=node:22-trixie-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.32

FROM ${UV_IMAGE} AS uv

# --------------------------------------------------------------------------- Python
FROM ${PYTHON_IMAGE} AS python-build
ARG VARIANT
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv
WORKDIR /app/servers/fastapi

COPY servers/fastapi/pyproject.toml servers/fastapi/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    extras=""; [ "$VARIANT" = "full" ] && extras="--extra memory"; \
    uv venv /opt/venv; \
    uv export --frozen --no-dev --no-emit-project $extras -o /tmp/requirements.txt; \
    uv pip install --python /opt/venv/bin/python -r /tmp/requirements.txt; \
    if [ "$VARIANT" = "full" ]; then \
      uv pip install --python /opt/venv/bin/python \
        "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"; \
    fi

COPY servers/fastapi ./
# Editable install: the code lives once, in /app/servers/fastapi; this adds the `chatppt` command.
RUN uv pip install --python /opt/venv/bin/python --no-deps -e .

# Model weights for icon search (and, in full, mem0's embedder), fetched now, never at runtime.
ENV CHATPPT_FASTEMBED_ICON_CACHE_DIR=/opt/chatppt/fastembed-icons \
    HF_HOME=/opt/chatppt/hf
RUN set -eu; \
    if [ "$VARIANT" = "full" ]; then /opt/venv/bin/python scripts/warm_fastembed_cache.py --memory; \
    else /opt/venv/bin/python scripts/warm_fastembed_cache.py; fi

# Byte-code for what the server imports (start-up, first icon search, MCP) and for our
# own code, so a cold start never compiles; the rest of site-packages stays source-only
# (compiling all of it would add ~170 MB for modules that are never imported).
RUN set -eu; \
    APP_DATA_DIRECTORY=/tmp/warm-data TEMP_DIRECTORY=/tmp/warm-tmp /opt/venv/bin/python -c \
      "import api.main, chatppt.cli, fastmcp, fastembed_vectorstore, onnxruntime, services.icon_finder_service"; \
    /opt/venv/bin/python -m compileall -q -j 0 /app/servers/fastapi; \
    rm -rf /tmp/warm-data /tmp/warm-tmp

# --------------------------------------------------------------------------- Next.js
FROM ${NODE_IMAGE} AS nextjs-build
ENV NEXT_TELEMETRY_DISABLED=1 \
    CYPRESS_INSTALL_BINARY=0 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /app/servers/nextjs
COPY servers/nextjs/package.json servers/nextjs/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY servers/nextjs ./
RUN npm run build && rm -rf .next-build/cache

# --------------------------------------------------------------------------- Node runtimes
# PPTX/PDF export (Puppeteer bundle + converter, Linux x64 only upstream) and LiteParse.
FROM ${NODE_IMAGE} AS node-runtimes
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json ./
COPY scripts/sync-presentation-export.cjs scripts/
RUN --mount=type=cache,target=/root/.npm \
    set -eu; \
    if [ "$TARGETARCH" = "amd64" ] || [ -z "$TARGETARCH" ]; then \
      node scripts/sync-presentation-export.cjs --force; \
      chmod +x presentation-export/py/convert-linux-x64; \
      cd presentation-export; \
      npm init -y >/dev/null; \
      npm install "sharp@^0.34.5" --include=optional --omit=dev --no-fund --no-audit --no-package-lock; \
      rm -rf /app/.cache; \
    else \
      # TODO(owner): no arm64 build of the export runtime exists upstream; arm64 images
      # run everything except PPTX/PDF export until one does (`chatppt doctor` says so).
      mkdir -p presentation-export; \
    fi
RUN --mount=type=cache,target=/root/.npm \
    mkdir -p document-extraction-liteparse \
    && cd document-extraction-liteparse \
    && npm init -y >/dev/null \
    && npm install @llamaindex/liteparse@1.4.0 --omit=dev --no-fund --no-audit --no-package-lock
COPY electron/resources/document-extraction/liteparse_runner.mjs document-extraction-liteparse/

# --------------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ARG VARIANT

# Chromium for the exporter: the headless shell where Debian packages it, else chromium.
# full adds the heavy optional tools; slim stays without them.
RUN set -eu; \
    apt-get update; \
    common="ca-certificates fonts-liberation fonts-dejavu-core"; \
    full=""; \
    if [ "$VARIANT" = "full" ]; then \
      full="libreoffice-impress libreoffice-writer tesseract-ocr tesseract-ocr-eng imagemagick fonts-noto-core"; \
    fi; \
    apt-get install -y --no-install-recommends $common $full chromium-headless-shell \
      || apt-get install -y --no-install-recommends $common $full chromium; \
    for b in /usr/bin/chromium-headless-shell /usr/lib/chromium/headless_shell /usr/bin/chromium; do \
      if [ -x "$b" ]; then ln -s "$b" /usr/local/bin/chromium-for-export; break; fi; \
    done; \
    test -x /usr/local/bin/chromium-for-export; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /usr/share/doc/* /usr/share/man/*; \
    groupadd --gid 1000 chatppt; \
    useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin chatppt; \
    mkdir -p /data /tmp/chatppt; \
    chown chatppt:chatppt /data /tmp/chatppt

COPY --from=nextjs-build /usr/local/bin/node /usr/local/bin/node
COPY --from=python-build /opt/venv /opt/venv
# Writable by the app user: the model loader may create lock files next to the weights.
COPY --from=python-build --chown=1000:1000 /opt/chatppt /opt/chatppt
COPY --from=python-build /app/servers/fastapi /app/servers/fastapi
COPY --from=nextjs-build /app/servers/nextjs/.next-build/standalone/ /app/servers/nextjs/
COPY --from=nextjs-build /app/servers/nextjs/.next-build/static /app/servers/nextjs/.next-build/static
COPY --from=nextjs-build /app/servers/nextjs/public /app/servers/nextjs/public
COPY --from=node-runtimes /app/presentation-export /app/presentation-export
COPY --from=node-runtimes /app/document-extraction-liteparse /app/document-extraction-liteparse
COPY package.json start.js LICENSE NOTICE /app/
COPY scripts/chatppt-banner.mjs scripts/chatppt-ascii.txt /app/scripts/

ENV PATH=/opt/venv/bin:$PATH \
    NODE_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHATPPT_APP_ROOT=/app \
    CHATPPT_FASTEMBED_ICON_CACHE_DIR=/opt/chatppt/fastembed-icons \
    HF_HOME=/opt/chatppt/hf \
    HF_HUB_OFFLINE=1 \
    EXPORT_PACKAGE_ROOT=/app/presentation-export \
    EXPORT_RUNTIME_DIR=/app/presentation-export \
    BUILT_PYTHON_MODULE_PATH=/app/presentation-export/py/convert-linux-x64 \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-for-export \
    TEMP_DIRECTORY=/tmp/chatppt

WORKDIR /app
VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||5000)+'/healthz').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]

# Starts as root only to hand /data to the `chatppt` user (bind mounts arrive root-owned),
# then start.js drops to uid 1000 before any server runs. `--user 1000:1000` skips that.
# --max-semi-space-size=1: ~20 MB less idle RAM for the Next.js server.
CMD ["node", "--max-semi-space-size=1", "/app/start.js"]
