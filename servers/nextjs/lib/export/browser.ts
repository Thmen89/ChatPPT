/**
 * One headless Chromium kept warm by this server for exports: launched on the first
 * export, shared by later ones (each in its own browser context, so cookies never mix),
 * closed after a minute without exports. A crash only costs the export that was running.
 */
import { chromium, type Browser, type BrowserContext } from "playwright-core";

const IDLE_CLOSE_MS = 60_000;
const MAX_PARALLEL_EXPORTS = 2;
const LAUNCH_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-zygote", "--no-extensions"];

let browser: Promise<Browser> | null = null;
let running = 0;
let idleTimer: NodeJS.Timeout | null = null;
const waiting: (() => void)[] = [];

export function chromiumExecutable(): string | undefined {
  return process.env.CHATPPT_CHROMIUM_PATH?.trim() || process.env.PUPPETEER_EXECUTABLE_PATH?.trim() || undefined;
}

function launch(): Promise<Browser> {
  const launching = chromium
    .launch({ executablePath: chromiumExecutable(), headless: true, args: LAUNCH_ARGS, timeout: 60_000 })
    .then((b) => {
      b.on("disconnected", () => {
        if (browser === launching) browser = null;
      });
      return b;
    });
  launching.catch(() => {
    if (browser === launching) browser = null;
  });
  return launching;
}

async function acquire(): Promise<void> {
  if (running >= MAX_PARALLEL_EXPORTS) await new Promise<void>((resolve) => waiting.push(resolve));
  running += 1;
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
  }
}

function release(): void {
  running -= 1;
  const next = waiting.shift();
  if (next) {
    next();
    return;
  }
  if (running === 0) {
    idleTimer = setTimeout(() => {
      idleTimer = null;
      const closing = browser;
      browser = null;
      closing?.then((b) => b.close()).catch(() => {});
    }, IDLE_CLOSE_MS);
    idleTimer.unref?.();
  }
}

export type ExportContextOptions = {
  viewport: { width: number; height: number };
  /** Cookie header every request of the page sends (the exporter's read-only token). */
  cookieHeader?: string;
};

/** Runs `work` with a fresh browser context on the shared browser. */
export async function withExportContext<T>(
  options: ExportContextOptions,
  work: (context: BrowserContext) => Promise<T>
): Promise<T> {
  await acquire();
  let context: BrowserContext | null = null;
  try {
    if (!browser) browser = launch();
    const b = await browser;
    context = await b.newContext({
      viewport: options.viewport,
      deviceScaleFactor: 1,
      extraHTTPHeaders: options.cookieHeader ? { cookie: options.cookieHeader } : undefined,
    });
    return await work(context);
  } finally {
    await context?.close().catch(() => {});
    release();
  }
}
