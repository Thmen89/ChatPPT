/**
 * Startup banner: the ChatPPT logo (scripts/chatppt-ascii.txt, copied next to this file in
 * the image) and where to open the app. Colour only on a terminal, and never with NO_COLOR.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const useColor = Boolean(process.stdout.isTTY) && !process.env.NO_COLOR;
const paint = (code) => (text) => (useColor ? `\x1b[${code}m${text}\x1b[0m` : text);
const brand = paint("1;38;2;138;99;255");
const muted = paint("2;38;2;160;150;210");
const strong = paint("1");

function loadAscii() {
  const asciiPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "chatppt-ascii.txt");
  try {
    return fs.readFileSync(asciiPath, "utf8").replace(/\r/g, "").trimEnd();
  } catch {
    return "";
  }
}

/**
 * @param {object} opts
 * @param {number} opts.port      public port inside the container (Next.js)
 * @param {string} opts.dataDir   data folder in use
 * @param {number} [opts.startupMs] time from start.js to all processes answering
 */
export function printStartupBanner({ port, dataDir, startupMs }) {
  const ascii = loadAscii();
  const lines = [
    "",
    ...(ascii ? ascii.split("\n").map(brand) : []),
    "",
    `  ${brand("ChatPPT")} ${muted("lean, fast, customisable AI decks")}`,
    "",
    `  ${muted("Open      ")}${strong(`http://localhost:${port}`)} ${muted("(or the host port you mapped with -p)")}`,
    `  ${muted("MCP       ")}http://localhost:${port}/mcp`,
    `  ${muted("Health    ")}http://localhost:${port}/healthz`,
    `  ${muted("Data      ")}${dataDir}`,
    ...(startupMs != null ? [`  ${muted("Ready in  ")}${(startupMs / 1000).toFixed(1)} s`] : []),
    "",
  ];
  console.log(lines.join("\n"));
}
