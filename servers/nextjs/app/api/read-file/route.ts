import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

/**
 * Text of a document decomposed by FastAPI's /files/decompose, for the documents
 * preview. Only files under the temp folder (where uploads and their extracted text
 * live) can be read: never APP_DATA_DIRECTORY, which holds chatppt.toml, userConfig.json
 * and the database. The session check happens in proxy.ts.
 */
function tempRoot(): string {
  return fs.realpathSync(path.resolve(process.env.TEMP_DIRECTORY || "/tmp/chatppt"));
}

function isReadablePath(filePath: unknown, root: string): string | null {
  if (typeof filePath !== "string" || !filePath || filePath.includes("\0")) return null;
  let resolved: string;
  try {
    resolved = fs.realpathSync(path.resolve(filePath));
  } catch {
    return null;
  }
  if (!resolved.startsWith(root + path.sep)) return null;
  return fs.statSync(resolved).isFile() ? resolved : null;
}

export async function POST(request: Request) {
  let filePath: unknown;
  try {
    ({ filePath } = await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }
  let root: string;
  try {
    root = tempRoot();
  } catch {
    return NextResponse.json({ error: "File not found" }, { status: 404 });
  }
  const resolved = isReadablePath(filePath, root);
  if (!resolved) {
    return NextResponse.json({ error: "Access denied: File path not allowed" }, { status: 403 });
  }
  try {
    return NextResponse.json({ content: fs.readFileSync(resolved, "utf-8") });
  } catch (error) {
    console.error("Error reading file:", error);
    return NextResponse.json({ error: "Failed to read file" }, { status: 500 });
  }
}
