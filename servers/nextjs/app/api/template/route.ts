import { NextResponse } from "next/server";

import { buildTemplateLayoutPayload } from "@/lib/server-template-layouts";

export const dynamic = "force-dynamic";

/**
 * Server-only layout ids + JSON schemas for one template: built-in, dropped into
 * `<data>/templates/<id>/`, or imported from a PPTX (`custom-<uuid>`). FastAPI resolves
 * template names through this route; it never imports `presentation-templates/index.tsx`
 * (which would pull Recharts into RSC).
 *
 * FastAPI calls this directly (`CHATPPT_NEXTJS_URL`) and caches the result per
 * template fingerprint, so it runs once per template version.
 */
export async function GET(request: Request) {
  const group = new URL(request.url).searchParams.get("group");
  if (!group) {
    return NextResponse.json(
      { error: "Missing required query parameter: group" },
      { status: 400 },
    );
  }

  try {
    const payload = await buildTemplateLayoutPayload(group);
    if (!payload) {
      return NextResponse.json(
        { error: `Unknown template group: ${group}` },
        { status: 404 },
      );
    }
    return NextResponse.json(payload);
  } catch (err) {
    console.error("[api/template] failed to build layout payload", err);
    return NextResponse.json(
      { error: "Failed to compile template layouts" },
      { status: 500 },
    );
  }
}
