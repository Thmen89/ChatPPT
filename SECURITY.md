# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

- Preferred: open a private report with GitHub's
  [security advisories](https://github.com/Thmen89/ChatPPT/security/advisories/new).
- Or contact the maintainers: TODO(owner): contact.

Include what you found, how to reproduce it, and the version or commit you tested. We aim to
acknowledge reports within a week and will credit you in the fix unless you ask us not to.

## Supported versions

Only the latest release and `main` receive security fixes.

## How ChatPPT protects an install

ChatPPT is built for one person or a small team on a host they control. Settings below live in
`<data>/chatppt.toml` (or `CHATPPT_AUTH__…` / `CHATPPT_SERVER__…` env vars); see
[docs/config-reference.md](docs/config-reference.md).

**Sign-in**
- Local users, one or more of them admins. The first account is created on the login page
  (or from `AUTH_USERNAME`/`AUTH_PASSWORD` on first start). Admins add users under
  Settings → Users. Passwords: PBKDF2-SHA256, 600,000 iterations, at least 8 characters.
- Browser sessions are an HttpOnly, SameSite=Lax cookie (`chatppt_session`), marked
  `Secure` when `server.public_url` is https. They last `auth.session_days`. Changing your
  password, "Sign out everywhere", or an admin disabling you ends every session at once.
- API tokens (Settings → Account & tokens) are for scripts and MCP clients:
  `Authorization: Bearer cpt_…`. Only a SHA-256 hash is stored, the token is shown once, and
  deleting it revokes it immediately. A token acts as the user who made it.
- Optional SSO: OIDC (`[auth.oidc]`, authorization code flow with PKCE, state and nonce), or a
  trusted reverse-proxy header (`auth.proxy_header`, e.g. `Remote-User`). Only set
  `proxy_header` when ChatPPT is reachable *solely* through that proxy, and prefer setting
  `auth.proxy_secret` so the header is honoured only together with
  `X-ChatPPT-Proxy-Secret`. OIDC users are created on first sign-in unless
  `auth.oidc.create_users = false`.
- Brute force: failed logins are limited per username (10 per 15 minutes) and per client
  (30 per 15 minutes); token creation is limited to 20 per user per hour. The limits are in
  memory and reset on restart.
- Forgot the admin password: `chatppt reset-password [--username NAME]` in the container.
- Upgrading from the single `userConfig.json` login: that user becomes the first admin with
  the same password. Existing browser sessions end once (logged at startup).

**Who may do what**
- Every `/api/*`, `/mcp`, `/docs` and `/app_data/*` request needs a signed-in user.
- Admin only: provider keys and settings (`/api/v1/config`), users, everyone's tokens,
  webhooks, provider model listing and Ollama pulls. Others see only their account in
  Settings. `CAN_CHANGE_KEYS=false` still locks keys for everyone.

**Browser protections**
- CORS allows only `server.public_url` (plus the loopback Next.js the exporter uses).
- CSRF: state-changing requests that rely on the cookie must come from ChatPPT's own pages
  (`Origin`/`Referer`/`Sec-Fetch-Site` checked). Bearer-token calls are not affected.
- Headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy: strict-origin-when-cross-origin`, a Content-Security-Policy, and HSTS when
  `server.public_url` is https. The page CSP allows inline and `eval` scripts because
  template layouts are compiled in the browser, so it is not an XSS barrier; it does block
  framing by other sites, plugins, `<base>` tags and cross-site form posts. Uploaded files are
  served with a sandboxing CSP so an SVG cannot run script.

**Files**
- `/app_data` serves only `images`, `uploads`, `fonts`, `exports` and `pptx-to-html`; never
  `chatppt.toml`, `userConfig.json` or the database next to them. Paths that leave a folder
  (`..`, symlinks) are refused everywhere a request names a file.
- Exported files and slide images are reached through signed links that expire after
  `auth.signed_url_minutes`; the headless exporter gets its own 15-minute read-only token.
- Uploads: request bodies are capped at `server.max_upload_mb`; images (20 MB) and fonts
  (15 MB) must match their extension by content; uploaded file names never become paths.

**Server-side requests**
- Webhook targets (when subscribing and again when sending) and template slide images are
  refused if they resolve to loopback, private, link-local or cloud-metadata addresses, unless
  the host is a provider base URL you configured or is listed in `server.fetch_allow_hosts`.
  Redirects are not followed. Provider URLs themselves are set by admins only.

**Things to know**
- `auth.disabled = true` (`DISABLE_AUTH=true`) turns all of this sign-in off. Use it only on a
  machine or network you trust: anyone who can reach the port can use the app and change
  keys. Cross-site writes from other web pages are still refused, but a DNS-rebinding page
  can get around that, so do not expose such an install.
- Behind a reverse proxy, client addresses for rate limits come from the last
  `X-Forwarded-For` hop. Without a proxy that header can be forged, so the per-client limit
  is weaker; the per-username limit still applies.
- OIDC ID tokens are taken from the provider's token endpoint over TLS and their claims
  (issuer, audience, expiry, nonce) are checked, but the signature is not verified. Use an
  `https://` issuer.
- `RESET_AUTH=true` at startup deletes every user and token.
- The exporter renders decks in Chromium on the server, so an image URL a signed-in user puts
  in a slide is fetched from the server's network (any `https://` host, or `http://` on
  loopback, as the page CSP allows) and an image it gets back lands in the export. The guard
  on server-side requests above does not cover it. Only give accounts to people you would let
  make such requests, or run the container where internal services are out of reach.

## Upstream

ChatPPT is derived from [Presenton](https://github.com/presenton/presenton). If an issue also
affects upstream, we will tell the Presenton maintainers once a fix is available, or let you do
so yourself.
