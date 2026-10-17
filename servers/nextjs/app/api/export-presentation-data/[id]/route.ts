import { NextRequest, NextResponse } from "next/server";

import { exportDeckUrl } from "@/lib/export-hooks";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { detail: "Missing presentation id" },
      { status: 400 }
    );
  }

  const exportCookie = request.headers.get("x-export-cookie")?.trim();
  if (!exportCookie) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const presentationUrl = exportDeckUrl(id); // the deck after hooks.py before_export

  try {
    const response = await fetch(presentationUrl, {
      method: "GET",
      headers: {
        Cookie: exportCookie,
      },
      cache: "no-store",
    });

    const bodyText = await response.text();
    const contentType = response.headers.get("content-type") ?? "application/json";

    return new NextResponse(bodyText, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("[export-presentation-data] Failed to fetch presentation", error);
    return NextResponse.json(
      { detail: "Failed to fetch presentation data" },
      { status: 500 }
    );
  }
}
