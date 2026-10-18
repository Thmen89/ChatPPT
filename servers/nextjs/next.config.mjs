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

const nextConfig = {
  reactStrictMode: false,
  distDir: ".next-build",
  output: "standalone",
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
