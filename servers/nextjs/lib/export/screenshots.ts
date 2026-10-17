/**
 * Pictures of what PowerPoint cannot draw natively (svg, canvas, tables, gradients, odd
 * borders): each target is isolated (everything else on the page made invisible, its
 * ancestors' backgrounds stripped) and captured with a transparent background, the way
 * the earlier export bundle did it. Targets that cannot bleed into each other share one
 * isolation pass and one capture, cropped per target, instead of three round trips each.
 */
import type { CDPSession, Page } from "playwright-core";
import sharp from "sharp";

type Target = any;

type Rect = { x: number; y: number; width: number; height: number };
type Measured = { id: string; clip: Rect | null; reach: Rect | null };

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
/** How far a target may paint outside its box (shadows, overflow) and still share a capture. */
const BLEED = 32;

/** Document-space boxes of the targets, plus the ancestry needed to group them. Runs in the page. */
function measureInPage(args: { ids: string[]; bleed: number }) {
  const { ids, bleed } = args;
  const sx = window.visualViewport ? window.visualViewport.pageLeft : window.scrollX;
  const sy = window.visualViewport ? window.visualViewport.pageTop : window.scrollY;
  const elements = ids.map((id) => document.querySelector(`[data-pptx-element-identifier="${id}"]`));
  const measured = ids.map((id, i) => {
    const el = elements[i];
    if (!el || el.getClientRects().length === 0) return { id, clip: null, reach: null };
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return { id, clip: null, reach: null };
    let left = r.left;
    let top = r.top;
    let right = r.right;
    let bottom = r.bottom;
    for (const d of Array.from(el.querySelectorAll("*"))) {
      const b = d.getBoundingClientRect();
      if (b.width === 0 && b.height === 0) continue;
      left = Math.min(left, b.left);
      top = Math.min(top, b.top);
      right = Math.max(right, b.right);
      bottom = Math.max(bottom, b.bottom);
    }
    return {
      id,
      clip: { x: r.x + sx, y: r.y + sy, width: r.width, height: r.height },
      reach: {
        x: left + sx - bleed,
        y: top + sy - bleed,
        width: right - left + 2 * bleed,
        height: bottom - top + 2 * bleed,
      },
    };
  });
  const related: [number, number][] = [];
  for (let i = 0; i < elements.length; i++) {
    for (let j = i + 1; j < elements.length; j++) {
      const a = elements[i];
      const b = elements[j];
      if (a && b && (a.contains(b) || b.contains(a))) related.push([i, j]);
    }
  }
  return { measured, related };
}

/** Make only the targets visible (the bundle's isolation rules). Runs in the page. */
function isolateInPage(args: {
  scope: string;
  targets: { id: string; children: boolean; noText: boolean }[];
  scrollTop: number | null;
}) {
  const { scope, targets, scrollTop } = args;
  if (scrollTop !== null) window.scrollTo(0, scrollTop);
  const scrolledTo = window.scrollY;
  const doc = document;
  const nodes = targets.map((t) => doc.querySelector(`[data-pptx-element-identifier="${t.id}"]`));
  for (const node of nodes) {
    if (!node || node.tagName.toLowerCase() !== "svg") continue;
    // Give gradient/clip ids a unique prefix and resolve var() paints, so the svg renders
    // the same once its surroundings are hidden.
    const svg = node as SVGSVGElement;
    const withId = Array.from(svg.querySelectorAll("[id]"));
    const renamed = new Map<string, string>();
    for (const el of withId) {
      const id = el.getAttribute("id");
      if (id) renamed.set(id, `${scope}__${id}`);
    }
    withId.forEach((el) => {
      const id = el.getAttribute("id");
      if (!id) return;
      const next = renamed.get(id);
      if (next && next !== id) el.setAttribute("id", next);
    });
    const refAttrs = [
      "fill",
      "stroke",
      "filter",
      "clip-path",
      "mask",
      "marker-start",
      "marker-mid",
      "marker-end",
      "href",
      "xlink:href",
    ];
    const rewrite = (value: string) =>
      value.replace(/url\(#([^\)]+)\)/g, (match, id) => {
        const next = renamed.get(id);
        return next ? `url(#${next})` : match;
      });
    for (const el of Array.from(svg.querySelectorAll("*"))) {
      for (const attr of refAttrs) {
        const value = el.getAttribute(attr);
        if (value && value.includes("url(#")) el.setAttribute(attr, rewrite(value));
      }
      const style = el.getAttribute("style");
      if (style && style.includes("url(#")) el.setAttribute("style", rewrite(style));
    }
    for (const style of Array.from(svg.querySelectorAll("style"))) {
      if (style.textContent && style.textContent.includes("url(#")) style.textContent = rewrite(style.textContent);
    }
    const paints = ["fill", "stroke", "stop-color"];
    for (const el of [svg, ...Array.from(svg.querySelectorAll("*"))]) {
      const computed = window.getComputedStyle(el);
      for (const paint of paints) {
        const raw = el.getAttribute(paint) || (el as any).style?.getPropertyValue(paint) || "";
        if (raw.includes("var(")) {
          const value = computed.getPropertyValue(paint) || (computed as any)[paint];
          if (value && value !== "none") el.setAttribute(paint, value);
        }
      }
    }
  }
  doc.body.setAttribute("data-pptx-scope", scope);
  const style = doc.createElement("style");
  style.setAttribute("data-pptx-style", scope);
  style.textContent = `
    html, body { background: transparent !important; }
    [data-pptx-scope="${scope}"] *:not([data-pptx-visible="${scope}"]):not([data-pptx-ancestor="${scope}"]) {
      opacity: 0 !important;
      pointer-events: none !important;
    }
    [data-pptx-visible="${scope}"], [data-pptx-ancestor="${scope}"] { visibility: visible !important; }
    [data-pptx-ancestor="${scope}"],
    [data-pptx-ancestor="${scope}"]::before,
    [data-pptx-ancestor="${scope}"]::after {
      background: none !important;
      background-color: transparent !important;
      background-image: none !important;
      box-shadow: none !important;
      border-color: transparent !important;
      outline: none !important;
    }
    [data-pptx-exclude-text="${scope}"],
    [data-pptx-exclude-text="${scope}"] *,
    [data-pptx-exclude-text="${scope}"]::before,
    [data-pptx-exclude-text="${scope}"]::after,
    [data-pptx-exclude-text="${scope}"] *::before,
    [data-pptx-exclude-text="${scope}"] *::after {
      color: transparent !important;
      -webkit-text-fill-color: transparent !important;
      text-shadow: none !important;
    }
    [data-pptx-exclude-text="${scope}"] svg text,
    [data-pptx-exclude-text="${scope}"] svg tspan,
    [data-pptx-exclude-text="${scope}"] svg tref,
    [data-pptx-exclude-text="${scope}"] svg textPath {
      fill: transparent !important;
      stroke: transparent !important;
    }
    [data-pptx-hidden="${scope}"] { opacity: 0 !important; visibility: hidden !important; }
  `;
  doc.head.appendChild(style);
  // Nodes on the way to any target stay; everything beside them is hidden.
  const kept = new Set<Element>();
  for (const node of nodes) {
    for (let el: Element | null = node; el; el = el.parentElement) kept.add(el);
  }
  targets.forEach((target, i) => {
    const node = nodes[i];
    if (!node) return;
    node.setAttribute("data-pptx-visible", scope);
    if (target.children) node.querySelectorAll("*").forEach((el) => el.setAttribute("data-pptx-visible", scope));
    if (target.noText) node.setAttribute("data-pptx-exclude-text", scope);
    let child: Element = node;
    for (let parent = node.parentElement; parent; child = parent, parent = parent.parentElement) {
      parent.setAttribute("data-pptx-ancestor", scope);
      for (const sibling of Array.from(parent.children) as HTMLElement[]) {
        if (sibling === child || kept.has(sibling) || sibling.getAttribute("data-pptx-hidden") === scope) continue;
        const opacity = sibling.style.getPropertyValue("opacity");
        const opacityPriority = sibling.style.getPropertyPriority("opacity");
        const visibility = sibling.style.getPropertyValue("visibility");
        const visibilityPriority = sibling.style.getPropertyPriority("visibility");
        if (opacity) sibling.setAttribute("data-pptx-prev-opacity", opacity);
        if (opacityPriority) sibling.setAttribute("data-pptx-prev-opacity-priority", opacityPriority);
        if (visibility) sibling.setAttribute("data-pptx-prev-visibility", visibility);
        if (visibilityPriority) sibling.setAttribute("data-pptx-prev-visibility-priority", visibilityPriority);
        sibling.setAttribute("data-pptx-hidden", scope);
        sibling.style.setProperty("opacity", "0", "important");
        sibling.style.setProperty("visibility", "hidden", "important");
      }
    }
  });
  return scrolledTo;
}

/** Undo isolateInPage (the svg id rewrites stay, as before). Runs in the page. */
function restoreInPage(scope: string) {
  const doc = document;
  doc.querySelector(`style[data-pptx-style="${scope}"]`)?.remove();
  for (const attr of ["data-pptx-visible", "data-pptx-ancestor", "data-pptx-exclude-text"]) {
    doc.querySelectorAll(`[${attr}="${scope}"]`).forEach((el) => el.removeAttribute(attr));
  }
  doc.querySelectorAll(`[data-pptx-hidden="${scope}"]`).forEach((node) => {
    const el = node as HTMLElement;
    const opacity = el.getAttribute("data-pptx-prev-opacity");
    const opacityPriority = el.getAttribute("data-pptx-prev-opacity-priority") || undefined;
    if (opacity !== null) el.style.setProperty("opacity", opacity, opacityPriority);
    else el.style.removeProperty("opacity");
    const visibility = el.getAttribute("data-pptx-prev-visibility");
    const visibilityPriority = el.getAttribute("data-pptx-prev-visibility-priority") || undefined;
    if (visibility !== null) el.style.setProperty("visibility", visibility, visibilityPriority);
    else el.style.removeProperty("visibility");
    for (const attr of [
      "data-pptx-prev-opacity",
      "data-pptx-prev-opacity-priority",
      "data-pptx-prev-visibility",
      "data-pptx-prev-visibility-priority",
      "data-pptx-hidden",
    ])
      el.removeAttribute(attr);
  });
  doc.querySelector(`[data-pptx-scope="${scope}"]`)?.removeAttribute("data-pptx-scope");
}

/** Puppeteer's clip rounding, so pictures keep the size they had. */
function roundClip(r: Rect): Rect {
  const x = Math.round(r.x);
  const y = Math.round(r.y);
  return { x, y, width: Math.round(r.width + r.x - x), height: Math.round(r.height + r.y - y) };
}

function intersects(a: Rect, b: Rect) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** The part of a capture that lies on the slide (what the bundle cropped to). */
function onSlideCrop(target: Target, width: number, height: number) {
  const pos = target.position;
  if (!pos || typeof pos.width !== "number" || typeof pos.height !== "number") {
    return { left: 0, top: 0, width, height };
  }
  const left = typeof pos.left === "number" ? pos.left : 0;
  const top = typeof pos.top === "number" ? pos.top : 0;
  const w = Math.max(0, Math.round(pos.width));
  const h = Math.max(0, Math.round(pos.height));
  const cutLeft = left < 0 ? Math.min(w - 1, Math.max(0, Math.round(-left))) : 0;
  const cutTop = top < 0 ? Math.min(h - 1, Math.max(0, Math.round(-top))) : 0;
  const cutRight = Math.max(0, Math.round(left + w - SLIDE_WIDTH));
  const cutBottom = Math.max(0, Math.round(top + h - SLIDE_HEIGHT));
  if (cutLeft === 0 && cutTop === 0 && cutRight === 0 && cutBottom === 0) return { left: 0, top: 0, width, height };
  return {
    left: cutLeft,
    top: cutTop,
    width: Math.max(1, w - cutLeft - cutRight),
    height: Math.max(1, h - cutTop - cutBottom),
  };
}

async function crop(png: Buffer, area: { left: number; top: number; width: number; height: number }) {
  return sharp(png).extract(area).png({ compressionLevel: 1 }).toBuffer();
}

/**
 * Captures every element of the slide flagged shouldScreenshot and points its imageSrc at
 * a PNG data URI; one that cannot be captured is left out of the export (skipExport).
 */
export async function captureSlideTargets(page: Page, cdp: CDPSession, elements: Target[], slideIndex: number) {
  const targets = elements.filter((e) => e.shouldScreenshot);
  if (targets.length === 0) return;
  const { measured, related } = (await page.evaluate(measureInPage, {
    ids: targets.map((t) => t.identifier),
    bleed: BLEED,
  })) as { measured: Measured[]; related: [number, number][] };

  const usable: number[] = [];
  measured.forEach((m, i) => {
    if (m.clip) usable.push(i);
    else skip(targets[i], "not visible");
  });
  const clashes = new Set(related.map(([a, b]) => `${a}:${b}`));
  const batches: number[][] = [];
  for (const i of usable) {
    const clip = roundClip(measured[i].clip as Rect);
    const reach = measured[i].reach as Rect;
    const batch = batches.find((group) =>
      group.every((j) => {
        if (clashes.has(`${Math.min(i, j)}:${Math.max(i, j)}`)) return false;
        const other = roundClip(measured[j].clip as Rect);
        return !intersects(reach, other) && !intersects(measured[j].reach as Rect, clip);
      })
    );
    if (batch) batch.push(i);
    else batches.push([i]);
  }

  let scrollY = await page.evaluate(() => window.scrollY);
  for (const [n, batch] of batches.entries()) {
    const scope = `pptx_${slideIndex}_${n}`;
    const clips = batch.map((i) => roundClip(measured[i].clip as Rect));
    const x = Math.min(...clips.map((c) => c.x));
    const y = Math.min(...clips.map((c) => c.y));
    const right = Math.max(...clips.map((c) => c.x + c.width));
    const bottom = Math.max(...clips.map((c) => c.y + c.height));
    try {
      // Capturing inside the viewport is much cheaper than beyond it, so scroll there first.
      const viewportHeight = page.viewportSize()?.height ?? 0;
      const visible = () => y >= scrollY && bottom <= scrollY + viewportHeight;
      const scrollTop = !visible() && bottom - y <= viewportHeight ? Math.max(0, y - 8) : null;
      scrollY = await page.evaluate(isolateInPage, {
        scope,
        scrollTop,
        targets: batch.map((i) => ({
          id: targets[i].identifier,
          children: !!targets[i].includeChildrenInScreenshot,
          noText: !!targets[i].excludeTextInScreenshot,
        })),
      });
      const shot = await cdp.send("Page.captureScreenshot", {
        format: "png",
        clip: { x, y, width: right - x, height: bottom - y, scale: 1 },
        captureBeyondViewport: !visible(),
        fromSurface: true,
        optimizeForSpeed: true,
      });
      const png = Buffer.from(shot.data, "base64");
      await Promise.all(
        batch.map(async (i, k) => {
          const clip = clips[k];
          const area = onSlideCrop(targets[i], clip.width, clip.height);
          const image = await crop(png, {
            left: clip.x - x + area.left,
            top: clip.y - y + area.top,
            width: Math.min(area.width, clip.width - area.left),
            height: Math.min(area.height, clip.height - area.top),
          });
          targets[i].imageSrc = `data:image/png;base64,${image.toString("base64")}`;
        })
      );
    } catch (error) {
      for (const i of batch) skip(targets[i], error instanceof Error ? error.message : String(error));
    } finally {
      await page.evaluate(restoreInPage, scope).catch(() => {});
    }
  }
}

function skip(target: Target, reason: string) {
  console.warn(`[export] picture of ${target.tagName} ${target.identifier} left out: ${reason}`);
  target.skipExport = true;
  target.shouldScreenshot = false;
}
