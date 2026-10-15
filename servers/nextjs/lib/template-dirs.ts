import fs from "fs/promises";
import path from "path";

/**
 * Template discovery, the same rules as `servers/fastapi/chatppt/templates.py`:
 * built-in folders under `app/presentation-templates/<id>/` plus user folders under
 * `<data>/templates/<id>/` (`CHATPPT_PATHS__TEMPLATES`, else `APP_DATA_DIRECTORY/templates`).
 * A user folder with the same id replaces the built-in one.
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
  theme?: string;
  fonts: string[];
};

export type TemplateDir = { id: string; dir: string; source: TemplateSource };

const MANIFEST_NAME = "template.json";
const LEGACY_SETTINGS_NAME = "settings.json";
const SKIP_FILES = new Set(["ExampleSlideLayoutTemplate.tsx"]);
const ICON_WEIGHTS = new Set(["bold", "duotone", "fill", "light", "regular", "thin"]);
const TEMPLATE_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;

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

/** Resolve a template id to its folder; data folders win over built-ins. */
export async function resolveTemplateDir(id: string): Promise<TemplateDir | null> {
  if (!TEMPLATE_ID.test(id) && !/^[A-Za-z0-9_-]{1,64}$/.test(id)) return null;
  let found: TemplateDir | null = null;
  for (const root of templateRoots()) {
    const dir = path.join(root.dir, id);
    if (await isDir(dir)) found = { id, dir, source: root.source };
  }
  return found;
}

/** Every template folder by id, data folders replacing built-ins with the same id. */
export async function listTemplateDirs(): Promise<TemplateDir[]> {
  const byId = new Map<string, TemplateDir>();
  for (const root of templateRoots()) {
    if (!(await isDir(root.dir))) continue;
    for (const entry of await fs.readdir(root.dir, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
      byId.set(entry.name, { id: entry.name, dir: path.join(root.dir, entry.name), source: root.source });
    }
  }
  return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
}

function normalizeIconWeight(value: unknown, fallback = "regular"): string {
  if (typeof value !== "string") return fallback;
  const v = value.trim().toLowerCase().replace("_", "-");
  return ICON_WEIGHTS.has(v) ? v : fallback;
}

/** `template.json`, else the legacy `settings.json` plus the folder name. */
export async function readTemplateManifest(dir: string): Promise<TemplateManifest> {
  const id = path.basename(dir);
  try {
    const raw = JSON.parse(await fs.readFile(path.join(dir, MANIFEST_NAME), "utf8")) as Partial<TemplateManifest>;
    return {
      id: raw.id ?? id,
      name: raw.name ?? id,
      description: raw.description ?? "",
      version: typeof raw.version === "number" ? raw.version : 1,
      ordered: Boolean(raw.ordered),
      default: Boolean(raw.default),
      icon_weight: normalizeIconWeight(raw.icon_weight),
      layouts: Array.isArray(raw.layouts) ? raw.layouts : undefined,
      theme: typeof raw.theme === "string" ? raw.theme : undefined,
      fonts: Array.isArray(raw.fonts) ? raw.fonts : [],
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
    id,
    name: id,
    description: typeof legacy.description === "string" ? legacy.description : "",
    version: 1,
    ordered: Boolean(legacy.ordered),
    default: Boolean(legacy.default),
    icon_weight: normalizeIconWeight(legacy.icon_weight),
    fonts: [],
  };
}

/** Layout files in the order the manifest gives, else every .tsx sorted by name. */
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
  return entries
    .filter((e) => e.isFile() && e.name.endsWith(".tsx"))
    .map((e) => e.name)
    .filter((n) => !SKIP_FILES.has(n) && !n.includes(".test.") && !n.includes(".spec."))
    .sort();
}
