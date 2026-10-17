/**
 * Turns the page walk's elements (lib/export/page-walk.ts) into the PPTX writer's shape
 * models (servers/fastapi/models/pptx_models.py): text boxes, auto shapes, pictures and
 * connectors in CSS pixels of a 1280x720 slide. It reproduces the earlier export bundle's
 * conversion rule for rule, so decks come out the same.
 */
import { Parser } from "htmlparser2";
import { decodeXML } from "entities";

type El = any;
type Shape = Record<string, any>;
type Run = { text: string; font?: Font };
type Font = {
  name: string;
  size: number;
  font_weight: number;
  italic: boolean;
  color: string;
  underline?: boolean;
  strike?: boolean;
};

export type SlideWalk = { elements: El[]; backgroundColor?: string; speakerNote?: string };
export type PptxSlideModel = { shapes: Shape[]; note?: string; background?: { color: string; opacity: number } };

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const DEFAULT_FONT: Font = { name: "Inter", size: 16, font_weight: 400, italic: false, color: "000000" };
const EDGE_SPACE = /^[\s​‌‍﻿]+|[\s​‌‍﻿]+$/g;

export function slidesToModels(slides: SlideWalk[]): PptxSlideModel[] {
  return slides.map((slide) => {
    const shapes: Shape[] = [];
    for (const element of slide.elements) shapes.push(...elementToShapes(element));
    const model: PptxSlideModel = { shapes, note: slide.speakerNote };
    if (slide.backgroundColor) model.background = { color: slide.backgroundColor, opacity: 1 };
    return model;
  });
}

function elementToShapes(el: El): Shape[] {
  if (el.skipExport || !el.position) return [];
  if (el.relatedElements && el.relatedElements.length > 0) return groupShapes(el);
  if (el.imageSrc) return pictureShapes(el);
  const painted = el.background?.color || el.border?.color;
  const rounded = el.borderRadius && el.borderRadius.some((r: number) => r > 0);
  if (el.innerText) return painted && rounded && !el.isExcludedTextChild ? boxShapes(el) : textShapes(el);
  return el.tagName === "hr" ? connectorShapes(el) : boxShapes(el);
}

// ------------------------------------------------------------------ small readers

function horizontalAlign(value: string | undefined): number | undefined {
  if (!value) return undefined;
  switch (value.toLowerCase()) {
    case "center":
      return 2;
    case "right":
      return 3;
    case "justify":
      return 4;
    default:
      return 1;
  }
}

function verticalAlign(value: string | undefined): number | undefined {
  if (!value) return undefined;
  switch (value.toLowerCase()) {
    case "top":
      return 1;
    case "middle":
      return 3;
    case "bottom":
      return 4;
    default:
      return undefined;
  }
}

function margin(el: El) {
  const p = el.padding;
  if (!p || !(p.top || p.bottom || p.left || p.right)) return undefined;
  return {
    top: Math.round(p.top ?? 0),
    bottom: Math.round(p.bottom ?? 0),
    left: Math.round(p.left ?? 0),
    right: Math.round(p.right ?? 0),
  };
}

function position(el: El) {
  return {
    left: el.position?.left ?? 0,
    top: el.position?.top ?? 0,
    width: el.position?.width ?? 0,
    height: el.position?.height ?? 0,
  };
}

function fill(el: El) {
  if (!el.background?.color) return undefined;
  return { color: el.background.color, opacity: Math.min(el.opacity ?? 1, el.background.opacity ?? 1) };
}

function stroke(el: El) {
  if (!el.border?.color) return undefined;
  return {
    color: el.border.color,
    thickness: el.border.width ?? 1,
    opacity: Math.min(el.opacity ?? 1, el.border.opacity ?? 1),
  };
}

function shadow(el: El) {
  if (!el.shadow?.color) return undefined;
  const offset = el.shadow.offset ? Math.sqrt(el.shadow.offset[0] ** 2 + el.shadow.offset[1] ** 2) : 0;
  return {
    radius: el.shadow.radius ?? 4,
    offset,
    color: el.shadow.color,
    opacity: Math.min(el.opacity ?? 0.5, el.shadow.opacity ?? 0.5),
    angle: el.shadow.angle ?? 0,
  };
}

function maxRadius(el: El): number | undefined {
  let radius: number | undefined;
  for (const r of el.borderRadius ?? []) if (r > 0) radius = Math.max(radius ?? 0, r);
  return radius;
}

function textTransformOf(el: El, parent?: El): string | undefined {
  return el?.font?.textTransform ?? parent?.font?.textTransform ?? undefined;
}

function transformText(transform: string | undefined, text: string): string {
  switch (transform) {
    case "uppercase":
      return text.toUpperCase();
    case "lowercase":
      return text.toLowerCase();
    case "capitalize":
      return text.replace(/\b\w/g, (c) => c.toUpperCase());
    default:
      return text;
  }
}

function applyTransform(el: El, text: string | undefined | null, parent?: El) {
  if (text == null) return text;
  return transformText(textTransformOf(el, parent), text);
}

function fontOf(el: El): Font | undefined {
  if (!el.font) return undefined;
  const decoration = el.font.textDecoration;
  return {
    name: el.font.name ?? "Inter",
    size: el.font.size ?? 16,
    font_weight: el.font.weight ?? 400,
    italic: el.font.italic ?? false,
    color: el.font.color ?? "000000",
    underline: decoration === "underline" ? true : undefined,
    strike: decoration === "line-through" ? true : undefined,
  };
}

function decode(text: string | undefined): string {
  return text ? decodeXML(text) : "";
}

// ------------------------------------------------------------------ inline markup → runs

function prepareMarkup(html: string): string {
  let text = html.replace(/\r\n?/g, "\n");
  text = text.replace(/>\s*\n\s*</g, "><");
  text = text.replace(/\n/g, "<br>");
  text = text.replace(/&nbsp;?/gi, " ");
  return text.replace(/&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)/g, "&amp;");
}

function runFont(base: Font | undefined, tags: string[]): Font {
  const font: Font = {
    name: base?.name ?? DEFAULT_FONT.name,
    size: base?.size ?? DEFAULT_FONT.size,
    font_weight: base?.font_weight ?? DEFAULT_FONT.font_weight,
    italic: base?.italic ?? DEFAULT_FONT.italic,
    color: base?.color ?? DEFAULT_FONT.color,
    underline: base?.underline,
    strike: base?.strike,
  };
  const has = (names: string[]) => names.some((name) => tags.includes(name.toLowerCase()));
  if (has(["strong", "b"])) font.font_weight = 700;
  if (has(["em", "i"])) font.italic = true;
  if (has(["u"])) font.underline = true;
  if (has(["s", "strike", "del"])) font.strike = true;
  if (has(["code"])) font.name = "Courier New";
  return font;
}

/** Text with <strong>/<em>/<u>/<s>/<code>/<br> as runs, each with its own font. */
function markupRuns(html: string | undefined, base: Font | undefined, transform: string | undefined): Run[] {
  if (!html) return [];
  const runs: Run[] = [];
  const open: string[] = [];
  const parser = new Parser(
    {
      onopentag(name) {
        const tag = name.toLowerCase();
        if (tag === "br") {
          runs.push({ text: "\n" });
          return;
        }
        open.push(tag);
      },
      onclosetag(name) {
        const tag = name.toLowerCase();
        for (let i = open.length - 1; i >= 0; i--) {
          if (open[i] === tag) {
            open.splice(i, 1);
            break;
          }
        }
      },
      ontext(chunk) {
        if (!chunk) return;
        const transformed = transformText(transform, chunk);
        if (!transformed) return;
        const text = decode(transformed);
        if (text) runs.push({ text, font: runFont(base, open) });
      },
    },
    { decodeEntities: true }
  );
  parser.write(prepareMarkup(html));
  parser.end();
  return runs.filter((run) => run.text.length > 0);
}

/** Only the text outside any child element, with top-level <br> as line breaks. */
function ownText(html: string): string {
  if (!html) return "";
  let depth = 0;
  let text = "";
  const parser = new Parser(
    {
      onopentag(name) {
        if (name.toLowerCase() === "br" && depth === 0) {
          text += "\n";
          return;
        }
        depth += 1;
      },
      onclosetag() {
        depth = Math.max(0, depth - 1);
      },
      ontext(chunk) {
        if (depth === 0 && chunk) text += chunk;
      },
    },
    { decodeEntities: true }
  );
  parser.write(html);
  parser.end();
  return decode(text).trim();
}

function paragraph(el: El) {
  const font = fontOf(el);
  const transform = textTransformOf(el);
  const parsed = el.innerText && el.innerText.length > 0 ? markupRuns(el.innerText, font, transform) : undefined;
  const runs = parsed && parsed.length > 0 ? parsed : undefined;
  const text = runs && runs.length > 0 ? runs.map((r) => r.text).join("") : applyTransform(el, el.innerText);
  return {
    alignment: horizontalAlign(el.textAlign),
    font,
    line_height: el.font?.lineHeight,
    letter_spacing: el.font?.letterSpacing,
    text,
    text_runs: runs,
  };
}

// ------------------------------------------------------------------ elements with children

const INLINE_TAGS = new Set([
  "a",
  "abbr",
  "b",
  "br",
  "code",
  "em",
  "i",
  "img",
  "mark",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "time",
  "u",
  "wbr",
]);

function directChildren(el: El): El[] {
  if (!el.relatedElements || el.relatedElements.length === 0) return [];
  const parent: number[] = el.path || [];
  return el.relatedElements
    .filter((child: El) => {
      const p: number[] = child.path || [];
      if (p.length !== parent.length + 1) return false;
      for (let i = 0; i < parent.length; i++) if (p[i] !== parent[i]) return false;
      return true;
    })
    .sort((a: El, b: El) => (a.path[a.path.length - 1] || 0) - (b.path[b.path.length - 1] || 0));
}

function isStrictPrefix(a: number[], b: number[]) {
  if (a.length >= b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function deepest(elements: El[]): El[] {
  const placed = elements.filter((e) => e.path && e.position);
  if (placed.length === 0) return [];
  return placed.filter((e) => !placed.some((other) => other !== e && isStrictPrefix(e.path, other.path)));
}

/** Where the element's own text goes when its children are drawn as separate shapes. */
function ownTextBox(el: El, children: El[]) {
  if (!el.position) return null;
  const padLeft = el.padding?.left ?? 0;
  const padRight = el.padding?.right ?? 0;
  const padTop = el.padding?.top ?? 0;
  const padBottom = el.padding?.bottom ?? 0;
  const size = el.font?.size ?? 16;
  const lineHeight = el.font?.lineHeight ?? Math.round(size * 1.2);
  const left = el.position.left + padLeft;
  const width = Math.max(1, el.position.width - padLeft - padRight);
  let top = el.position.top + padTop;
  if (children.length > 0) {
    const placed = children
      .filter((c) => c.position)
      .sort((a, b) => (a.position.top ?? 0) - (b.position.top ?? 0));
    if (placed.length > 0) {
      const gaps: number[] = [];
      for (let i = 0; i < placed.length - 1; i++) {
        const current = placed[i].position;
        const gap = placed[i + 1].position.top - (current.top + current.height);
        if (gap >= 0) gaps.push(gap);
      }
      const gap = gaps.length > 0 ? Math.round(gaps.reduce((s, g) => s + g, 0) / gaps.length) : 0;
      const last = placed[placed.length - 1].position;
      top = last.top + last.height + gap;
    }
  }
  const lowest = el.position.top + el.position.height - padBottom - lineHeight;
  if (top > lowest) top = Math.max(el.position.top + padTop, lowest);
  return { left, top, width, height: lineHeight };
}

function fillWidthWithSpaces(width: number, fontSize: number, letterSpacing: number) {
  const spaces: [number, string][] = [
    [1, " "],
    [0.5, " "],
    [1 / 3, " "],
    [0.25, " "],
    [1 / 6, " "],
    [0.2, " "],
    [1 / 12, " "],
  ];
  let left = Math.max(0, width);
  let text = "";
  for (const [em, char] of spaces) {
    const advance = em * fontSize + letterSpacing;
    if (advance <= 0) continue;
    const count = Math.floor(left / advance);
    if (count > 0) {
      text += char.repeat(count);
      left -= count * advance;
    }
  }
  return text || " ";
}

/** Mixed text and inline children (<span>, <img>, ...) as paragraphs of runs; painted
 * children become their own shapes with a gap of spaces left in the text. */
function inlineRuns(el: El): { paragraphRuns: Run[][]; extraShapes: Shape[] } | null {
  if (!el.hasImmediateUnwrappedText || !el.relatedElements || el.relatedElements.length === 0 || !el.innerText)
    return null;
  const children = directChildren(el);
  if (children.length === 0) return null;
  const BREAK = "PPTX_BR";
  let html: string = el.innerText;
  html = html
    .replace(/(\r?\n)[^\S\r\n]+(?=<)/g, "$1")
    .replace(/>\s+(?=<)/g, "><")
    .replace(/\r?\n(?=\s*<)/g, "");
  html = html.replace(/<br\s*\/?>/gi, BREAK);
  const tokens: string[] = [];
  const tokenChildren: El[] = [];
  const kinds: ("run" | "shape")[] = [];
  const painted = (c: El) =>
    !!c.background?.color ||
    !!(c.border?.color && (c.border?.width ?? 0) > 0) ||
    !!c.imageSrc ||
    !!(c.hasGradient || c.shape || c.shouldScreenshot);
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if ((child.tagName || "").toLowerCase() === "br") continue;
    const childText = (child.innerText ?? "").replace(/<[^>]+>/g, "");
    const asShape = painted(child) || childText.length === 0;
    const token = `PPTX_RUN_${i}`;
    if (!asShape && childText) {
      const at = html.indexOf(childText);
      if (at !== -1) {
        html = html.slice(0, at) + token + html.slice(at + childText.length);
        tokens.push(token);
        tokenChildren.push(child);
        kinds.push("run");
        continue;
      }
    }
    let placed = false;
    if (childText) {
      const at = html.indexOf(childText);
      if (at !== -1) {
        html = html.slice(0, at) + token + html.slice(at + childText.length);
        placed = true;
      }
    }
    if (!placed) {
      const tag = (child.tagName || "span").toLowerCase();
      try {
        const empty = new RegExp(`<${tag}[^>]*></${tag}>`, "i");
        if (empty.test(html)) {
          html = html.replace(empty, token);
          placed = true;
        }
      } catch {}
    }
    if (!placed) html = token + html;
    tokens.push(token);
    tokenChildren.push(child);
    kinds.push("shape");
  }
  const flat = html.replace(/<[^>]+>/g, "").replace(EDGE_SPACE, "");
  type Piece = { text?: string; child?: El; kind?: "run" | "shape"; hardBreak?: boolean };
  const pieces: Piece[] = [];
  if (tokens.length === 0) pieces.push({ text: flat });
  else {
    let at = 0;
    while (at < flat.length) {
      let next = -1;
      let found: string | undefined;
      for (const token of tokens) {
        const i = flat.indexOf(token, at);
        if (i !== -1 && (next === -1 || i < next)) {
          next = i;
          found = token;
        }
      }
      if (next === -1 || !found) {
        const rest = flat.slice(at);
        if (rest) pieces.push({ text: rest });
        break;
      }
      if (next > at) pieces.push({ text: flat.slice(at, next) });
      const index = tokens.indexOf(found);
      if (index !== -1) pieces.push({ child: tokenChildren[index], kind: kinds[index] });
      at = next + found.length;
    }
  }
  const split: Piece[] = [];
  for (const piece of pieces) {
    if (piece.text && piece.text.includes(BREAK)) {
      const parts = piece.text.split(BREAK);
      parts.forEach((part, i) => {
        if (part) split.push({ text: part });
        if (i < parts.length - 1) split.push({ hardBreak: true });
      });
    } else split.push(piece);
  }
  const paragraphs: Run[][] = [];
  let current: Run[] = [];
  const extraShapes: Shape[] = [];
  const flush = (force = false) => {
    if (!force && current.length === 0) return;
    paragraphs.push(current);
    current = [];
  };
  for (const piece of split) {
    if (piece.hardBreak) {
      flush(true);
      continue;
    }
    if (piece.child) {
      if (piece.kind === "run") {
        const text = decode((piece.child.innerText || "").replace(/<[^>]+>/g, "").replace(EDGE_SPACE, ""));
        if (text) {
          const transformed = applyTransform(piece.child, text, el);
          if (transformed) current.push({ text: transformed, font: fontOf(piece.child) });
        }
      } else {
        const size = el.font?.size ?? piece.child.font?.size ?? 16;
        const spacing = el.font?.letterSpacing ?? 0;
        current.push({ text: fillWidthWithSpaces(piece.child.position?.width ?? 0, size, spacing) });
        const shapes = elementToShapes(piece.child) || [];
        if (shapes.length > 0) extraShapes.push(...shapes);
      }
    } else if (piece.text && piece.text.length > 0) {
      const transformed = applyTransform(el, decode(piece.text));
      if (transformed) current.push({ text: transformed });
    }
  }
  if (current.length > 0 || paragraphs.length === 0) flush(true);
  return { paragraphRuns: paragraphs, extraShapes };
}

function joinParagraphs(paragraphs: Run[][]): Run[] {
  if (paragraphs.length <= 1) return paragraphs[0] ? [...paragraphs[0]] : [];
  const runs: Run[] = [];
  paragraphs.forEach((p, i) => {
    runs.push(...p);
    if (i < paragraphs.length - 1) runs.push({ text: "\n" });
  });
  return runs;
}

type Frame = {
  position: ReturnType<typeof position>;
  wrap: boolean;
  margin: ReturnType<typeof margin>;
  fill: ReturnType<typeof fill>;
  stroke: ReturnType<typeof stroke>;
  shadow: ReturnType<typeof shadow>;
  rotation: number | undefined;
  vertical: number | undefined;
};

function groupShapes(el: El): Shape[] {
  const shapes: Shape[] = [];
  if (el.imageSrc) shapes.push(...pictureShapes(el));
  const frame: Frame = {
    position: position(el),
    margin: margin(el),
    fill: fill(el),
    stroke: stroke(el),
    shadow: shadow(el),
    rotation: el.rotation,
    wrap: el.textWrap ?? true,
    vertical: verticalAlign(el.textVerticalAlign),
  };
  const radius = maxRadius(el);
  const painted = el.background?.color || el.border?.color;
  const roundedBackdrop = !!(radius && painted);
  if (roundedBackdrop) {
    shapes.push({
      shape_type: "autoshape",
      type: 5,
      position: frame.position,
      margin: frame.margin,
      fill: frame.fill,
      stroke: frame.stroke,
      shadow: frame.shadow,
      rotation: frame.rotation,
      border_radius: radius,
    });
  }
  const children = directChildren(el);
  const allInline = el.hasImmediateUnwrappedText && children.length > 0 && children.every((c) => INLINE_TAGS.has((c.tagName || "").toLowerCase()));
  if (el.hasImmediateUnwrappedText && allInline) shapes.push(...inlineTextBox(el, roundedBackdrop, frame));
  else if (el.hasImmediateUnwrappedText && children.length > 0) {
    const leaves = el.relatedElements ? deepest(el.relatedElements) : [];
    for (const child of leaves.length > 0 ? leaves : children) {
      const childShapes = elementToShapes(child);
      if (childShapes) shapes.push(...childShapes);
    }
    const text = applyTransform(el, ownText(el.innerText ?? ""));
    if (text && text.trim().length > 0) {
      const box = ownTextBox(el, children);
      shapes.push(...textShapes({ ...el, innerText: text, position: box ?? el.position, textVerticalAlign: "top" }, true));
    }
  } else shapes.push(...listTextBox(el, roundedBackdrop, frame));
  return shapes;
}

function inlineTextBox(el: El, roundedBackdrop: boolean, frame: Frame): Shape[] {
  const box = { left: frame.position.left, top: frame.position.top, width: frame.position.width + 2, height: frame.position.height };
  const inline = inlineRuns(el);
  const base = paragraph(el);
  const paragraphs: any[] = [];
  let extra: Shape[] = [];
  if (inline) {
    extra = inline.extraShapes;
    const groups = inline.paragraphRuns.length > 0 ? inline.paragraphRuns : [[]];
    for (const runs of groups) paragraphs.push({ ...base, text: undefined, text_runs: runs.length > 0 ? runs : undefined });
  } else paragraphs.push(base);
  return [
    {
      shape_type: "textbox",
      position: box,
      margin: frame.margin,
      fill: roundedBackdrop ? undefined : frame.fill,
      stroke: roundedBackdrop ? undefined : frame.stroke,
      shadow: roundedBackdrop ? undefined : frame.shadow,
      rotation: frame.rotation,
      text_wrap: frame.wrap,
      vertical_alignment: frame.vertical,
      paragraphs,
    },
    ...extra,
  ];
}

/** A list (or any element with related text children) as one text box, a paragraph each. */
function listTextBox(el: El, roundedBackdrop: boolean, frame: Frame): Shape[] {
  const indent = el.font?.size ?? el.relatedElements[0].font?.size ?? 16;
  const box = { left: frame.position.left - indent, top: frame.position.top, width: frame.position.width + indent, height: frame.position.height };
  const items: El[] = el.relatedElements;
  const gaps: number[] = [];
  for (let i = 0; i < items.length - 1; i++) {
    const current = position(items[i]);
    const gap = position(items[i + 1]).top - current.top - current.height;
    if (gap >= 0) gaps.push(gap);
  }
  const spacing = gaps.length > 0 ? Math.floor(gaps.reduce((s, g) => s + g, 0) / gaps.length) : undefined;
  const paragraphs: any[] = [];
  const extra: Shape[] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const after = i < items.length - 1 ? spacing : undefined;
    const inline = inlineRuns(item);
    let runs: Run[] | undefined;
    if (inline) {
      if (inline.extraShapes.length > 0) extra.push(...inline.extraShapes);
      runs = joinParagraphs(inline.paragraphRuns);
    } else if (item.innerText) {
      const parsed = markupRuns(item.innerText, fontOf(item), textTransformOf(item, el));
      runs = parsed.length > 0 ? parsed : undefined;
    }
    const text = runs && runs.length > 0 ? runs.map((r) => r.text).join("") : (applyTransform(item, item.innerText ?? "", el) ?? "");
    paragraphs.push({
      spacing: { top: 0, bottom: after ?? 0, left: 0, right: 0 },
      alignment: horizontalAlign(item.textAlign),
      font: fontOf(item),
      line_height: item.font?.lineHeight,
      level: 0,
      bullet: item.marker ? (item.marker.color ? { type: "default", color: item.marker.color } : { type: "default" }) : undefined,
      letter_spacing: item.font?.letterSpacing,
      text,
      text_runs: runs,
    });
  }
  return [
    {
      shape_type: "textbox",
      position: box,
      margin: frame.margin,
      fill: roundedBackdrop ? undefined : frame.fill,
      stroke: roundedBackdrop ? undefined : frame.stroke,
      shadow: roundedBackdrop ? undefined : frame.shadow,
      rotation: frame.rotation,
      text_wrap: frame.wrap,
      vertical_alignment: frame.vertical,
      paragraphs,
    },
    ...extra,
  ];
}

// ------------------------------------------------------------------ leaf elements

function textShapes(el: El, bare = false): Shape[] {
  const styled = !(bare || el.isExcludedTextChild);
  const box = position(el);
  box.width += 2;
  return [
    {
      shape_type: "textbox",
      margin: margin(el),
      fill: styled ? fill(el) : undefined,
      stroke: styled ? stroke(el) : undefined,
      shadow: styled ? shadow(el) : undefined,
      position: box,
      rotation: el.rotation,
      text_wrap: el.textWrap ?? true,
      vertical_alignment: verticalAlign(el.textVerticalAlign),
      paragraphs: [paragraph(el)],
    },
  ];
}

function boxShapes(el: El): Shape[] {
  const box = position(el);
  const textBox = { left: box.left, top: box.top, width: box.width + 2, height: box.height };
  const paragraphs = el.innerText ? [paragraph(el)] : undefined;
  const type = el.borderRadius ? 5 : 1;
  const radius = maxRadius(el);
  if (radius) {
    const shapes: Shape[] = [
      {
        shape_type: "autoshape",
        type,
        margin: margin(el),
        fill: fill(el),
        stroke: stroke(el),
        shadow: shadow(el),
        position: box,
        rotation: el.rotation,
        border_radius: radius,
      },
    ];
    if (paragraphs) {
      shapes.push({
        shape_type: "textbox",
        position: textBox,
        margin: margin(el),
        rotation: el.rotation,
        text_wrap: el.textWrap ?? true,
        vertical_alignment: verticalAlign(el.textVerticalAlign),
        paragraphs,
      });
    }
    return shapes;
  }
  return [
    {
      shape_type: "autoshape",
      type,
      margin: margin(el),
      fill: fill(el),
      stroke: stroke(el),
      shadow: shadow(el),
      position: box,
      rotation: el.rotation,
      text_wrap: el.textWrap ?? true,
      border_radius: radius || undefined,
      paragraphs,
    },
  ];
}

function pictureShapes(el: El): Shape[] {
  let left = el.position?.left ?? 0;
  let top = el.position?.top ?? 0;
  let width = Math.max(0, el.position?.width ?? 0);
  let height = Math.max(0, el.position?.height ?? 0);
  if (left < 0) {
    width = Math.max(1, width + left);
    left = 0;
  }
  if (top < 0) {
    height = Math.max(1, height + top);
    top = 0;
  }
  if (left + width > SLIDE_WIDTH) width = Math.max(1, SLIDE_WIDTH - left);
  if (top + height > SLIDE_HEIGHT) height = Math.max(1, SLIDE_HEIGHT - top);
  const src: string = el.imageSrc || "";
  const shapes: Shape[] = [
    {
      shape_type: "picture",
      position: { left, top, width, height },
      margin: undefined,
      rotation: el.rotation,
      clip: el.clip ?? true,
      invert: el.filters?.invert === 1,
      opacity: el.shouldScreenshot ? undefined : el.opacity,
      border_radius: el.shouldScreenshot ? undefined : el.borderRadius,
      shape: el.shape ? el.shape : "rectangle",
      object_fit: { fit: el.objectFit ? el.objectFit : "contain" },
      picture: { is_network: src.startsWith("http"), path: src },
    },
  ];
  if (el.innerText && el.shouldScreenshot && el.excludeTextInScreenshot) shapes.push(...textShapes(el, true));
  return shapes;
}

function connectorShapes(el: El): Shape[] {
  return [
    {
      shape_type: "connector",
      type: 1,
      position: position(el),
      rotation: el.rotation,
      thickness: el.border?.width ?? 0.5,
      color: el.border?.color || el.background?.color || "000000",
      opacity: el.border?.opacity ?? 1,
    },
  ];
}
