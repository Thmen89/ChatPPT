/**
 * `<data>/hooks.py` export hooks for exports this server runs (the editor's Export button).
 * FastAPI runs the hooks (servers/fastapi/chatppt/hooks.py); a failure never fails the export.
 */

function fastApiBaseUrl(): string {
  const url =
    process.env.FAST_API_INTERNAL_URL?.trim() || process.env.NEXT_PUBLIC_FAST_API?.trim() || "http://127.0.0.1:8000";
  return url.replace(/\/+$/, "");
}

/** Where the exporter reads the deck: the presentation after `before_export`. */
export function exportDeckUrl(presentationId: string): string {
  return `${fastApiBaseUrl()}/api/v1/hooks/export-deck/${encodeURIComponent(presentationId)}`;
}

/** Run `after_export` on the written file. */
export async function runAfterExportHook(path: string, cookieHeader: string): Promise<void> {
  try {
    const response = await fetch(`${fastApiBaseUrl()}/api/v1/hooks/after-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookieHeader },
      body: JSON.stringify({ path }),
      cache: "no-store",
    });
    if (!response.ok) console.warn(`[export-hooks] after_export: HTTP ${response.status}`);
  } catch (err) {
    console.warn("[export-hooks] after_export failed", err);
  }
}
