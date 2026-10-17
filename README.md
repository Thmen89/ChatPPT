<p align="center">
  <img src="./servers/nextjs/public/Logo.png" alt="ChatPPT" height="64" />
</p>

<p align="center">
  Prompt in, editable PPTX out. Self-hosted, any model, customised by dropping files in one folder.
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=flat" alt="Apache-2.0" /></a>
</p>

```bash
docker run -p 5000:5000 -v ./chatppt:/data -e CHATPPT_LLM_API_KEY=sk-... ghcr.io/thmen89/chatppt
```

Open <http://localhost:5000>. Everything ChatPPT keeps (database, decks, settings, templates,
prompts, themes, hooks) is in `./chatppt`.

> TODO(owner): `ghcr.io/thmen89/chatppt` is not published yet (CI pushes it once the
> registry is set up). Until then build it: `docker build -t chatppt .`, and use `chatppt`
> as the image name. `--build-arg VARIANT=full` adds LibreOffice (PPTX template import,
> DOCX/PPTX uploads), OCR and chat memory; it will be published as `:full`.

The key's prefix picks the provider: `sk-` OpenAI, `sk-ant-` Anthropic, `AIza` Google,
`sk-or-` OpenRouter. For anything else set `CHATPPT_LLM__PROVIDER` too, or leave the key out
and pick a provider on the settings page.

## Quickstart: prompt to PPTX in two minutes

1. Start the container (above). Add `-e AUTH_USERNAME=admin -e AUTH_PASSWORD=<password>` to
   create the admin on first start; otherwise the first page asks you to create one.
2. In the browser: type a prompt, pick a template and a length, check the outline, generate,
   then **Export → PPTX**.
3. Or from a script. Make an API token once, then generate:

```bash
TOKEN=$(curl -s -u admin:<password> -X POST http://localhost:5000/api/v1/auth/tokens \
  -H 'Content-Type: application/json' -d '{"name": "scripts"}' | jq -r .token)

curl -s -X POST http://localhost:5000/api/v1/ppt/presentation/generate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content": "Q3 review of a mid-cap industrial: thesis, numbers, risks", "n_slides": 6}'
# {"presentation_id": "...", "path": "/data/exports/<name>.pptx",
#  "edit_path": "/presentation?id=...", "download_url": "/app_data/exports/<name>.pptx?exp=...&sig=..."}

curl -s -o deck.pptx "http://localhost:5000<download_url>"
```

The same token works for MCP at `http://localhost:5000/mcp`.

## Docs

- [Customising](docs/customising.md): templates, themes, prompts, providers, per-step models, hooks.
- [API and MCP](docs/api.md): tokens, endpoints, `/mcp`, `/docs`.
- [Configuration reference](docs/config-reference.md): every `chatppt.toml` key and its env var.
- [Offline install](docs/offline.md): air-gapped hosts, what leaves the machine ([telemetry](docs/telemetry.md)).
- [Architecture](docs/architecture.md), [contracts](docs/contracts.md), [Amazon Bedrock](docs/amazon-bedrock.md).
- [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md).

In the container: `chatppt doctor`, `chatppt backup`, `chatppt restore`, `chatppt reset-password`
(`docker exec -it <container> chatppt doctor`).

## Credits

ChatPPT is derived from [Presenton](https://github.com/presenton/presenton) by the Presenton
team, licensed under Apache-2.0. See [`NOTICE`](NOTICE) and [`docs/upstream.md`](docs/upstream.md).

## License

[Apache-2.0](LICENSE).
