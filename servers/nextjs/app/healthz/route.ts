import { NextResponse } from "next/server";

import { getFastApiBaseUrl } from "@/lib/fastapi-internal";

export const dynamic = "force-dynamic";

/**
 * Health of the whole app on the public port: this server answers and FastAPI behind it
 * answers its own /healthz. Cheap (no database, no disk); used by the Docker HEALTHCHECK
 * and the compose file.
 */
export async function GET() {
  const headers = { "Cache-Control": "no-store" };
  try {
    const res = await fetch(`${getFastApiBaseUrl()}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (res.ok) {
      return NextResponse.json({ status: "ok" }, { headers });
    }
    return NextResponse.json(
      { status: "error", fastapi: `HTTP ${res.status}` },
      { status: 503, headers }
    );
  } catch {
    return NextResponse.json(
      { status: "error", fastapi: "unreachable" },
      { status: 503, headers }
    );
  }
}
