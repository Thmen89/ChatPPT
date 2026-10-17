// FastAPI listens on loopback only; this server is the one public port and forwards
// the backend's paths to it. Rewrites are fixed at build time, so the address is too:
// start.js (and `npm run dev` next to `python server.py --port 8000`) use this one.
const FASTAPI_URL = "http://127.0.0.1:8000";

/** Paths served by FastAPI. Streams and uploads pass through unbuffered; FastAPI marks
 * event streams `Cache-Control: no-transform` so gzip here never holds them back. */
const FASTAPI_PATHS = [
  "/api/v1/:path*",
  "/app_data/:path*",
  "/static/:path*",
  "/mcp",
  "/mcp/:path*",
  "/docs",
  "/openapi.json",
];

/** Security headers for the pages Next.js serves itself (FastAPI sets its own on the
 * paths above). Layouts are compiled in the browser with Babel, hence 'unsafe-eval';
 * slides show images and Google Fonts from any https host; Electron talks to FastAPI on
 * a 127.0.0.1 port. The CSP still blocks framing by other sites, plugins, <base> and
 * cross-site form posts. */
const PAGE_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:",
  "style-src 'self' 'unsafe-inline' https:",
  "img-src 'self' data: blob: https: http://127.0.0.1:* http://localhost:*",
  "font-src 'self' data: https:",
  "media-src 'self' data: blob: https:",
  "connect-src 'self' https: http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*",
  "worker-src 'self' blob:",
  "frame-src 'self' blob: data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'",
].join("; ");

const PAGE_HEADERS = [
  { key: "Content-Security-Policy", value: PAGE_CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig = {
  reactStrictMode: false,
  distDir: ".next-build",
  output: "standalone",
  // The forwarded FastAPI calls: Next.js drops a proxied request after 30 s without a
  // byte by default, and POST /api/v1/ppt/presentation/generate answers only once the deck
  // is exported (minutes with a real model). Same ceiling as the MCP tool calls' 10 min,
  // with room for big decks.
  experimental: { proxyTimeout: 30 * 60 * 1000 },
  ...(process.env.NODE_ENV !== "production"
    ? {
        allowedDevOrigins: [
          "http://127.0.0.1:40001",
          "http://localhost:40001",
          "127.0.0.1",
          "localhost",
        ],
      }
    : {}),

  async headers() {
    return [
      { source: "/", headers: PAGE_HEADERS },
      {
        // Everything except the FastAPI paths, which carry FastAPI's own headers.
        source: "/:path((?!api/v1/|app_data/|static/|mcp|docs|openapi\\.json).*)",
        headers: PAGE_HEADERS,
      },
    ];
  },

  async rewrites() {
    return {
      // Before the filesystem and app routes, so nothing in Next.js shadows the API.
      beforeFiles: FASTAPI_PATHS.map((source) => ({
        source,
        destination: `${FASTAPI_URL}${source}`,
      })),
    };
  },

  // No images.remotePatterns: next/image only serves local files (public/ and
  // /app_data). Template layouts use plain <img>, so the optimizer never
  // fetches a third-party host.
};

export default nextConfig;
