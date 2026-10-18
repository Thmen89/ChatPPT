import { createHash } from "crypto";
import { NextResponse } from "next/server";
import postcss from "postcss";
import tailwindcss from "tailwindcss";

export const dynamic = "force-dynamic";

/**
 * Tailwind utilities for layouts compiled at runtime (template folders under
 * `<data>/templates/`, PPTX imports). Built-in layouts get their classes from the app's
 * build; runtime layouts send their source here and get exactly the utilities they use,
 * compiled locally. Replaces the Tailwind Play CDN, so templates render offline.
 *
 * POST `{ "sources": ["<layout code>", ...] }` -> `text/css`. Cached by content hash.
 */

const MAX_BODY_BYTES = 4 * 1024 * 1024;
const MAX_CACHE = 256;
const cache = new Map<string, string>();

async function compile(sources: string[]): Promise<string> {
  const key = createHash("sha1").update(sources.join("\u0000")).digest("hex");
  const hit = cache.get(key);
  if (hit !== undefined) return hit;

  const result = await postcss([
    tailwindcss({
      content: sources.map((raw) => ({ raw, extension: "tsx" })),
      // The app's stylesheet already carries Tailwind's base layer.
      corePlugins: { preflight: false },
    }),
  ]).process("@tailwind components;\n@tailwind utilities;", { from: undefined });

  if (cache.size >= MAX_CACHE) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, result.css);
  return result.css;
}

export async function POST(request: Request) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_BODY_BYTES) {
    return NextResponse.json({ error: "Payload too large" }, { status: 413 });
  }

  let sources: unknown;
  try {
    sources = ((await request.json()) as { sources?: unknown }).sources;
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  if (!Array.isArray(sources) || !sources.every((s) => typeof s === "string")) {
    return NextResponse.json({ error: "sources must be a list of strings" }, { status: 400 });
  }

  try {
    const css = await compile(sources as string[]);
    return new NextResponse(css, {
      headers: { "Content-Type": "text/css; charset=utf-8", "Cache-Control": "no-store" },
    });
  } catch (err) {
    console.error("[api/template/css] tailwind compile failed", err);
    return NextResponse.json({ error: "Failed to compile CSS" }, { status: 500 });
  }
}
