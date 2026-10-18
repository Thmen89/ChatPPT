/**
 * Which templates the editor loads at runtime. Built-in templates are compiled into the
 * app (`app/presentation-templates/index.tsx`); every folder under `<data>/templates/`
 * (dropped in, imported from a PPTX as `custom-<uuid>`, or overriding a built-in id) is
 * fetched from FastAPI and compiled in the browser by `compileLayout.ts`.
 */

/** Ids of the folders in `app/presentation-templates/` (their `template.json` ids). */
export const BUILTIN_TEMPLATE_IDS: ReadonlySet<string> = new Set([
  "general",
  "modern",
  "standard",
  "swift",
  "code",
  "education",
  "product-overview",
  "report",
  "pitch-deck",
  "neo-general",
  "neo-standard",
  "neo-modern",
  "neo-swift",
]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Canonical id of a runtime template: a bare UUID (older links) means `custom-<uuid>`. */
export function runtimeTemplateId(id: string): string {
  return UUID.test(id) ? `custom-${id.toLowerCase()}` : id;
}

/** Built-in ids that a `<data>/templates/<id>/` folder replaces (filled from the list). */
const overriddenBuiltins = new Set<string>();

/** Record the data folders' ids; true when the set of overridden built-ins changed. */
export function setDataTemplateIds(ids: Iterable<string>): boolean {
  const next = [...ids].filter((id) => BUILTIN_TEMPLATE_IDS.has(id));
  const changed = next.length !== overriddenBuiltins.size || next.some((id) => !overriddenBuiltins.has(id));
  overriddenBuiltins.clear();
  next.forEach((id) => overriddenBuiltins.add(id));
  return changed;
}

export function isRuntimeTemplate(group: string | null | undefined): boolean {
  if (!group) return false;
  return !BUILTIN_TEMPLATE_IDS.has(group) || overriddenBuiltins.has(group);
}

/** `slide.layout` without its `<template id>:` prefix (what the layout file declares). */
export function bareLayoutId(layout: string, group: string): string {
  for (const prefix of [`${group}:`, `${runtimeTemplateId(group)}:`]) {
    if (layout.startsWith(prefix)) return layout.slice(prefix.length);
  }
  return layout.startsWith("custom-") && layout.includes(":") ? layout.split(":")[1] : layout;
}
