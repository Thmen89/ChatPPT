import fs from "fs/promises";
import path from "path";

import { compileTemplateSchema } from "@/lib/compile-template-schema";
import { getFastApiAuthHeaders, getFastApiBaseUrl } from "@/lib/fastapi-internal";
import { listLayoutFiles, readTemplateManifest, resolveTemplateDir } from "@/lib/template-dirs";

export type BuiltinLayoutSlide = {
  id: string;
  name: string;
  description: string;
  json_schema: unknown;
};

const DEFAULT_ICON_WEIGHT = "bold";
const ALLOWED_ICON_WEIGHTS = new Set([
  "bold",
  "duotone",
  "fill",
  "light",
  "regular",
  "thin",
]);
function normalizeIconWeight(value: unknown): string {
  if (typeof value !== "string") {
    return DEFAULT_ICON_WEIGHT;
  }
  const normalized = value.trim().toLowerCase().replace("_", "-");
  return ALLOWED_ICON_WEIGHTS.has(normalized) ? normalized : DEFAULT_ICON_WEIGHT;
}

/**
 * Build layout + JSON schemas for a built-in template directory without importing
 * `presentation-templates/index.tsx` (that pulls Recharts/client bundles into RSC).
 *
 * Scans `app/presentation-templates/<group>/*.tsx` and runs the same schema compiler
 * the UI uses. Slide IDs match `getSchemaByTemplateId` in `presentation-templates/index.tsx`
 * (`id` is the fully-qualified `<group>:<layoutId>` form used by layout lookup).
 * Slide order is sorted by filename for stability (may differ slightly from registration
 * order in index.tsx).
 */
export async function buildBuiltinTemplateLayoutPayload(group: string): Promise<{
  name: string;
  ordered: boolean;
  icon_weight: string;
  slides: BuiltinLayoutSlide[];
} | null> {
  const resolved = await resolveTemplateDir(group);
  if (!resolved) {
    return null;
  }
  const manifest = await readTemplateManifest(resolved.dir);
  const tsxFiles = await listLayoutFiles(resolved.dir, manifest);

  const slides: BuiltinLayoutSlide[] = [];

  for (const file of tsxFiles) {
    const full = path.join(resolved.dir, file);
    const code = await fs.readFile(full, "utf8");
    const compiled = compileTemplateSchema(code);
    if (!compiled) {
      continue;
    }
    const qualifiedLayoutId = compiled.layoutId.includes(":")
      ? compiled.layoutId
      : `${group}:${compiled.layoutId}`;
    slides.push({
      id: qualifiedLayoutId,
      name: compiled.layoutName,
      description: compiled.layoutDescription,
      json_schema: compiled.schemaJSON,
    });
  }

  if (slides.length === 0) {
    return null;
  }

  return {
    name: group,
    ordered: manifest.ordered,
    icon_weight: normalizeIconWeight(manifest.icon_weight),
    slides,
  };
}

export type CustomLayoutCompileInput = {
  layout_id: string;
  layout_name: string;
  layout_code: string;
};

/**
 * Compile custom template slide layouts stored in the DB (same IDs as /schema?group=custom-*).
 */
export function buildCustomTemplateLayoutPayload(
  group: string,
  layouts: CustomLayoutCompileInput[],
): {
  name: string;
  ordered: boolean;
  icon_weight: string;
  slides: BuiltinLayoutSlide[];
} | null {
  if (!group.startsWith("custom-") || layouts.length === 0) {
    return null;
  }

  const slides: BuiltinLayoutSlide[] = [];

  for (const layout of layouts) {
    const compiled = compileTemplateSchema(layout.layout_code);
    if (!compiled) {
      console.warn(
        `[server-template-layouts] failed to compile custom layout ${layout.layout_name}`,
      );
      continue;
    }

    const qualifiedLayoutId = `${group}:${compiled.layoutId}`;
    slides.push({
      id: qualifiedLayoutId,
      name: compiled.layoutName || layout.layout_name,
      description: compiled.layoutDescription,
      json_schema: compiled.schemaJSON,
    });
  }

  if (slides.length === 0) {
    return null;
  }

  return {
    name: group,
    ordered: false,
    icon_weight: DEFAULT_ICON_WEIGHT,
    slides,
  };
}

type FastApiTemplateLayoutsResponse = {
  layouts?: Array<{
    layout_id: string;
    layout_name: string;
    layout_code: string;
  }>;
};

/**
 * Fetch custom template slide code from FastAPI and compile (for `/api/template?group=custom-*`).
 */
export async function buildCustomTemplateLayoutPayloadFromApi(
  group: string,
): Promise<{
  name: string;
  ordered: boolean;
  icon_weight: string;
  slides: BuiltinLayoutSlide[];
} | null> {
  if (!group.startsWith("custom-")) {
    return null;
  }

  const url = `${getFastApiBaseUrl()}/api/v1/ppt/template/${encodeURIComponent(group)}/layouts`;
  const response = await fetch(url, {
    headers: getFastApiAuthHeaders(),
    cache: "no-store",
  });

  if (!response.ok) {
    return null;
  }

  const data = (await response.json()) as FastApiTemplateLayoutsResponse;
  const layouts = data.layouts ?? [];
  if (layouts.length === 0) {
    return null;
  }

  return buildCustomTemplateLayoutPayload(
    group,
    layouts.map((layout) => ({
      layout_id: layout.layout_id,
      layout_name: layout.layout_name,
      layout_code: layout.layout_code,
    })),
  );
}
