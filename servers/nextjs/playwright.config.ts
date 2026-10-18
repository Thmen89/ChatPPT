import { chromium, defineConfig, devices } from "@playwright/test";

// One flow, end to end, on mock providers: see e2e/deck.spec.ts.
// `npm run test:e2e` starts the stack with e2e/stack.py, or reuses one already
// answering on :80 when not in CI.
const BASE_URL = "http://127.0.0.1";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/results",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python3 e2e/stack.py",
    url: `${BASE_URL}/api/v1/auth/status`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: "pipe",
    gracefulShutdown: { signal: "SIGTERM", timeout: 15_000 },
    // The exporter drives Chromium through Puppeteer; reuse Playwright's.
    env: {
      PUPPETEER_EXECUTABLE_PATH: process.env.PUPPETEER_EXECUTABLE_PATH || chromium.executablePath(),
    },
  },
});
