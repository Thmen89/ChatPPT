"use client";

import { useEffect, useState } from "react";
import { getApiUrl } from "@/utils/api";
import { BUILTIN_TEMPLATE_IDS } from "./runtimeTemplates";

export type TemplateOption = { id: string; name: string };

const titleCase = (id: string) => id.replace(/[-_]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Template ids and names for a picker, without loading any template code. Built-ins first,
 * then every folder in `<data>/templates/` (a folder with a built-in id replaces it). */
async function loadTemplates(): Promise<TemplateOption[]> {
  const options = new Map<string, TemplateOption>(
    [...BUILTIN_TEMPLATE_IDS].map((id) => [id, { id, name: titleCase(id) }])
  );
  try {
    const res = await fetch(getApiUrl("/api/v1/ppt/template/all"), { credentials: "include" });
    if (res.ok) {
      const list: { id: string; name?: string; total_layouts?: number | null }[] = await res.json();
      for (const t of list) {
        if (t.total_layouts) options.set(t.id, { id: t.id, name: t.name || titleCase(t.id) });
      }
    }
  } catch (e) {
    console.error("Failed to list templates:", e);
  }
  return [...options.values()];
}

export function useTemplateList(): TemplateOption[] {
  const [templates, setTemplates] = useState<TemplateOption[]>(() =>
    [...BUILTIN_TEMPLATE_IDS].map((id) => ({ id, name: titleCase(id) }))
  );
  useEffect(() => {
    let alive = true;
    loadTemplates().then((list) => alive && setTemplates(list));
    return () => {
      alive = false;
    };
  }, []);
  return templates;
}
