# Offline install

The image carries everything it runs: both servers, Chromium for export, the icon-search
model and, in `:full`, LibreOffice, OCR and the memory model. Nothing is downloaded at start
or at run time (`HF_HUB_OFFLINE=1` is set in the image), and nothing phones home
([telemetry.md](telemetry.md)). CI starts the servers in a network namespace with no route
out and fails on any outbound attempt (`scripts/check_offline.py`).

## Move the image to an air-gapped host

```bash
# connected machine
docker pull ghcr.io/thmen89/chatppt            # TODO(owner): not published yet; or docker build -t chatppt .
docker save ghcr.io/thmen89/chatppt | gzip > chatppt.tar.gz

# air-gapped host
docker load < chatppt.tar.gz
docker run -p 5000:5000 -v ./chatppt:/data ghcr.io/thmen89/chatppt
```

## Point it at a model on your network

Any OpenAI-compatible server (vLLM, llama.cpp, a gateway), Ollama or LM Studio:

```bash
docker run -p 5000:5000 -v ./chatppt:/data \
  -e CHATPPT_LLM__PROVIDER=ollama \
  -e CHATPPT_LLM__MODEL=<model> \
  -e CHATPPT_LLM__PROVIDERS__OLLAMA__BASE_URL=http://10.0.0.5:11434 \
  ghcr.io/thmen89/chatppt
```

For an OpenAI-compatible server use `provider = "custom"` with `base_url` (ending in `/v1`),
`model` and, if it wants one, `api_key`; or any id of your own, as in
[customising.md](customising.md#providers).

## What still wants the network

- **Images.** With no image provider, slides get placeholders. Point `[images]` at a local
  OpenAI-compatible image endpoint, ComfyUI or Open WebUI to generate them on the LAN.
- **Web fonts.** Some built-in templates and theme fonts reference Google Fonts; the
  *browser* asks for them and falls back to installed fonts when it cannot reach them. Exports
  render with whatever fonts the container has. Put font files in a theme's `font.url`
  (`/app_data/fonts/...`) or a template's `fonts/` folder to keep them local.
- **PPTX template import** (`:full`) looks the deck's font names up on Google Fonts.
