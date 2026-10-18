import { NextRequest, NextResponse } from "next/server";

import { exporterCookieHeader } from "@/lib/export-auth";
import { renderPdf, renderPptxModel } from "@/lib/export/render";

/**
 * For FastAPI's export (POST /api/v1/ppt/presentation/generate and friends): renders a
 * deck with this server's Chromium and returns the PPTX shape models (JSON) or the PDF
 * bytes. It writes nothing and runs no hooks; FastAPI saves the file and runs its own
 * after_export hook. Reachable with the exporter's read-only token (see proxy.ts).
 */
export async function POST(req: NextRequest) {
  const { id, format } = (await req.json().catch(() => ({}))) as { id?: unknown; format?: unknown };
  if (typeof id !== "string" || !id) {
    return NextResponse.json({ error: "Missing Presentation ID" }, { status: 400 });
  }
  if (format !== "pptx" && format !== "pdf") {
    return NextResponse.json({ error: "Invalid export format" }, { status: 400 });
  }
  // FastAPI calls with an exporter token already (which cannot mint another); anyone else
  // gets one, so the page never carries a user's own session.
  const callerCookie = req.headers.get("cookie") ?? "";
  const cookieHeader = (await exporterCookieHeader(callerCookie)) || callerCookie;
  try {
    if (format === "pdf") {
      const pdf = await renderPdf({ presentationId: id, cookieHeader });
      return new NextResponse(new Uint8Array(pdf), {
        headers: { "Content-Type": "application/pdf", "Cache-Control": "no-store" },
      });
    }
    return NextResponse.json(await renderPptxModel({ presentationId: id, cookieHeader }), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    console.error(`[export-presentation/render:${format}]`, message);
    return NextResponse.json({ error: message, success: false }, { status: 500 });
  }
}
