/**
 * Styles for layouts compiled in the browser. Each layout source is sent once to
 * `/api/template/css`, which returns the Tailwind utilities it uses (compiled on the
 * server, no CDN); the result is appended to <head>. Requests are batched per tick.
 */

const seen = new Set<string>();
let pending: string[] = [];
let scheduled = false;

function hash(text: string): string {
  // FNV-1a, enough to de-duplicate sources within a page.
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return `${(h >>> 0).toString(36)}:${text.length}`;
}

async function flush(): Promise<void> {
  scheduled = false;
  const sources = pending;
  pending = [];
  if (sources.length === 0) return;
  try {
    const response = await fetch("/api/template/css", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ sources }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const style = document.createElement("style");
    style.dataset.chatpptTemplateCss = "";
    style.textContent = await response.text();
    document.head.appendChild(style);
  } catch (err) {
    console.warn("Could not load styles for runtime template layouts", err);
    sources.forEach((source) => seen.delete(hash(source)));
  }
}

/** Make sure the Tailwind classes used by `source` are styled on this page. */
export function ensureTemplateCss(source: string): void {
  if (typeof window === "undefined" || !source) return;
  const key = hash(source);
  if (seen.has(key)) return;
  seen.add(key);
  pending.push(source);
  if (!scheduled) {
    scheduled = true;
    setTimeout(() => void flush(), 0);
  }
}
