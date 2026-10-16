/**
 * Optional error reporting for the desktop main process.
 *
 * Off unless the operator sets SENTRY_DSN (same key as the server's
 * `server.error_reporting_dsn`) AND installs `@sentry/electron`, which is not a
 * dependency. Nothing is sent by default. PII stays off unless
 * SENTRY_SEND_DEFAULT_PII=true. See docs/telemetry.md.
 */

type SentryMain = {
  init: (options: Record<string, unknown>) => void;
  captureException: (error: unknown) => void;
  addBreadcrumb: (breadcrumb: Record<string, unknown>) => void;
  setContext: (name: string, context: Record<string, unknown>) => void;
};

let sentry: SentryMain | null = null;

type MainSentryRuntimeContext = {
  profileHash?: string;
  cacheRecoveryStatus?: string;
  cacheRecoveryMode?: string;
};

export function initMainSentry(): void {
  const dsn = (process.env.SENTRY_DSN || "").trim();
  if (sentry || !dsn) {
    return;
  }

  try {
    // Lazy, optional: only resolved when an operator configured a DSN.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require("@sentry/electron/main") as SentryMain;
    mod.init({
      dsn,
      sendDefaultPii: (process.env.SENTRY_SEND_DEFAULT_PII || "").trim().toLowerCase() === "true",
      tracesSampleRate: Number.parseFloat(process.env.SENTRY_TRACES_SAMPLE_RATE || "0") || 0,
    });
    sentry = mod;
  } catch (error) {
    console.warn("[ErrorReporting] SENTRY_DSN is set but @sentry/electron is not installed; reporting stays off.", error);
  }
}

export function setMainSentryRuntimeContext(context: MainSentryRuntimeContext): void {
  try {
    sentry?.setContext("runtime", { ...context });
  } catch {
    /* ignore */
  }
}

export function captureMainException(error: unknown, context?: Record<string, unknown>): void {
  if (!sentry) return;
  try {
    if (context) sentry.setContext("details", context);
    sentry.captureException(error);
  } catch {
    /* ignore */
  }
}

export function addMainBreadcrumb(category: string, message: string, data?: Record<string, unknown>): void {
  try {
    sentry?.addBreadcrumb({ category, message, level: "info", data });
  } catch {
    /* ignore */
  }
}
