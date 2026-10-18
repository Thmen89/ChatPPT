"use client";

import { useState, useEffect, useCallback, useSyncExternalStore } from "react";

import { compileCustomLayout, CompiledLayout } from "./compileLayout";
import { runtimeTemplateId, setDataTemplateIds } from "./runtimeTemplates";
import TemplateService from "../(presentation-generator)/services/api/template";

/**
 * Runtime templates: folders under `<data>/templates/` (dropped in or imported from a
 * PPTX), fetched from FastAPI and compiled in the browser. Compiled results are cached per
 * template fingerprint; `refreshRuntimeTemplates()` (run when the template list loads and
 * when the window regains focus) drops any template whose files changed, so edits on disk
 * show up without a rebuild or a reload.
 */

export interface TemplateSummary {
    id: string;
    name: string;
    description?: string | null;
    total_layouts: number;
    fingerprint?: string | null;
}

export interface RawLayoutResponse {
    template: string;
    layout_id: string;
    layout_name: string;
    layout_code: string;
    fonts?: Record<string, string> | null;
}

export interface CustomTemplateDetailResponse {
    layouts: RawLayoutResponse[];
    template: any;
    fonts?: Record<string, string> | null;
    modules?: Record<string, string>;
    fingerprint?: string | null;
}

export interface CustomTemplateLayout extends CompiledLayout {
    templateId: string;
    rawLayoutId: string;
    rawLayoutName: string;
    layoutCode: string;
    fonts?: Record<string, string> | null;
}

export interface CustomTemplateDetail {
    layouts: CustomTemplateLayout[];
    name: string;
    description: string;
    id: string;
    template: any;
    fonts?: Record<string, string> | null;
    fingerprint?: string | null;
}

export interface CustomTemplates {
    id: string;
    name: string;
    layoutCount: number;
    isCustom: true;
}

const detailsCache = new Map<string, CustomTemplateDetail>();
const inFlight = new Map<string, Promise<CustomTemplateDetail | null>>();
const knownFingerprints = new Map<string, string>();

// ---- change notifications (hot reload) -------------------------------------------------

let version = 0;
const listeners = new Set<() => void>();

function notify(): void {
    version += 1;
    listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    ensureFocusRefresh();
    return () => listeners.delete(listener);
}

/** Re-renders when any runtime template changed on disk. */
export function useRuntimeTemplatesVersion(): number {
    return useSyncExternalStore(subscribe, () => version, () => 0);
}

let focusRefreshInstalled = false;
function ensureFocusRefresh(): void {
    if (focusRefreshInstalled || typeof window === "undefined") return;
    focusRefreshInstalled = true;
    window.addEventListener("focus", () => {
        void refreshRuntimeTemplates().catch(() => undefined);
    });
    void refreshRuntimeTemplates().catch(() => undefined);
}

let summariesPromise: Promise<TemplateSummary[]> | null = null;

/** Fetch the template list; forget compiled templates whose fingerprint changed. */
export async function refreshRuntimeTemplates(): Promise<TemplateSummary[]> {
    if (summariesPromise) return summariesPromise;
    summariesPromise = (async () => {
        try {
            const data: TemplateSummary[] = await TemplateService.getCustomTemplateSummaries();
            const runtime = data.filter((item) => item.total_layouts && item.total_layouts > 0);
            let changed = setDataTemplateIds(runtime.map((item) => item.id));
            for (const item of runtime) {
                const previous = knownFingerprints.get(item.id);
                if (item.fingerprint && previous && previous !== item.fingerprint) {
                    detailsCache.delete(item.id);
                    changed = true;
                }
                if (item.fingerprint) knownFingerprints.set(item.id, item.fingerprint);
            }
            if (changed) notify();
            return data;
        } finally {
            summariesPromise = null;
        }
    })();
    return summariesPromise;
}

// ---- fetch + compile ------------------------------------------------------------------

function compileDetail(id: string, data: CustomTemplateDetailResponse, name: string, description: string): CustomTemplateDetail {
    const layouts: CustomTemplateLayout[] = [];
    for (const layout of data.layouts) {
        const compiled = compileCustomLayout(layout.layout_code, { modules: data.modules, templateId: id });
        if (!compiled) {
            console.warn(`Failed to compile layout ${layout.layout_name} of ${id}`);
            continue;
        }
        layouts.push({
            ...compiled,
            templateId: layout.template,
            rawLayoutId: layout.layout_id,
            rawLayoutName: layout.layout_name,
            layoutCode: layout.layout_code,
            fonts: layout.fonts,
        });
    }
    if (data.fingerprint) knownFingerprints.set(id, data.fingerprint);
    return {
        layouts,
        name: data.template?.name || name,
        description: data.template?.description || description,
        id,
        template: data.template ?? null,
        fonts: data.fonts,
        fingerprint: data.fingerprint,
    };
}

/**
 * Fetch and compile one runtime template (any id form: `custom-<uuid>`, a bare UUID or a
 * folder id). Cached until its files change; concurrent calls share one request.
 */
export async function getCustomTemplateDetails(
    templateId: string,
    name: string = "Custom Template",
    description: string = "User-created template"
): Promise<CustomTemplateDetail | null> {
    if (!templateId) return null;
    const id = runtimeTemplateId(templateId);
    const cached = detailsCache.get(id);
    if (cached) return cached;
    const existing = inFlight.get(id);
    if (existing) return existing;

    const request = (async () => {
        try {
            const data: CustomTemplateDetailResponse = await TemplateService.getCustomTemplateDetails(id);
            const detail = compileDetail(id, data, name, description);
            detailsCache.set(id, detail);
            return detail;
        } finally {
            inFlight.delete(id);
        }
    })();
    inFlight.set(id, request);
    return request;
}

/** The first layout of a runtime template, compiled (template cards). */
export async function getCustomTemplateFirstSlidePreview(
    presentationIdOrCustomId: string
): Promise<CompiledLayout | null> {
    try {
        const detail = await getCustomTemplateDetails(presentationIdOrCustomId);
        return detail?.layouts[0] ?? null;
    } catch (err) {
        console.error("Error fetching first-slide preview:", err);
        return null;
    }
}

// ---- hooks ----------------------------------------------------------------------------

/** Runtime templates for the picker; also refreshes fingerprints (hot reload). */
export function useCustomTemplateSummaries() {
    const [templates, setTemplates] = useState<CustomTemplates[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchTemplates = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await refreshRuntimeTemplates();
            setTemplates(
                data
                    .filter((item) => item.total_layouts && item.total_layouts > 0)
                    .map((item) => ({
                        id: item.id,
                        name: item.name || "Custom Template",
                        layoutCount: item.total_layouts,
                        isCustom: true as const,
                    }))
            );
        } catch (err) {
            console.error("Error fetching custom templates:", err);
            setError(err instanceof Error ? err.message : "Unknown error");
            setTemplates([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchTemplates();
    }, [fetchTemplates]);

    return { templates, loading, error, refetch: fetchTemplates };
}

/** One runtime template, compiled; re-fetched when its files change on disk. */
export function useCustomTemplateDetails(templateDetail: { id: string; name: string; description: string }) {
    const id = templateDetail.id ? runtimeTemplateId(templateDetail.id) : "";
    const changes = useRuntimeTemplatesVersion();
    const [template, setTemplate] = useState<CustomTemplateDetail | null>(() => (id ? detailsCache.get(id) ?? null : null));
    const [loading, setLoading] = useState<boolean>(() => (id ? !detailsCache.has(id) : false));
    const [error, setError] = useState<string | null>(null);

    const fetchTemplateDetails = useCallback(async () => {
        if (!id) return;
        const cached = detailsCache.get(id);
        if (cached) {
            setTemplate(cached);
            setLoading(false);
            return;
        }
        setLoading(true);
        setError(null);
        try {
            setTemplate(await getCustomTemplateDetails(id, templateDetail.name, templateDetail.description));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
            setTemplate(null);
        } finally {
            setLoading(false);
        }
    }, [id, templateDetail.name, templateDetail.description]);

    useEffect(() => {
        if (id) fetchTemplateDetails();
    }, [id, changes, fetchTemplateDetails]);

    return { template, loading, error, refetch: fetchTemplateDetails, fonts: template?.fonts ?? {} };
}

/** First four layouts of a runtime template, compiled (template cards). */
export function useCustomTemplatePreview(presentationId: string) {
    const changes = useRuntimeTemplatesVersion();
    const [previewLayouts, setPreviewLayouts] = useState<CompiledLayout[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!presentationId) return;
        let cancelled = false;
        setLoading(true);
        getCustomTemplateDetails(presentationId)
            .then((detail) => {
                if (!cancelled) setPreviewLayouts(detail?.layouts.slice(0, 4) ?? []);
            })
            .catch((err) => console.error("Error fetching preview layouts:", err))
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [presentationId, changes]);

    return { previewLayouts, loading };
}

/** First layout of a runtime template, compiled. */
export function useCustomTemplateFirstSlidePreview(presentationIdOrCustomId: string) {
    const changes = useRuntimeTemplatesVersion();
    const [previewLayout, setPreviewLayout] = useState<CompiledLayout | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!presentationIdOrCustomId) return;
        let cancelled = false;
        setLoading(true);
        setError(null);
        getCustomTemplateFirstSlidePreview(presentationIdOrCustomId)
            .then((compiled) => {
                if (!cancelled) setPreviewLayout(compiled);
            })
            .catch((e) => {
                if (!cancelled) {
                    setError(e instanceof Error ? e.message : "Unknown error");
                    setPreviewLayout(null);
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [presentationIdOrCustomId, changes]);

    return { previewLayout, loading, error };
}
