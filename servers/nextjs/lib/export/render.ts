/**
 * Renders a deck's /pdf-maker page in the warm Chromium and returns either the PPTX shape
 * models (for the writer in FastAPI) or the PDF bytes.
 *
 * Readiness is signalled, not guessed: the page marks itself loaded (data-export-state),
 * then fonts, images and the DOM have to settle (no spinners, no mutations for a short
 * quiet window, so chart animations have finished).
 */
import type { BrowserContext, Page } from "playwright-core";
import sharp from "sharp";

import { withExportContext } from "@/lib/export/browser";
import { walkSlidesInPage } from "@/lib/export/page-walk";
import { slidesToModels, type PptxSlideModel } from "@/lib/export/pptx-models";
import { captureSlideTargets } from "@/lib/export/screenshots";

export type ExportFormat = "pptx" | "pdf";
export type PptxPresentationModel = { name?: string; slides: PptxSlideModel[] };

const PAGE_TIMEOUT_MS = 120_000;
const QUIET_MS = 400;
const SETTLE_CAP_MS = 15_000;

function exportPageUrl(presentationId: string, cookieHeader?: string): string {
  const nextjsUrl = process.env.CHATPPT_NEXTJS_URL?.trim() || process.env.NEXT_PUBLIC_URL?.trim() || "http://127.0.0.1";
  const query = new URLSearchParams({ id: presentationId });
  const session = cookieHeader?.match(/(?:^|;\s*)(?:chatppt_session|presenton_session)=([^;]+)/)?.[1];
  if (session) query.set("exportSession", decodeURIComponent(session));
  const fastapiUrl = process.env.NEXT_PUBLIC_FAST_API?.trim();
  if (fastapiUrl) query.set("fastapiUrl", fastapiUrl);
  const url = `${nextjsUrl}/pdf-maker?${query.toString()}`;
  return cookieHeader?.trim() ? `${url}#exportCookie=${encodeURIComponent(cookieHeader)}` : url;
}

/** Waits in the page until fonts, images and the DOM are settled. Runs in the page. */
async function settleInPage(args: { quietMs: number; capMs: number }) {
  const { quietMs, capMs } = args;
  const deadline = Date.now() + capMs;
  const left = () => Math.max(0, deadline - Date.now());
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  const withCap = <T,>(promise: Promise<T>) => Promise.race([promise, sleep(left())]);

  let lastMutation = Date.now();
  const observer = new MutationObserver(() => {
    lastMutation = Date.now();
  });
  observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });

  const backgroundUrls = () => {
    const urls = new Set<string>();
    for (const el of Array.from(document.querySelectorAll("#presentation-slides-wrapper *"))) {
      const image = getComputedStyle(el).backgroundImage;
      if (!image || image === "none") continue;
      const pattern = /url\(("|'|)(.*?)\1\)/g;
      let match: RegExpExecArray | null;
      while ((match = pattern.exec(image)) !== null) if (match[2]) urls.add(match[2].trim());
    }
    return Array.from(urls);
  };
  const loadImages = async () => {
    const images = Array.from(document.images).map((img) =>
      img.complete && img.naturalWidth > 0
        ? Promise.resolve()
        : typeof img.decode === "function"
          ? img.decode().catch(() => {})
          : Promise.resolve()
    );
    const backgrounds = backgroundUrls().map(
      (src) =>
        new Promise<void>((resolve) => {
          const image = new Image();
          image.onload = () => resolve();
          image.onerror = () => resolve();
          image.src = src;
        })
    );
    await withCap(Promise.all([...images, ...backgrounds]));
  };
  const tailwindReady = () => {
    if (!document.querySelector('script[src*="tailwindcss.com"]')) return true;
    const probe = document.createElement("div");
    probe.className = "hidden";
    document.body.appendChild(probe);
    const hidden = getComputedStyle(probe).display === "none";
    probe.remove();
    return hidden;
  };
  const busy = () =>
    !!document.querySelector("#presentation-slides-wrapper .animate-spin") ||
    !tailwindReady() ||
    Array.from(document.images).some((img) => !img.complete);

  try {
    for (;;) {
      await loadImages();
      if (document.fonts) await withCap(document.fonts.ready);
      while (Date.now() - lastMutation < quietMs && left() > 0) await sleep(50);
      if (!busy() || left() === 0) return;
      await sleep(50);
    }
  } finally {
    observer.disconnect();
  }
}

async function openExportPage(context: BrowserContext, presentationId: string, cookieHeader?: string): Promise<Page> {
  const fastapiUrl = process.env.NEXT_PUBLIC_FAST_API?.trim();
  if (fastapiUrl) {
    await context.addInitScript((url: string) => {
      const w = window as unknown as { env?: Record<string, string> };
      w.env = { ...(w.env || {}), NEXT_PUBLIC_FAST_API: url };
    }, fastapiUrl);
  }
  const page = await context.newPage();
  page.setDefaultTimeout(PAGE_TIMEOUT_MS);
  await page.goto(exportPageUrl(presentationId, cookieHeader), { waitUntil: "load", timeout: PAGE_TIMEOUT_MS });

  const state = await page.waitForSelector('[data-export-state="ready"], [data-export-state="error"]', {
    state: "attached",
  });
  if (!state || (await state.getAttribute("data-export-state")) === "error") {
    throw new Error("The presentation could not be loaded for export.");
  }
  await page.evaluate(settleInPage, { quietMs: QUIET_MS, capMs: SETTLE_CAP_MS });
  return page;
}

/** SVG pictures as PNG at their own size (what the earlier converter did with sharp). */
async function rasterizeSvgPictures(context: BrowserContext, slides: PptxSlideModel[]) {
  const pictures = slides.flatMap((s) => s.shapes).filter((s) => s.shape_type === "picture");
  const isSvg = (src: string) => {
    if (src.startsWith("data:")) return src.startsWith("data:image/svg+xml");
    try {
      return new URL(src).pathname.toLowerCase().endsWith(".svg");
    } catch {
      return src.split(/[?#]/)[0].toLowerCase().endsWith(".svg");
    }
  };
  await Promise.all(
    pictures
      .filter((p) => p.picture?.path && isSvg(p.picture.path))
      .map(async (p) => {
        try {
          const src: string = p.picture.path;
          let svg: Buffer;
          if (src.startsWith("data:")) {
            const [header, payload] = src.split(",", 2);
            svg = header.endsWith(";base64") ? Buffer.from(payload, "base64") : Buffer.from(decodeURIComponent(payload));
          } else {
            const response = await context.request.get(src, { timeout: 30_000 });
            if (!response.ok()) throw new Error(`HTTP ${response.status()}`);
            svg = await response.body();
          }
          const png = await sharp(svg).png().toBuffer();
          p.picture = { is_network: false, path: `data:image/png;base64,${png.toString("base64")}` };
        } catch (error) {
          console.warn(`[export] svg picture left as is: ${error instanceof Error ? error.message : error}`);
        }
      })
  );
}

export async function renderPptxModel(params: {
  presentationId: string;
  title?: string;
  cookieHeader?: string;
}): Promise<PptxPresentationModel> {
  return withExportContext({ viewport: { width: 3000, height: 3000 }, cookieHeader: params.cookieHeader }, async (context) => {
    const started = Date.now();
    const page = await openExportPage(context, params.presentationId, params.cookieHeader);
    const loaded = Date.now();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
    const { slides, speakerNotes } = await page.evaluate(walkSlidesInPage);
    const walked = Date.now();
    for (const [index, slide] of slides.entries()) {
      await captureSlideTargets(page, cdp, slide.elements, index);
      slide.speakerNote = speakerNotes[index];
    }
    const models = slidesToModels(slides);
    await rasterizeSvgPictures(context, models);
    console.info(
      `[export] pptx ${slides.length} slides: page ${loaded - started} ms, walk ${walked - loaded} ms, pictures ${Date.now() - walked} ms`
    );
    return { name: params.title, slides: models };
  });
}

export async function renderPdf(params: { presentationId: string; cookieHeader?: string }): Promise<Buffer> {
  return withExportContext({ viewport: { width: 1280, height: 720 }, cookieHeader: params.cookieHeader }, async (context) => {
    const page = await openExportPage(context, params.presentationId, params.cookieHeader);
    return page.pdf({
      width: "1280px",
      height: "720px",
      printBackground: true,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
    });
  });
}
