import { createHash } from "crypto";
import fs from "fs/promises";
import path from "path";

/**
 * Template discovery, the same rules as `servers/fastapi/chatppt/templates.py`:
 * built-in folders under `app/presentation-templates/<folder>/` plus user folders under
 * `<data>/templates/<folder>/` (`CHATPPT_PATHS__TEMPLATES`, else `APP_DATA_DIRECTORY/templates`).
 * A template's id is the `id` in its `template.json` (else the folder name); a user folder
 * with the same id replaces the built-in one.
 */

export type TemplateSource = "builtin" | "data";

export type TemplateManifest = {
  id: string;
  name: string;
  description: string;
  version: number;
  ordered: boolean;
  default: boolean;
  icon_weight: string;
  layouts?: string[];
  fonts: Record<string, string>;
};

export type TemplateDir = { id: string; dir: string; source: TemplateSource; manifest: TemplateManifest };

const MANIFEST_NAME = "template.json";
const LEGACY_SETTINGS_NAME = "settings.json";
const SKIP_FILES = new Set(["ExampleSlideLayoutTemplate.tsx"]);
const ICON_WEIGHTS = new Set(["bold", "duotone", "fill", "light", "regular", "thin"]);
const TEMPLATE_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** Same rule as the backend: a `.tsx` declaring a layoutId is a layout; others are helpers. */
const DECLARES_LAYOUT = /(?:export\s+)?const\s+(?:slide)?[lL]ayoutId\s*(?::\s*string\s*)?=\s*['"`]/;

export function builtinTemplatesRoot(): string {
  return path.join(process.cwd(), "app", "presentation-templates");
}

export function dataTemplatesRoot(): string | null {
  const explicit = process.env.CHATPPT_PATHS__TEMPLATES?.trim();
  if (explicit) return explicit;
  const dataDir = process.env.APP_DATA_DIRECTORY?.trim();
  return dataDir ? path.join(dataDir, "templates") : null;
}

export function templateRoots(): { dir: string; source: TemplateSource }[] {
  const roots: { dir: string; source: TemplateSource }[] = [
    { dir: builtinTemplatesRoot(), source: "builtin" },
  ];
  const data = dataTemplatesRoot();
  if (data) roots.push({ dir: data, source: "data" });
  return roots;
}

async function isDir(p: string): Promise<boolean> {
  try {
    return (await fs.stat(p)).isDirectory();
  } catch {
    return false;
  }
}

/** Every template by id, data folders replacing built-ins with the same id. */
export async function listTemplateDirs(): Promise<TemplateDir[]> {
  const byId = new Map<string, TemplateDir>();
  for (const root of templateRoots()) {
    if (!(await isDir(root.dir))) continue;
    for (const entry of await fs.readdir(root.dir, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
      const dir = path.join(root.dir, entry.name);
      const manifest = await readTemplateManifest(dir);
      if (!TEMPLATE_ID.test(manifest.id)) continue;
      byId.set(manifest.id, { id: manifest.id, dir, source: root.source, manifest });
    }
  }
  return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
}

/** Resolve a template id to its folder; a bare UUID also finds `custom-<uuid>` (imports). */
export async function resolveTemplateDir(id: string): Promise<TemplateDir | null> {
  const wanted = UUID.test(id) ? `custom-${id.toLowerCase()}` : id;
  if (!TEMPLATE_ID.test(wanted)) return null;
  return (await listTemplateDirs()).find((t) => t.id === wanted) ?? null;
}

function normalizeIconWeight(value: unknown, fallback = "regular"): string {
  if (typeof value !== "string") return fallback;
  const v = value.trim().toLowerCase().replace("_", "-");
  return ICON_WEIGHTS.has(v) ? v : fallback;
}

function normalizeFonts(value: unknown): Record<string, string> {
  if (Array.isArray(value)) {
    return Object.fromEntries(
      value.map((file) => [path.parse(String(file)).name, `fonts/${path.basename(String(file))}`]),
    );
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
    );
  }
  return {};
}

/** `template.json`, else the legacy `settings.json` plus the folder name. */
export async function readTemplateManifest(dir: string): Promise<TemplateManifest> {
  const folder = path.basename(dir);
  try {
    const raw = JSON.parse(await fs.readFile(path.join(dir, MANIFEST_NAME), "utf8")) as Partial<TemplateManifest>;
    return {
      id: raw.id ?? folder,
      name: raw.name ?? folder,
      description: raw.description ?? "",
      version: typeof raw.version === "number" ? raw.version : 1,
      ordered: Boolean(raw.ordered),
      default: Boolean(raw.default),
      icon_weight: normalizeIconWeight(raw.icon_weight),
      layouts: Array.isArray(raw.layouts) ? raw.layouts : undefined,
      fonts: normalizeFonts(raw.fonts),
    };
  } catch {
    // fall through to legacy settings
  }
  let legacy: Record<string, unknown> = {};
  try {
    legacy = JSON.parse(await fs.readFile(path.join(dir, LEGACY_SETTINGS_NAME), "utf8"));
  } catch {
    // optional
  }
  return {
    id: folder.toLowerCase(),
    name: folder,
    description: typeof legacy.description === "string" ? legacy.description : "",
    version: 1,
    ordered: Boolean(legacy.ordered),
    default: Boolean(legacy.default),
    icon_weight: normalizeIconWeight(legacy.icon_weight),
    fonts: {},
  };
}

/** Layout files in the order the manifest gives, else every layout .tsx sorted by name. */
export async function listLayoutFiles(dir: string, manifest: TemplateManifest): Promise<string[]> {
  if (manifest.layouts?.length) {
    const present: string[] = [];
    for (const name of manifest.layouts) {
      try {
        await fs.access(path.join(dir, name));
        present.push(name);
      } catch {
        // listed but missing: skip
      }
    }
    return present;
  }
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const candidates = entries
    .filter((e) => e.isFile() && e.name.endsWith(".tsx"))
    .map((e) => e.name)
    .filter((n) => !SKIP_FILES.has(n) && !n.includes(".test.") && !n.includes(".spec."))
    .sort();
  const layouts: string[] = [];
  for (const name of candidates) {
    if (DECLARES_LAYOUT.test(await fs.readFile(path.join(dir, name), "utf8"))) layouts.push(name);
  }
  return layouts;
}

/** Changes whenever any file in the folder changes; the cache key for compiled schemas. */
export async function templateFingerprint(t: TemplateDir): Promise<string> {
  const hash = createHash("sha1");
  const entries = (await fs.readdir(t.dir, { withFileTypes: true }))
    .filter((e) => e.isFile())
    .map((e) => e.name)
    .sort();
  for (const name of entries) {
    const st = await fs.stat(path.join(t.dir, name), { bigint: true });
    hash.update(`${name}:${st.mtimeNs}:${st.size};`);
  }
  return hash.digest("hex").slice(0, 12);
}
