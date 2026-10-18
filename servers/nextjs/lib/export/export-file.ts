/**
 * Exports a deck to a file in <data>/exports with the built-in exporter: PDF straight from
 * Chromium, PPTX as shape models written by FastAPI's writer (POST /api/v1/ppt/export/pptx).
 *
 * CHATPPT_EXPORT_ENGINE=bundle switches back to the earlier presentation-export bundle.
 */
import crypto from "crypto";
import fs from "fs/promises";
import path from "path";

import { getFastApiBaseUrl } from "@/lib/fastapi-internal";
import { renderPdf, renderPptxModel, type ExportFormat } from "@/lib/export/render";

export function exportEngine(): "chromium" | "bundle" {
  return process.env.CHATPPT_EXPORT_ENGINE?.trim().toLowerCase() === "bundle" ? "bundle" : "chromium";
}

/** The exporter's file-name rule (same as the writer's export_basename). */
export function exportBasename(title: string | undefined): string {
  return (
    (title ?? "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/[^a-zA-Z0-9-]/g, "") || "presentation"
  );
}

function exportsDirectory(): string {
  const appData = process.env.APP_DATA_DIRECTORY?.trim();
  if (!appData) throw new Error("APP_DATA_DIRECTORY is required for exports.");
  return path.join(appData, "exports");
}

export async function exportPresentationFile(params: {
  presentationId: string;
  title: string;
  format: ExportFormat;
  /** What the headless page sends: the exporter's read-only token. */
  exporterCookie: string;
  /** The caller's own credentials (Cookie, Authorization), for the writer, which saves a file. */
  callerHeaders: Record<string, string>;
}): Promise<string> {
  const { presentationId, title, format, exporterCookie, callerHeaders } = params;
  if (format === "pdf") {
    const pdf = await renderPdf({ presentationId, cookieHeader: exporterCookie });
    const directory = exportsDirectory();
    await fs.mkdir(directory, { recursive: true });
    const outPath = path.join(directory, `${exportBasename(title)}_${crypto.randomUUID()}.pdf`);
    await fs.writeFile(outPath, pdf);
    await fs.chmod(outPath, 0o644);
    return outPath;
  }
  const model = await renderPptxModel({ presentationId, title, cookieHeader: exporterCookie });
  const response = await fetch(`${getFastApiBaseUrl()}/api/v1/ppt/export/pptx`, {
    method: "POST",
    headers: { ...callerHeaders, "Content-Type": "application/json" },
    body: JSON.stringify(model),
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`Writing the PPTX failed (${response.status}): ${detail.slice(0, 300)}`);
  }
  const { path: outPath } = (await response.json()) as { path?: string };
  if (!outPath) throw new Error("Writing the PPTX failed: no file path returned.");
  return outPath;
}
