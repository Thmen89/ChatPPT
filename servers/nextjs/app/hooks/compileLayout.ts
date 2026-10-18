"use client";

import { ensureTemplateCss } from "./templateCss";
import React from "react";
import * as z from "zod";
import * as Recharts from "recharts";
import * as Babel from "@babel/standalone";
import * as d3 from "d3";
import * as LucideReact from "lucide-react";
import * as ReactJsxRuntime from "react/jsx-runtime";
import * as ChartJs from "chart.js";
import * as ChartJsAuto from "chart.js/auto";
import * as RemoteSvgIcon from "@/app/hooks/useRemoteSvgIcon";
import { IconSchema, ImageSchema } from "@/app/presentation-templates/defaultSchemes";
import * as UtilsApi from "@/utils/api";
import { resolveBackendAssetUrl } from "@/utils/api";

/** Names already bound from Recharts (and core helpers) — do not shadow with Lucide. */
const RESERVED_FOR_LUCIDE = new Set([
    "Fragment",
    "useState",
    "useEffect",
    "useRef",
    "useMemo",
    "useCallback",
    "z",
    "ResponsiveContainer",
    "LineChart",
    "Line",
    "BarChart",
    "Bar",
    "XAxis",
    "YAxis",
    "CartesianGrid",
    "Tooltip",
    "Legend",
    "PieChart",
    "Pie",
    "Cell",
    "AreaChart",
    "Area",
    "RadarChart",
    "Radar",
    "PolarGrid",
    "PolarAngleAxis",
    "PolarRadiusAxis",
    "ComposedChart",
    "ScatterChart",
    "Scatter",
    "RadialBarChart",
    "RadialBar",
    "ReferenceLine",
    "ReferenceDot",
    "ReferenceArea",
    "Brush",
    "LabelList",
    "Label",
    "Text",
]);

function isLucideComponent(value: unknown): boolean {
    return typeof value === "function" || (typeof value === "object" && value !== null);
}

function getLucideBindingLines(layoutCode: string): string {
    const requestedBindings = new Map<string, string>();
    const declaredComponents = new Set<string>();
    const bindings: string[] = [];

    for (const match of layoutCode.matchAll(
        /\b(?:const|let|var|function|class)\s+([A-Z][A-Za-z0-9_$]*)\b/g
    )) {
        declaredComponents.add(match[1]);
    }

    const importPattern = /import\s+\{([\s\S]*?)\}\s+from\s+['"]lucide-react['"];?/g;

    for (const match of layoutCode.matchAll(importPattern)) {
        const specifiers = match[1].split(",");
        for (const specifier of specifiers) {
            const [importedName, localName = importedName] = specifier
                .trim()
                .split(/\s+as\s+/);

            if (!importedName || !/^[A-Z][A-Za-z0-9_$]*$/.test(localName)) continue;
            requestedBindings.set(localName, importedName);
        }
    }

    // Generated layouts sometimes omit Lucide imports entirely. Any undefined
    // capitalized JSX component gets a Lucide component or a visible placeholder.
    for (const match of layoutCode.matchAll(/<\s*([A-Z][A-Za-z0-9_$]*)(?![A-Za-z0-9_$.])/g)) {
        const componentName = match[1];
        if (!requestedBindings.has(componentName)) {
            requestedBindings.set(componentName, componentName);
        }
    }

    for (const [localName, importedName] of requestedBindings) {
        if (RESERVED_FOR_LUCIDE.has(localName)) continue;
        if (localName === "Icon" || localName === "LucideIcon") continue;
        if (declaredComponents.has(localName)) continue;

        const resolvedName = isLucideComponent(
            (LucideReact as Record<string, unknown>)[importedName]
        )
            ? importedName
            : "CircleHelp";

        bindings.push(`const ${localName} = _Lucide[${JSON.stringify(resolvedName)}];`);
    }

    return bindings.join("\n");
}

export interface CompiledLayout {
    component: React.ComponentType<{ data: any }>;
    layoutId: string;
    layoutName: string;
    layoutDescription: string;
    schema: any;
    sampleData: Record<string, any>;
    schemaJSON: any;
}

function isLikelyBackendAssetPath(value: string): boolean {
    if (!value) return false;
    if (value.startsWith("file://")) return true;
    if (value.startsWith("/app_data/") || value.startsWith("/static/")) return true;
    if (value.startsWith("app_data/") || value.startsWith("static/")) return true;
    return value.includes("/app_data/") || value.includes("/static/");
}

function normalizeLayoutAssetUrls<T>(value: T): T {
    if (typeof value === "string") {
        const trimmedValue = value.trim();
        if (!isLikelyBackendAssetPath(trimmedValue)) {
            return value;
        }
        return resolveBackendAssetUrl(trimmedValue) as T;
    }

    if (Array.isArray(value)) {
        return value.map((item) => normalizeLayoutAssetUrls(item)) as T;
    }

    if (value && typeof value === "object") {
        const normalizedEntries = Object.entries(value as Record<string, unknown>).map(
            ([key, item]) => [key, normalizeLayoutAssetUrls(item)]
        );
        return Object.fromEntries(normalizedEntries) as T;
    }

    return value;
}

function normalizeHardcodedBackendUrlsInCode(layoutCode: string): string {
    // Keep /app_data and /static paths origin-agnostic so nginx can proxy them.
    return layoutCode.replace(
        /https?:\/\/(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(?:8000|5000)(?=\/(?:app_data|static)\/)/g,
        ""
    );
}

/**
 * Modules a runtime-loaded layout may import. Template folders (`<data>/templates/<id>/`)
 * use the same imports as the built-ins; anything else is a sibling file in the folder.
 */
const SHARED_SCHEMAS = { ImageSchema, IconSchema };
const RUNTIME_MODULES: Record<string, unknown> = {
    react: React,
    "react/jsx-runtime": ReactJsxRuntime,
    zod: { ...z, z, default: z },
    recharts: Recharts,
    "lucide-react": LucideReact,
    d3,
    "chart.js": ChartJs,
    "chart.js/auto": { ...ChartJsAuto, default: ChartJsAuto.default },
    "@/app/hooks/useRemoteSvgIcon": RemoteSvgIcon,
    "@/app/presentation-templates/defaultSchemes": SHARED_SCHEMAS,
    "@/utils/api": UtilsApi,
};

export interface CompileOptions {
    /** Other `.ts`/`.tsx` files of the template folder, by file name, for `./Helper` imports. */
    modules?: Record<string, string>;
    /** Template id, for messages. */
    templateId?: string;
}

type ModuleExports = Record<string, any>;

const BABEL_OPTIONS = {
    presets: [
        ["react", { runtime: "classic" }],
        ["typescript", { isTSX: true, allExtensions: true }],
    ],
    plugins: ["transform-modules-commonjs"],
    sourceType: "unambiguous" as const,
};

function resolveSibling(specifier: string, modules: Record<string, string>): string | null {
    const base = specifier.replace(/^\.\//, "");
    if (base.includes("/")) return null;
    for (const candidate of [base, `${base}.tsx`, `${base}.ts`]) {
        if (candidate in modules) return candidate;
    }
    return null;
}

/**
 * Run one TSX file: ES module (imports/exports, like the built-in layouts) or the plain
 * script form PPTX import generates (`const layoutId = ...; const dynamicSlideLayout = ...`).
 * React, zod, Recharts names and Lucide icons are in scope either way.
 */
function runModule(
    code: string,
    options: CompileOptions,
    cache: Map<string, ModuleExports>,
    lucideScope: boolean,
): { exports: ModuleExports; script: ModuleExports } {
    const modules = options.modules ?? {};
    const compiled = Babel.transform(normalizeHardcodedBackendUrlsInCode(code), BABEL_OPTIONS).code ?? "";

    const requireModule = (specifier: string): unknown => {
        if (specifier in RUNTIME_MODULES) return RUNTIME_MODULES[specifier];
        if (/(^|\/)defaultSchemes$/.test(specifier)) return SHARED_SCHEMAS;
        const sibling = resolveSibling(specifier, modules);
        if (sibling) {
            const cached = cache.get(sibling);
            if (cached) return cached;
            const exports: ModuleExports = {};
            cache.set(sibling, exports); // cycles see the partial exports, as in CommonJS
            Object.assign(exports, runModule(modules[sibling], options, cache, false).exports);
            return exports;
        }
        throw new Error(
            `'${specifier}' cannot be imported by a template layout${options.templateId ? ` (${options.templateId})` : ""}. ` +
            `Use react, zod, recharts, lucide-react, d3, chart.js, or a file in the template folder.`
        );
    };

    const lucideBindings = lucideScope ? getLucideBindingLines(code) : "";
    const factory = new Function(
        "React", "_z", "Recharts", "_d3", "_Lucide", "_shared", "require", "module", "exports",
        `
        const z = _z;
        const d3 = _d3;
        const { useState, useEffect, useRef, useMemo, useCallback, Fragment } = React;
        const {
            ResponsiveContainer, LineChart, Line, BarChart, Bar,
            XAxis, YAxis, CartesianGrid, Tooltip, Legend,
            PieChart, Pie, Cell, AreaChart, Area,
            RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
            ComposedChart, ScatterChart, Scatter,
            RadialBarChart, RadialBar,
            ReferenceLine, ReferenceDot, ReferenceArea,
            Brush, LabelList, Label, Text
        } = Recharts || {};
        const { ImageSchema, IconSchema } = _shared;
        ${lucideBindings}
        return (function () {
            ${compiled}
            return {
                component: typeof dynamicSlideLayout !== 'undefined' ? dynamicSlideLayout
                    : (typeof DefaultLayout !== 'undefined' ? DefaultLayout : undefined),
                layoutId: typeof layoutId !== 'undefined' ? layoutId : undefined,
                layoutName: typeof layoutName !== 'undefined' ? layoutName : undefined,
                layoutDescription: typeof layoutDescription !== 'undefined' ? layoutDescription : undefined,
                Schema: typeof Schema !== 'undefined' ? Schema : undefined,
            };
        })();
        `
    );
    const module = { exports: {} as ModuleExports };
    const script = factory(React, z, Recharts, d3, LucideReact, SHARED_SCHEMAS, requireModule, module, module.exports);
    return { exports: module.exports, script };
}

/**
 * Compiles a layout (TSX source) into a usable React component. Used for template folders
 * loaded at runtime and for layouts being edited in the PPTX import flow.
 */
export function compileCustomLayout(layoutCode: string, options: CompileOptions = {}): CompiledLayout | null {
    ensureTemplateCss(layoutCode);
    Object.values(options.modules ?? {}).forEach(ensureTemplateCss);
    try {
        const { exports, script } = runModule(layoutCode, options, new Map(), true);
        const pick = (...names: string[]) => names.map((n) => exports[n]).find((v) => v !== undefined);

        const component =
            pick("default", "dynamicSlideLayout", "DefaultLayout") ?? script.component;
        const layoutId = pick("layoutId", "slideLayoutId") ?? script.layoutId ?? "custom-layout";
        const layoutName = pick("layoutName", "slideLayoutName") ?? script.layoutName ?? "Custom Layout";
        const layoutDescription =
            pick("layoutDescription", "slideLayoutDescription") ?? script.layoutDescription ?? "";
        const Schema = pick("Schema") ?? script.Schema ?? null;

        if (!component) {
            console.error("No component found in compiled code");
            return null;
        }

        const wrappedComponent: React.ComponentType<{ data: any }> = ({ data, ...props }) => {
            const normalizedData = React.useMemo(() => normalizeLayoutAssetUrls(data), [data]);
            return React.createElement(component, { ...(props as any), data: normalizedData });
        };
        wrappedComponent.displayName = `CompiledTemplateLayout(${layoutName || layoutId || "Custom"})`;

        let sampleData: Record<string, any> = {};
        if (Schema) {
            try {
                sampleData = normalizeLayoutAssetUrls(Schema.parse({}));
            } catch (e) {
                console.warn("Could not parse schema defaults:", e);
            }
        }
        const schemaJSON = Schema ? z.toJSONSchema(Schema) : {};

        return {
            component: wrappedComponent,
            layoutId,
            layoutName,
            layoutDescription,
            schema: Schema,
            sampleData,
            schemaJSON,
        };
    } catch (error) {
        console.error(`Error compiling layout${options.templateId ? ` of ${options.templateId}` : ""}:`, error);
        return null;
    }
}
