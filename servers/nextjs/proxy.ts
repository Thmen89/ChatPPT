import { NextRequest, NextResponse } from "next/server";
import { isAuthDisabled } from "@/utils/auth";

/**
 * API-only: session required for all /api/* except auth and
 * /api/template (server-to-server template layout for FastAPI fallback).
 * Page routes are protected in server layouts (unknown URLs still 404; login uses relative redirects).
 */
function getFastApiBaseUrl(): string {
  const internal = process.env.FAST_API_INTERNAL_URL?.trim();
  if (internal) {
    return internal.replace(/\/+$/, "");
  }
  const configured = process.env.NEXT_PUBLIC_FAST_API?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  if (process.env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000";
  }
  return "http://127.0.0.1:8000";
}

type AuthStatus = {
  exporter?: boolean;
  configured: boolean;
  authenticated: boolean;
};

const SESSION_COOKIE_NAME = "chatppt_session";
/** The exporter's ?exportSession= is a read-only token FastAPI issues for 15 minutes
 * (POST /api/v1/auth/export-token); the cookie lives no longer than that. */
const EXPORT_SESSION_TTL_SECONDS = 15 * 60;

async function getAuthStatus(request: NextRequest): Promise<AuthStatus> {
  const cookieHeader = request.headers.get("cookie");
  const authStatusUrl = `${getFastApiBaseUrl()}/api/v1/auth/status`;
  try {
    const response = await fetch(authStatusUrl, {
      method: "GET",
      headers: cookieHeader ? { Cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (!response.ok) {
      return { configured: true, authenticated: false };
    }
    const payload = (await response.json()) as Partial<AuthStatus>;
    return {
      configured: Boolean(payload.configured),
      authenticated: Boolean(payload.authenticated),
      exporter: Boolean(payload.exporter),
    };
  } catch {
    return { configured: true, authenticated: false };
  }
}

/** What the exporter's read-only token may reach here: reads, and compiling the CSS of
 * folder templates (a POST with no side effects). */
function isExporterAllowed(request: NextRequest): boolean {
  return request.method === "GET" || request.nextUrl.pathname === "/api/template/css";
}

function isApiAuthExempt(pathname: string): boolean {
  return (
    pathname.startsWith("/api/v1/auth/") ||
    /** FastAPI `get_layout_by_name` fallback (no browser cookie in Docker). */
    pathname === "/api/template" ||
    pathname.startsWith("/api/export-presentation-data/")
  );
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname === "/pdf-maker") {
    const exportSession = request.nextUrl.searchParams.get("exportSession");
    if (exportSession) {
      const redirectUrl = request.nextUrl.clone();
      redirectUrl.searchParams.delete("exportSession");

      const response = NextResponse.redirect(redirectUrl);
      response.cookies.set({
        name: SESSION_COOKIE_NAME,
        value: exportSession,
        maxAge: EXPORT_SESSION_TTL_SECONDS,
        httpOnly: true,
        secure:
          request.headers.get("x-forwarded-proto")?.toLowerCase() === "https" ||
          request.nextUrl.protocol === "https:",
        sameSite: "lax",
        path: "/",
      });
      return response;
    }

    return NextResponse.next();
  }

  if (isAuthDisabled()) {
    return NextResponse.next();
  }

  if (request.method === "OPTIONS" || isApiAuthExempt(pathname)) {
    return NextResponse.next();
  }

  const authStatus = await getAuthStatus(request);
  if (authStatus.authenticated || (authStatus.exporter && isExporterAllowed(request))) {
    return NextResponse.next();
  }
  if (!authStatus.configured) {
    return NextResponse.json(
      { detail: "Login setup is required", setup_required: true },
      { status: 428, headers: { "Cache-Control": "no-store" } }
    );
  }
  return NextResponse.json(
    { detail: "Unauthorized" },
    { status: 401, headers: { "Cache-Control": "no-store" } }
  );
}

export const config = {
  // /api/v1/* is FastAPI's (forwarded by next.config.mjs rewrites) and FastAPI checks the
  // session itself; running this proxy there too would add a round trip per request and
  // buffer upload bodies.
  matcher: ["/api/((?!v1/).*)", "/pdf-maker"],
};
