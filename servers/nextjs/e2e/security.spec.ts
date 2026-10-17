import { expect, test } from "@playwright/test";

// Security headers and file access through the one public port (auth is disabled in the
// e2e stack, so this is about what is reachable at all, not who may reach it).

test("pages and API carry security headers", async ({ request }) => {
  for (const path of ["/", "/upload", "/settings"]) {
    const response = await request.get(path);
    const headers = response.headers();
    expect(headers["x-content-type-options"], path).toBe("nosniff");
    expect(headers["x-frame-options"], path).toBe("SAMEORIGIN");
    expect(headers["content-security-policy"], path).toContain("frame-ancestors 'self'");
    expect(headers["content-security-policy"], path).toContain("object-src 'none'");
  }
  // FastAPI's own policy, not merged with the page one.
  const api = await request.get("/api/v1/auth/status");
  expect(api.headers()["content-security-policy"]).toBe("default-src 'none'; frame-ancestors 'self'");
});

test("settings and secrets next to the media folders are not served", async ({ request }) => {
  for (const path of [
    "/app_data/chatppt.toml",
    "/app_data/userConfig.json",
    "/app_data/fastapi.db",
    "/app_data/images/../chatppt.toml",
    "/app_data/images/%2e%2e/chatppt.toml",
  ]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(404);
  }
});

test("read-file only reads the temp folder", async ({ request }) => {
  for (const filePath of ["/etc/passwd", "/tmp/chatppt/../../etc/passwd", "../../chatppt.toml"]) {
    const response = await request.post("/api/read-file", { data: { filePath } });
    expect(response.status(), filePath).toBe(403);
  }
});

test("removed Next routes that wrote files are gone", async ({ request }) => {
  for (const path of ["/api/save-layout", "/api/upload-image"]) {
    const response = await request.post(path, { data: {} });
    expect(response.status(), path).toBe(404);
  }
});
