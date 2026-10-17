import fs from "fs/promises";
import path from "path";

import { compileTemplateSchema } from "@/lib/compile-template-schema";
import {
  listLayoutFiles,
  resolveTemplateDir,
  templateFingerprint,
} from "@/lib/template-dirs";

export type BuiltinLayoutSlide = {
  id: string;
  name: string;
  description: string;
  json_schema: unknown;
};

export type TemplateLayoutPayload = {
  name: string;
  ordered: boolean;
  icon_weight: string;
  fingerprint: string;
  slides: BuiltinLayoutSlide[];
};

/** Compiled payloads by template id; reused while the folder's fingerprint is unchanged. */
const cache = new Map<string, TemplateLayoutPayload>();

/**
 * Layout ids + JSON schemas for any template folder (built-in or `<data>/templates/<id>/`)
 * without importing `presentation-templates/index.tsx` (that pulls Recharts/client bundles
 * into RSC). Slide ids are `<template id>:<layoutId>`, as the editor registry uses them.
 * Compiled once per folder fingerprint, so an edited layout is picked up on the next call.
 */
export async function buildTemplateLayoutPayload(group: string): Promise<TemplateLayoutPayload | null> {
  const resolved = await resolveTemplateDir(group);
  if (!resolved) {
    return null;
  }
  const fingerprint = await templateFingerprint(resolved);
  const cached = cache.get(resolved.id);
  if (cached?.fingerprint === fingerprint) {
    return cached;
  }

  const slides: BuiltinLayoutSlide[] = [];
  for (const file of await listLayoutFiles(resolved.dir, resolved.manifest)) {
    const code = await fs.readFile(path.join(resolved.dir, file), "utf8");
    const compiled = compileTemplateSchema(code);
    if (!compiled) {
      console.warn(`[server-template-layouts] could not read the schema of ${resolved.id}/${file}`);
      continue;
    }
    slides.push({
      id: compiled.layoutId.includes(":") ? compiled.layoutId : `${resolved.id}:${compiled.layoutId}`,
      name: compiled.layoutName,
      description: compiled.layoutDescription,
      json_schema: compiled.schemaJSON,
    });
  }
  if (slides.length === 0) {
    return null;
  }

  const payload: TemplateLayoutPayload = {
    name: resolved.id,
    ordered: resolved.manifest.ordered,
    icon_weight: resolved.manifest.icon_weight,
    fingerprint,
    slides,
  };
  cache.set(resolved.id, payload);
  return payload;
}
