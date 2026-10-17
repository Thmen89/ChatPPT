/**
 * The headless exporter never gets the user's own session: FastAPI issues a read-only
 * token valid for a few minutes, sent to the exporter as its cookie.
 */

function fastApiBaseUrl(): string {
  const url =
    process.env.FAST_API_INTERNAL_URL?.trim() || process.env.NEXT_PUBLIC_FAST_API?.trim() || "http://127.0.0.1:8000";
  return url.replace(/\/+$/, "");
}

/** `Cookie` header for the exporter, or "" when sign-in is off (or the caller has none). */
export async function exporterCookieHeader(userCookieHeader: string): Promise<string> {
  if (!userCookieHeader.trim()) return "";
  try {
    const response = await fetch(`${fastApiBaseUrl()}/api/v1/auth/export-token`, {
      method: "POST",
      headers: { Cookie: userCookieHeader },
      cache: "no-store",
    });
    if (!response.ok) return "";
    const payload = (await response.json()) as { cookie?: string | null };
    return payload.cookie ?? "";
  } catch {
    return "";
  }
}
