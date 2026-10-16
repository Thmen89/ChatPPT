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

  // Rewrites for development - proxy font requests to FastAPI backend
  async rewrites() {
    return [
      {
        source: '/app_data/fonts/:path*',
        destination: 'http://localhost:5000/app_data/fonts/:path*',
      },
    ];
  },

  // No images.remotePatterns: next/image only serves local files (public/ and
  // /app_data). Template layouts use plain <img>, so the optimizer never
  // fetches a third-party host.
};

export default nextConfig;
