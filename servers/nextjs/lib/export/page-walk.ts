/**
 * Runs inside the exporter's page (page.evaluate): one synchronous walk over every
 * slide that reads each element's box, text, fonts, colours, borders, shadows and image
 * source, and flags what has to be captured as a picture (svg, canvas, tables, gradients,
 * odd borders). It reproduces, element for element, what the earlier export bundle
 * gathered with one browser round trip per element.
 *
 * Self-contained on purpose: Playwright serialises the function, so it may not use
 * imports or anything outside its own body.
 */
export function walkSlidesInPage(): { slides: any[]; speakerNotes: string[] } {
  let nextId = 0;
  const colorCache = new Map<string, { hex?: string; opacity?: number }>();
  const fontNameCache = new Map<string, string>();
  let measureCanvas: CanvasRenderingContext2D | null | undefined;
  let colorCanvas: CanvasRenderingContext2D | null | undefined;
  const GENERIC_FAMILY =
    /^(system-ui|ui-sans-serif|ui-serif|ui-monospace|ui-rounded|sans-serif|serif|monospace|cursive|fantasy|emoji|math|fangsong)$/i;

  // ------------------------------------------------------------------ CSS readers

  function parseColor(input: string | null | undefined): { hex?: string; opacity?: number } {
    const value = (input || "").trim();
    if (!value) return { hex: undefined, opacity: undefined };
    const cached = colorCache.get(value);
    if (cached) return cached;
    const result = parseColorUncached(value);
    colorCache.set(value, result);
    return result;
  }

  function parseColorUncached(value: string): { hex?: string; opacity?: number } {
    const none = { hex: undefined, opacity: undefined };
    if (value.toLowerCase() === "transparent" || value === "rgba(0, 0, 0, 0)" || value === "rgba(0,0,0,0)") return none;
    const fromHex = (raw: string) => {
      const h = raw.trim().replace(/^#/, "");
      if (!/^[0-9a-fA-F]+$/.test(h)) return null;
      if (h.length === 3) return { hex: h.split("").map((c) => c + c).join(""), opacity: undefined };
      if (h.length === 4) {
        const full = h.split("").map((c) => c + c).join("");
        const alpha = parseInt(full.slice(6, 8), 16) / 255;
        return { hex: full.slice(0, 6), opacity: alpha < 1 ? Number(alpha.toFixed(4)) : undefined };
      }
      if (h.length === 6) return { hex: h, opacity: undefined };
      if (h.length === 8) {
        const alpha = parseInt(h.slice(6, 8), 16) / 255;
        return { hex: h.slice(0, 6), opacity: alpha < 1 ? Number(alpha.toFixed(4)) : undefined };
      }
      return null;
    };
    if (value.startsWith("#")) {
      const parsed = fromHex(value);
      if (parsed) return parsed;
    }
    const probe = document.createElement("span");
    probe.style.color = "";
    probe.style.color = value;
    if (!probe.style.color) return none;
    if (colorCanvas === undefined) {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      colorCanvas = canvas.getContext("2d", { willReadFrequently: true });
    }
    const ctx = colorCanvas;
    if (!ctx) return none;
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "rgba(0,0,0,0)";
    ctx.fillRect(0, 0, 1, 1);
    try {
      ctx.fillStyle = value;
    } catch {
      return none;
    }
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    if (a === 0) return none;
    const hex = [r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("");
    const alpha = a / 255;
    return { hex, opacity: alpha < 1 ? Number(alpha.toFixed(4)) : undefined };
  }

  function hasNoElementChildren(el: Element): boolean {
    const nodes = el.childNodes;
    for (let i = 0; i < nodes.length; i++) if (nodes[i].nodeType === Node.ELEMENT_NODE) return false;
    return true;
  }

  function box(el: Element) {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  function background(style: CSSStyleDeclaration) {
    const c = parseColor(style.backgroundColor);
    const result = { color: c.hex, opacity: c.opacity };
    if (!(!result.color && result.opacity === undefined)) return result;
    return undefined;
  }

  function backgroundImageUrl(style: CSSStyleDeclaration) {
    const value = style.backgroundImage;
    if (!value || value === "none") return undefined;
    const match = value.match(/url\(['"]?([^'"]+)['"]?\)/);
    if (match && match[1]) return match[1];
    return undefined;
  }

  function hasGradient(style: CSSStyleDeclaration) {
    const image = style.backgroundImage;
    const gradient =
      !!image &&
      image !== "none" &&
      /(linear-gradient|radial-gradient|conic-gradient|repeating-linear-gradient|repeating-radial-gradient)\s*\(/i.test(image);
    const clip = style.backgroundClip;
    const webkitClip = style.getPropertyValue ? style.getPropertyValue("-webkit-background-clip") : undefined;
    const clipText = (clip && clip.toLowerCase() === "text") || (webkitClip && webkitClip.toLowerCase() === "text");
    const color = (style.color || "").trim().toLowerCase();
    const fill = style.getPropertyValue ? (style.getPropertyValue("-webkit-text-fill-color") || "").trim().toLowerCase() : "";
    const transparent = (v: string) =>
      v === "transparent" || /rgba\s*\([^)]*,\s*0\s*\)/i.test(v) || /hsla\s*\([^)]*,\s*0\s*\)/i.test(v);
    const gradientText = clipText && (gradient || transparent(fill) || transparent(color));
    return gradient || gradientText;
  }

  function listMarker(el: Element, style: CSSStyleDeclaration) {
    try {
      if (el.tagName.toLowerCase() !== "li") return undefined;
      const display = (style.display || "").toLowerCase();
      const listStyle = (style.listStyleType || "").toLowerCase();
      let visible = display === "list-item" && listStyle !== "none";
      let color: string | undefined;
      try {
        const marker = window.getComputedStyle(el, "::marker");
        if (marker) {
          const content = (marker.content || "").trim();
          const markerList = ((marker as any).listStyleType || "").toLowerCase();
          if (content && content !== "none" && content !== "normal" && content !== '""') visible = true;
          if (markerList && markerList !== "none") visible = true;
          if (marker.color) color = parseColor(marker.color).hex;
        }
      } catch {}
      if (!visible) return undefined;
      const result: { color?: string } = {};
      if (color) result.color = color;
      return result;
    } catch {
      return undefined;
    }
  }

  function border(style: CSSStyleDeclaration) {
    const c = parseColor(style.borderColor);
    const width = (w: string, s: string) => {
      const n = parseFloat(w || "0");
      const st = (s || "").toLowerCase();
      return !isFinite(n) || n <= 0 || st === "none" || st === "hidden" ? 0 : n;
    };
    const top = width(style.borderTopWidth, style.borderTopStyle);
    const right = width(style.borderRightWidth, style.borderRightStyle);
    const bottom = width(style.borderBottomWidth, style.borderBottomStyle);
    const left = width(style.borderLeftWidth, style.borderLeftStyle);
    const sides: string[] = [];
    if (top > 0) sides.push("top");
    if (right > 0) sides.push("right");
    if (bottom > 0) sides.push("bottom");
    if (left > 0) sides.push("left");
    const max = Math.max(top, right, bottom, left);
    if (!isFinite(max) || max <= 0) return undefined;
    const result: any = { color: c.hex, width: max, opacity: c.opacity };
    if (sides.length > 0 && sides.length < 4) result.sides = sides;
    if (!(!result.color && result.width === undefined && result.opacity === undefined)) return result;
    return undefined;
  }

  function splitShadowTokens(part: string) {
    const tokens = part.split(" ");
    const numbers: number[] = [];
    const words: string[] = [];
    let inset = false;
    let color = "";
    let inColor = false;
    for (let i = 0; i < tokens.length; i++) {
      const t = tokens[i].trim();
      if (t === "") continue;
      if (t.toLowerCase() === "inset") {
        inset = true;
        continue;
      }
      if (t.match(/^(rgba?|hsla?)\s*\(/i)) {
        inColor = true;
        color = t;
        continue;
      }
      if (inColor) {
        color += " " + t;
        const open = (color.match(/\(/g) || []).length;
        const close = (color.match(/\)/g) || []).length;
        if (open <= close) {
          words.push(color);
          color = "";
          inColor = false;
        }
        continue;
      }
      const n = parseFloat(t);
      if (isNaN(n)) words.push(t);
      else numbers.push(n);
    }
    return { numbers, words, inset };
  }

  function shadow(style: CSSStyleDeclaration) {
    const value = style.boxShadow;
    let result: any = {};
    if (value && value !== "none") {
      const parts: string[] = [];
      let current = "";
      let depth = 0;
      for (let i = 0; i < value.length; i++) {
        const ch = value[i];
        if (ch === "(") depth++;
        else if (ch === ")") depth--;
        else if (ch === "," && depth === 0) {
          parts.push(current.trim());
          current = "";
          continue;
        }
        current += ch;
      }
      if (current.trim()) parts.push(current.trim());
      let best = "";
      let bestScore = -1;
      for (let i = 0; i < parts.length; i++) {
        const { numbers, words } = splitShadowTokens(parts[i]);
        let visibleColor = false;
        if (words.length > 0) {
          const c = parseColor(words.join(" "));
          visibleColor = !!(c.hex && c.hex !== "000000" && c.opacity !== 0);
        }
        const hasOffset = numbers.some((n) => n !== 0);
        let score = 0;
        if (hasOffset) score += numbers.filter((n) => n !== 0).length;
        if (visibleColor) score += 2;
        if ((hasOffset || visibleColor) && score > bestScore) {
          best = parts[i];
          bestScore = score;
        }
      }
      if (!best && parts.length > 0) best = parts[0];
      if (best) {
        const { numbers, words, inset } = splitShadowTokens(best);
        if (numbers.length >= 2) {
          const [x, y] = numbers;
          const blur = numbers.length >= 3 ? numbers[2] : 0;
          const spread = numbers.length >= 4 ? numbers[3] : 0;
          if (words.length > 0) {
            const c = parseColor(words.join(" "));
            if (c.hex) {
              result = {
                offset: [x, y],
                color: c.hex,
                opacity: c.opacity,
                radius: blur,
                spread,
                inset,
                angle: Math.atan2(y, x) * (180 / Math.PI),
              };
            }
          }
        }
      }
    }
    if (Object.keys(result).length !== 0) return result;
    return undefined;
  }

  function cleanFamilyName(family: string) {
    const names = (family || "").split(",").map((f) => f.trim().replace(/['"]/g, ""));
    const first = names[0] || "";
    const nextFont = first.match(/^__([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)_[A-Za-z0-9]+$/);
    if (nextFont) {
      return nextFont[1]
        .split(/[_-]+/)
        .filter((p) => p.length > 0)
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
        .join(" ");
    }
    if (/^__/.test(first)) {
      return (
        names.find((n) => !/^__/.test(n) && !/(^|\s)(fallback)$/i.test(n) && !GENERIC_FAMILY.test(n)) || first
      ).replace(/\s+Fallback$/i, "");
    }
    return first;
  }

  /** The first family in the stack the browser actually renders with (it measures). */
  function renderedFamily(style: CSSStyleDeclaration) {
    const key = `${style.fontStyle}|${style.fontWeight}|${style.fontSize}|${style.fontFamily}`;
    const cached = fontNameCache.get(key);
    if (cached !== undefined) return cached;
    const name = renderedFamilyUncached(style);
    fontNameCache.set(key, name);
    return name;
  }

  function renderedFamilyUncached(style: CSSStyleDeclaration) {
    try {
      if (measureCanvas === undefined) {
        const canvas = document.createElement("canvas");
        canvas.width = 600;
        canvas.height = 100;
        measureCanvas = canvas.getContext("2d");
      }
      const ctx = measureCanvas;
      if (!ctx) return cleanFamilyName(style.fontFamily || "");
      const sample = `mmmmmmmmmmlliWWWWW@#$%^&*()_+-=[]{}|;':",./<>? 1234567890`.repeat(3);
      const size = style.fontSize || "16px";
      const weight = style.fontWeight || "400";
      const fontStyle = style.fontStyle || "normal";
      const width = (family: string) => {
        ctx.font = `${fontStyle} ${weight} ${size} ${family}`;
        return ctx.measureText(sample).width;
      };
      const mono = width("monospace");
      const serif = width("serif");
      const sans = width("sans-serif");
      const families = (style.fontFamily || "")
        .split(",")
        .map((f) => f.trim())
        .filter((f) => f.length > 0);
      const generic = (f: string) =>
        /^("|')?(system-ui|ui-sans-serif|ui-serif|ui-monospace|ui-rounded|sans-serif|serif|monospace|cursive|fantasy|emoji|math|fangsong)("|')?$/i.test(
          f
        );
      for (const family of families) {
        const bare = family.replace(/^\s*["']|["']\s*$/g, "");
        if (generic(bare)) continue;
        if (
          width(`"${bare}", monospace`) !== mono ||
          width(`"${bare}", serif`) !== serif ||
          width(`"${bare}", sans-serif`) !== sans
        )
          return cleanFamilyName(bare);
      }
      if (families.some((f) => /^['"]?serif['"]?$/i.test(f))) return "serif";
      if (families.some((f) => /^['"]?monospace['"]?$/i.test(f))) return "monospace";
      return (families.find((f) => generic(f)) || "serif").replace(/^["']|["']$/g, "");
    } catch {
      return cleanFamilyName(style.fontFamily || "");
    }
  }

  function exportFontName(name: string) {
    const value = (name || "").trim();
    if (!value) return "Noto Sans";
    const lower = value.toLowerCase();
    if (lower === "serif") return "Noto Serif";
    if (lower === "monospace") return "Noto Sans Mono";
    if (lower === "emoji") return "Noto Color Emoji";
    if (
      [
        "sans-serif",
        "system-ui",
        "ui-sans-serif",
        "ui-monospace",
        "ui-serif",
        "ui-rounded",
        "cursive",
        "fantasy",
        "math",
        "fangsong",
      ].includes(lower)
    )
      return "Noto Sans";
    return value;
  }

  function font(style: CSSStyleDeclaration) {
    const size = parseFloat(style.fontSize);
    const weight = parseInt(style.fontWeight);
    const color = parseColor(style.color);
    const result = {
      name: exportFontName(renderedFamily(style)),
      size: isNaN(size) ? undefined : size,
      weight: isNaN(weight) ? undefined : weight,
      color: color.hex,
      italic: style.fontStyle === "italic",
    };
    if (!(!result.name && result.size === undefined && result.weight === undefined && !result.color && !result.italic))
      return result;
    return undefined;
  }

  function lineHeight(style: CSSStyleDeclaration) {
    const value = style.lineHeight;
    if (!value || value === "normal") return undefined;
    const text = String(value).trim();
    const fontSize = parseFloat(style.fontSize);
    let px: number | undefined;
    if (text.endsWith("px")) {
      const n = parseFloat(text);
      px = isNaN(n) ? undefined : n;
    } else if (text.endsWith("%")) {
      const n = parseFloat(text);
      px = isNaN(n) ? undefined : (n / 100) * fontSize;
    } else if (text.endsWith("em")) {
      const n = parseFloat(text);
      px = isNaN(n) ? undefined : n * fontSize;
    } else if (text.endsWith("rem")) {
      const n = parseFloat(text);
      try {
        const root = parseFloat(window.getComputedStyle(document.documentElement).fontSize);
        px = isNaN(n) || isNaN(root) ? undefined : n * root;
      } catch {
        px = isNaN(n) ? undefined : n * fontSize;
      }
    } else {
      const n = parseFloat(text);
      if (!isNaN(n)) px = n * fontSize;
    }
    return px !== undefined && isFinite(px) ? px : undefined;
  }

  function letterSpacing(style: CSSStyleDeclaration) {
    const value = style.letterSpacing;
    if (!value || value === "normal") return undefined;
    const n = parseFloat(value);
    return isNaN(n) ? undefined : n;
  }

  function textDecoration(style: CSSStyleDeclaration) {
    const value = style.textDecorationLine || style.textDecoration;
    if (!value) return undefined;
    const lower = String(value).toLowerCase();
    if (lower.includes("line-through")) return "line-through";
    if (lower.includes("underline")) return "underline";
    if (lower.includes("overline")) return "overline";
    return undefined;
  }

  function textTransform(style: CSSStyleDeclaration) {
    const value = (style.textTransform || "").toLowerCase();
    if (value === "uppercase" || value === "lowercase" || value === "capitalize") return value;
    return undefined;
  }

  function edges(top: string, bottom: string, left: string, right: string) {
    const t = parseFloat(top);
    const b = parseFloat(bottom);
    const l = parseFloat(left);
    const r = parseFloat(right);
    const result = {
      top: isNaN(t) ? undefined : t,
      bottom: isNaN(b) ? undefined : b,
      left: isNaN(l) ? undefined : l,
      right: isNaN(r) ? undefined : r,
    };
    if (result.top === 0 && result.bottom === 0 && result.left === 0 && result.right === 0) return undefined;
    return result;
  }

  function borderRadius(style: CSSStyleDeclaration, el: Element) {
    const value = style.borderRadius;
    let radii: number[] | undefined;
    if (value && value !== "0px") {
      const n = value.split(" ").map((v) => parseFloat(v));
      if (n.length === 1) radii = [n[0], n[0], n[0], n[0]];
      else if (n.length === 2) radii = [n[0], n[1], n[0], n[1]];
      else if (n.length === 3) radii = [n[0], n[1], n[2], n[1]];
      else if (n.length === 4) radii = n;
      if (radii) {
        const r = el.getBoundingClientRect();
        const max = Math.min(r.width, r.height) / 2;
        radii = radii.map((v) => Math.max(0, Math.min(v, max)));
      }
    }
    return radii;
  }

  function imageShape(el: Element, radii: number[] | undefined) {
    if (el.tagName.toLowerCase() === "img") {
      return radii && radii.length === 4 && radii.every((v) => v === 50) ? "circle" : "rectangle";
    }
    return undefined;
  }

  function filters(style: CSSStyleDeclaration) {
    const value = style.filter;
    if (!value || value === "none") return undefined;
    const result: Record<string, number> = {};
    const names: Record<string, string> = {
      invert: "invert",
      brightness: "brightness",
      contrast: "contrast",
      saturate: "saturate",
      "hue-rotate": "hueRotate",
      blur: "blur",
      grayscale: "grayscale",
      sepia: "sepia",
      opacity: "opacity",
    };
    const parts = value.match(/[a-zA-Z]+\([^)]*\)/g);
    if (parts) {
      parts.forEach((part) => {
        const m = part.match(/([a-zA-Z]+)\(([^)]*)\)/);
        if (!m) return;
        const n = parseFloat(m[2]);
        if (!isNaN(n) && names[m[1]]) result[names[m[1]]] = n;
      });
    }
    return Object.keys(result).length > 0 ? result : undefined;
  }

  function rotation(style: CSSStyleDeclaration) {
    const value = style.transform;
    if (!value || value === "none") return undefined;
    const normalize = (deg: number) => {
      let d = deg % 360;
      if (d < 0) d += 360;
      return Math.round(d);
    };
    const rotate = value.match(/rotate(?:Z)?\(([^)]+)\)/);
    if (rotate) {
      const arg = rotate[1].trim();
      if (arg.endsWith("deg")) {
        const n = parseFloat(arg.replace("deg", ""));
        if (!isNaN(n)) return normalize(n);
      } else if (arg.endsWith("rad")) {
        const n = parseFloat(arg.replace("rad", ""));
        if (!isNaN(n)) return normalize((n * 180) / Math.PI);
      } else if (arg.endsWith("turn")) {
        const n = parseFloat(arg.replace("turn", ""));
        if (!isNaN(n)) return normalize(n * 360);
      } else {
        const n = parseFloat(arg);
        if (!isNaN(n)) return normalize(n);
      }
    }
    const matrix = value.match(/matrix\(([^)]+)\)/);
    if (matrix) {
      const m = matrix[1].split(",").map((v) => parseFloat(v.trim()));
      if (m.length >= 2 && !m.some((v) => isNaN(v))) return normalize((Math.atan2(m[1], m[0]) * 180) / Math.PI);
    }
    const matrix3d = value.match(/matrix3d\(([^)]+)\)/);
    if (matrix3d) {
      const m = matrix3d[1].split(",").map((v) => parseFloat(v.trim()));
      if (m.length === 16 && !m.some((v) => isNaN(v))) return normalize((Math.atan2(m[1], m[0]) * 180) / Math.PI);
    }
    return undefined;
  }

  function alignment(style: CSSStyleDeclaration) {
    let textAlign = style.textAlign;
    const direction = style.direction || "ltr";
    if (textAlign === "start") textAlign = direction === "rtl" ? "right" : "left";
    else if (textAlign === "end") textAlign = direction === "rtl" ? "left" : "right";
    const display = style.display;
    const flexDirection = style.flexDirection;
    const alignItems = style.alignItems;
    const justifyContent = style.justifyContent;
    const justifyItems = style.justifyItems;
    const placeItems = (style as any).placeItems;
    const verticalAlign = style.verticalAlign;
    const horizontal = (v: string) => {
      if (!v) return undefined;
      if (v === "center") return "center";
      if (v === "flex-end" || v === "end" || v === "right") return "right";
      if (v === "flex-start" || v === "start" || v === "left") return "left";
      return undefined;
    };
    let fromLayout: string | undefined;
    if (display === "flex" || display === "inline-flex") {
      fromLayout = !!flexDirection && flexDirection.startsWith("column") ? horizontal(alignItems) : horizontal(justifyContent);
    } else if (display === "grid" || display === "inline-grid") {
      fromLayout = horizontal(justifyItems) || (placeItems === "center" ? "center" : undefined);
    } else if (placeItems === "center") {
      fromLayout = "center";
    }
    if (fromLayout) textAlign = fromLayout;
    let vertical: string | undefined;
    if (placeItems === "center") vertical = "middle";
    else if (display === "flex" || display === "inline-flex") {
      const axis = flexDirection && flexDirection.startsWith("column") ? justifyContent : alignItems;
      if (axis === "center") vertical = "middle";
      else if (axis === "flex-end" || axis === "end") vertical = "bottom";
      else if (axis === "flex-start" || axis === "start") vertical = "top";
    } else if (display === "grid" || display === "inline-grid") {
      if (alignItems === "center") vertical = "middle";
      else if (alignItems === "end") vertical = "bottom";
      else if (alignItems === "start") vertical = "top";
    }
    if (!vertical && verticalAlign) {
      const v = verticalAlign.toLowerCase();
      if (v === "middle") vertical = "middle";
      else if (v === "bottom" || v === "sub" || v === "text-bottom") vertical = "bottom";
      else if (v === "top" || v === "super" || v === "text-top") vertical = "top";
    }
    return { textAlign, textVerticalAlign: vertical };
  }

  /** Everything the converter needs about one element (and tag it for screenshots). */
  function attributes(el: Element): any {
    const identifier = `e${nextId++}`;
    try {
      el.setAttribute("data-pptx-element-identifier", identifier);
    } catch {}
    const tagName = el.tagName.toLowerCase();
    const passedAttributes: Record<string, string> = {};
    for (const attr of Array.from(el.attributes)) {
      if (attr.name.startsWith("data-") && attr.name !== "data-pptx-element-identifier") {
        passedAttributes[attr.name] = attr.value;
      }
    }
    const style = window.getComputedStyle(el);
    const position = box(el);
    const fontInfo = font(style);
    const lh = lineHeight(style);
    const ls = letterSpacing(style);
    const decoration = textDecoration(style);
    const transform = textTransform(style);
    const fullFont =
      fontInfo || lh !== undefined || ls !== undefined || decoration !== undefined || transform !== undefined
        ? { ...(fontInfo || {}), lineHeight: lh, letterSpacing: ls, textDecoration: decoration, textTransform: transform }
        : undefined;
    let innerText: string | undefined = (hasNoElementChildren(el) && el.textContent) || undefined;
    if (innerText) {
      innerText = innerText
        .replace(/^\n+|\n+$/g, "")
        .trim()
        .replace(/[ \t]+/g, " ")
        .replace(/<br\s*\/?>/gi, "\n");
      if (innerText.trim().length <= 0) innerText = undefined;
    }
    const z = parseInt(style.zIndex);
    const { textAlign, textVerticalAlign } = alignment(style);
    const radii = borderRadius(style, el);
    const opacity = parseFloat(style.opacity);
    const className = (el as any).className;
    return {
      tagName,
      path: [],
      id: el.id,
      className: className && typeof className == "string" ? className : className ? className.toString() : undefined,
      innerText,
      passedAttributes,
      opacity: isNaN(opacity) ? undefined : opacity,
      background: background(style),
      hasGradient: hasGradient(style),
      marker: listMarker(el, style),
      border: border(style),
      shadow: shadow(style),
      font: fullFont,
      position,
      margin: edges(style.marginTop, style.marginBottom, style.marginLeft, style.marginRight),
      padding: edges(style.paddingTop, style.paddingBottom, style.paddingLeft, style.paddingRight),
      zIndex: isNaN(z) ? undefined : z,
      textAlign: textAlign !== "left" ? textAlign : undefined,
      textVerticalAlign: textVerticalAlign && textVerticalAlign !== "top" ? textVerticalAlign : undefined,
      borderRadius: radii,
      rotation: rotation(style),
      imageSrc: (el as any).src || backgroundImageUrl(style),
      objectFit: style.objectFit,
      clip: false,
      overlay: undefined,
      shape: imageShape(el, radii),
      connectorType: undefined,
      textWrap: style.whiteSpace !== "nowrap",
      shouldScreenshot: false,
      identifier,
      filters: filters(style),
      clipPath: style.clipPath === "none" ? undefined : style.clipPath,
    };
  }

  // ------------------------------------------------------------------ the walk

  function cornerOutside(rect: any, radii: number[] | undefined, child: any) {
    const [tl = 0, tr = 0, br = 0, bl = 0] = radii || [];
    if (tl <= 0 && tr <= 0 && br <= 0 && bl <= 0) return false;
    const L = rect.left;
    const T = rect.top;
    const R = rect.left + rect.width;
    const B = rect.top + rect.height;
    const l = child.left;
    const t = child.top;
    const r = child.left + child.width;
    const b = child.top + child.height;
    const inTL = l < L + tl && t < T + tl && tl > 0;
    const inTR = r > R - tr && t < T + tr && tr > 0;
    const inBR = r > R - br && b > B - br && br > 0;
    const inBL = l < L + bl && b > B - bl && bl > 0;
    const outTL = inTL && (l - (L + tl)) ** 2 + (t - (T + tl)) ** 2 > tl * tl;
    const outTR = inTR && (r - (R - tr)) ** 2 + (t - (T + tr)) ** 2 > tr * tr;
    const outBR = inBR && (r - (R - br)) ** 2 + (b - (B - br)) ** 2 > br * br;
    const outBL = inBL && (l - (L + bl)) ** 2 + (b - (B - bl)) ** 2 > bl * bl;
    return outTL || outTR || outBR || outBL;
  }

  function cleanMarkup(html: string | undefined) {
    if (!html) return undefined;
    let text = html.replace(/^[\s​‌‍﻿]+|[\s​‌‍﻿]+$/g, "");
    if (!text) return undefined;
    text = text.replace(/<br\s*\/?>\s*/gi, "\n").replace(/\r\n?/g, "\n").replace(/\n[^\S\n]+/g, "\n");
    if (!text.trim()) return undefined;
    return text;
  }

  function isPrefix(a: number[], b: number[]) {
    if (a.length > b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  function isChildPath(parent: number[], child: number[]) {
    return child.length === parent.length + 1 && isPrefix(parent, child);
  }

  function truthyAttr(value: string | undefined) {
    if (value == null) return false;
    const v = String(value).trim().toLowerCase();
    if (v === "" || ["true", "1", "yes", "y", "on"].includes(v)) return true;
    return !["false", "0", "no", "n", "off"].includes(v);
  }

  function hasOwnText(el: Element) {
    for (const node of Array.from(el.childNodes)) {
      if (node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim().length > 0) return true;
    }
    return false;
  }

  const INLINE_FORMATTING = new Set(["strong", "u", "em", "code", "s", "b", "br"]);

  function walk(opts: {
    element: Element;
    rootRect?: any;
    depth?: number;
    inheritedPath?: number[];
    inheritedFont?: any;
    inheritedBackground?: any;
    inheritedRectangle?: any;
    inheritedBorderRadius?: number[];
    inheritedBorderRadiusRect?: any;
    inheritedZIndex?: number;
    inheritedOpacity?: number;
    inheritedRotation?: number;
    inheritedClipPath?: string;
    inheritedZPath?: number[];
  }): { elements: any[]; backgroundColor?: string } {
    const element = opts.element;
    let rootRect = opts.rootRect;
    const depth = opts.depth ?? 0;
    const inheritedPath = opts.inheritedPath;
    let inheritedFont = opts.inheritedFont;
    let inheritedBackground = opts.inheritedBackground;
    let inheritedRectangle = opts.inheritedRectangle;
    const inheritedBorderRadius = opts.inheritedBorderRadius;
    let inheritedBorderRadiusRect = opts.inheritedBorderRadiusRect;
    let inheritedZIndex = opts.inheritedZIndex;
    let inheritedOpacity = opts.inheritedOpacity;
    const inheritedRotation = opts.inheritedRotation;
    const inheritedClipPath = opts.inheritedClipPath;
    let inheritedZPath = opts.inheritedZPath;

    if (!rootRect) {
      const root = attributes(element);
      inheritedFont = root.font;
      inheritedBackground = root.background;
      rootRect = {
        left: root.position.left ?? 0,
        top: root.position.top ?? 0,
        width: root.position.width ?? 1280,
        height: root.position.height ?? 720,
      };
      inheritedBorderRadiusRect = root.borderRadius ? rootRect : undefined;
      inheritedZIndex = root.zIndex;
      inheritedOpacity = root.opacity;
      inheritedZPath = root.zIndex !== undefined ? [root.zIndex] : [];
      inheritedRectangle = rootRect;
    }

    const children = Array.from(element.children);
    const collected: any[] = [];
    for (let index = 0; index < children.length; index++) {
      const child = children[index];
      const el = attributes(child);
      el.depth = depth;
      el.index = index;
      el.path = Array.isArray(inheritedPath) ? [...inheritedPath, index] : [index];
      el.parentZIndex = inheritedZIndex;
      el.zPath = Array.isArray(inheritedZPath) ? [...inheritedZPath] : [];
      if (
        ["style", "script", "link", "meta", "path", "title"].includes(el.tagName) ||
        el.className?.includes("recharts-tooltip-wrapper")
      )
        continue;

      if (el.position.left === 0 && el.position.top === 0 && el.position.width === 0 && el.position.height === 0) {
        el.position = {
          left: inheritedRectangle.left,
          top: inheritedRectangle.top,
          width: inheritedRectangle.width,
          height: inheritedRectangle.height,
        };
      } else {
        el.position = {
          left: el.position.left - rootRect.left,
          top: el.position.top - rootRect.top,
          width: el.position.width,
          height: el.position.height,
        };
      }
      if (inheritedFont) {
        if (el.font) {
          if (!el.font.name || el.font.name.trim() === "" || el.font.name.trim().toLowerCase().startsWith("noto"))
            el.font.name = inheritedFont.name;
          el.font.color = el.font.color ?? inheritedFont.color;
          el.font.size = el.font.size ?? inheritedFont.size;
          el.font.weight = el.font.weight ?? inheritedFont.weight;
          el.font.italic = el.font.italic ?? inheritedFont.italic;
          el.font.lineHeight = el.font.lineHeight ?? inheritedFont.lineHeight;
          el.font.letterSpacing = el.font.letterSpacing ?? inheritedFont.letterSpacing;
          el.font.textDecoration = el.font.textDecoration ?? inheritedFont.textDecoration;
          el.font.textTransform = el.font.textTransform ?? inheritedFont.textTransform;
        } else {
          el.font = inheritedFont;
        }
      }
      if (inheritedBackground && !el.background && el.shadow) el.background = inheritedBackground;
      if (inheritedOpacity !== undefined && (el.opacity === undefined || el.opacity === 1)) el.opacity = inheritedOpacity;
      if (inheritedRotation !== undefined && !el.rotation) el.rotation = inheritedRotation;
      if (inheritedClipPath && !el.clipPath) el.clipPath = inheritedClipPath;
      if (
        inheritedBorderRadius &&
        !el.borderRadius &&
        cornerOutside(inheritedBorderRadiusRect || rootRect, inheritedBorderRadius, el.position)
      )
        el.borderRadius = inheritedBorderRadius;

      if (["p", "div", "span", "li"].includes(el.tagName) || /^h[1-6]$/.test(el.tagName)) {
        const tags = Array.from(child.querySelectorAll("*")).map((d) => d.tagName.toLowerCase());
        if (tags.length > 0 && tags.every((t) => INLINE_FORMATTING.has(t))) {
          el.innerText = cleanMarkup(child.innerHTML || "");
          collected.push(el);
          continue;
        }
      }
      el.hasImmediateUnwrappedText = hasOwnText(child);
      if (el.hasImmediateUnwrappedText) el.innerText = cleanMarkup(child.innerHTML || "");

      if (el.tagName === "svg" || el.tagName === "canvas") {
        el.shouldScreenshot = true;
        el.includeChildrenInScreenshot = true;
        collected.push(el);
        continue;
      }
      if (el.tagName === "table") {
        el.shouldScreenshot = true;
        el.includeChildrenInScreenshot = true;
        el.excludeTextInScreenshot = true;
      }
      if (
        (el.position.left < 0 ||
          el.position.top < 0 ||
          el.position.left + el.position.width > 1280 ||
          el.position.top + el.position.height > 720) &&
        (el.background?.color || el.border?.color)
      ) {
        el.shouldScreenshot = true;
        el.includeChildrenInScreenshot = true;
        el.excludeTextInScreenshot = true;
      }
      if ((el.clipPath && el.background?.color) || el.hasGradient) {
        el.shouldScreenshot = true;
        el.excludeTextInScreenshot = true;
      }
      if (el.border && el.border.sides) {
        el.shouldScreenshot = true;
        el.excludeTextInScreenshot = true;
      }
      if (
        el.borderRadius &&
        Array.isArray(el.borderRadius) &&
        el.borderRadius.length === 4 &&
        !el.imageSrc &&
        ((el.background && el.background.color) || (el.border && el.border.color))
      ) {
        const [a, b, c, d] = el.borderRadius;
        if (!(a === b && b === c && c === d)) {
          el.shouldScreenshot = true;
          el.excludeTextInScreenshot = true;
        }
      }
      const passed = el.passedAttributes ?? {};
      if (truthyAttr(passed["data-screenshot-include-children"])) {
        el.shouldScreenshot = true;
        el.includeChildrenInScreenshot = true;
      }
      if (truthyAttr(passed["data-screenshot-exclude-text"])) el.excludeTextInScreenshot = true;
      if (truthyAttr(passed["data-screenshot"])) el.shouldScreenshot = true;
      if (el.shouldScreenshot && !el.excludeTextInScreenshot) {
        collected.push(el);
        continue;
      }

      let descendants = walk({
        element: child,
        rootRect,
        depth: depth + 1,
        inheritedPath: Array.isArray(inheritedPath) ? [...inheritedPath, index] : [index],
        inheritedFont: el.font,
        inheritedRectangle: el.position,
        inheritedBackground: el.background || inheritedBackground,
        inheritedBorderRadius: el.borderRadius || inheritedBorderRadius,
        inheritedBorderRadiusRect:
          (el.position && {
            left: el.position.left ?? 0,
            top: el.position.top ?? 0,
            width: el.position.width ?? 0,
            height: el.position.height ?? 0,
          }) ||
          inheritedBorderRadiusRect,
        inheritedOpacity: el.opacity || inheritedOpacity,
        inheritedRotation: el.rotation || inheritedRotation,
        inheritedClipPath: el.clipPath || inheritedClipPath,
        inheritedZIndex: el.zIndex ?? inheritedZIndex,
        inheritedZPath: el.zIndex !== undefined ? [...(el.zPath || []), el.zIndex] : el.zPath || inheritedZPath,
      }).elements;

      if (el.shouldScreenshot && el.includeChildrenInScreenshot && el.excludeTextInScreenshot) {
        descendants = descendants.filter((d: any) => d.innerText && d.innerText.trim().length > 0);
        descendants.forEach((d: any) => {
          d.isExcludedTextChild = true;
        });
      }
      if (el.tagName === "ul" || el.tagName === "ol") {
        const listPath = el.path || [];
        const items = descendants.filter((d: any) => (d.tagName !== "li" || !d.path ? false : isChildPath(listPath, d.path)));
        const related: any[] = [];
        const consumed: number[][] = [];
        for (const item of items) {
          const itemPath = item.path || [];
          const texts = descendants
            .filter((d: any) => (!d.path || d === item ? false : isPrefix(itemPath, d.path)))
            .filter((d: any) => d.innerText && d.innerText.trim().length > 0)
            .sort((x: any, y: any) => {
              const tx = x.position?.top ?? Number.MAX_SAFE_INTEGER;
              const ty = y.position?.top ?? Number.MAX_SAFE_INTEGER;
              return tx !== ty ? tx - ty : (x.path?.length ?? 0) - (y.path?.length ?? 0);
            });
          const source = item.innerText && item.innerText.trim().length > 0 ? item : texts[0];
          if (!source) {
            consumed.push(itemPath);
            continue;
          }
          related.push({ ...source, marker: source.marker || item.marker });
          consumed.push(itemPath);
        }
        if (related.length > 0) {
          descendants = descendants.filter((d: any) => (d.path ? !consumed.some((p) => isPrefix(p, d.path)) : true));
          el.relatedElements = related;
        } else {
          const markers = descendants.filter((d: any) => d.tagName === "li" && !!d.marker);
          descendants = descendants.filter((d: any) => !(d.tagName === "li" && d.marker));
          el.relatedElements = markers;
        }
      }
      if (el.hasImmediateUnwrappedText) {
        el.relatedElements = descendants;
        descendants = [];
      }
      collected.push(el);
      collected.push(...descendants);
    }

    let backgroundColor = inheritedBackground?.color;
    if (depth === 0) {
      const fullSlide = collected.filter(
        (e) =>
          e.position &&
          e.position.left === 0 &&
          e.position.top === 0 &&
          e.position.width === rootRect.width &&
          e.position.height === rootRect.height
      );
      for (const e of fullSlide) if (e.background && e.background.color) backgroundColor = e.background.color;
    }
    const kept =
      depth === 0
        ? collected.filter((e) => {
            const visible =
              (e.background && e.background.color) ||
              (e.border && e.border.color) ||
              (e.shadow && e.shadow.color) ||
              (e.innerText && e.innerText.trim().length > 0);
            const media =
              e.imageSrc ||
              e.tagName === "svg" ||
              e.tagName === "canvas" ||
              e.tagName === "table" ||
              e.hasGradient ||
              (e.relatedElements && e.relatedElements.length > 0);
            return visible || media;
          })
        : collected;
    if (depth !== 0) return { elements: kept, backgroundColor };

    let sorted = kept.sort((a, b) => {
      const za = a.zPath || [];
      const zb = b.zPath || [];
      const n = Math.max(za.length, zb.length);
      for (let i = 0; i < n; i++) {
        const x = za[i] ?? 0;
        const y = zb[i] ?? 0;
        if (x !== y) return x - y;
      }
      const ia = typeof a.zIndex == "number" ? a.zIndex : 0;
      const ib = typeof b.zIndex == "number" ? b.zIndex : 0;
      if (ia !== ib) return ia - ib;
      const area = (a.position?.width ?? 0) * (a.position?.height ?? 0);
      const areb = (b.position?.width ?? 0) * (b.position?.height ?? 0);
      if (area !== areb) return areb - area;
      const pa = a.path || [];
      const pb = b.path || [];
      const m = Math.max(pa.length, pb.length);
      for (let i = 0; i < m; i++) {
        const x = pa[i] ?? -1;
        const y = pb[i] ?? -1;
        if (x !== y) return x - y;
      }
      return 0;
    });
    // Full-slide backgrounds at the bottom become the slide background instead.
    let skip = 0;
    for (const e of sorted) {
      const full =
        e.position &&
        e.position.left === 0 &&
        e.position.top === 0 &&
        e.position.width === rootRect.width &&
        e.position.height === rootRect.height;
      if (!full || e.imageSrc || e.shouldScreenshot) break;
      skip++;
    }
    sorted = sorted.slice(skip).map((e) => {
      if (e.shadow && e.shadow.color && (!e.background || !e.background.color) && backgroundColor)
        e.background = { color: backgroundColor, opacity: undefined };
      return e;
    });
    return { elements: sorted, backgroundColor };
  }

  const wrapper = document.querySelector("#presentation-slides-wrapper");
  if (!wrapper) throw new Error("Presentation slides not found");
  const slideRoots = Array.from(wrapper.querySelectorAll(":scope > div > div > div > div > div"));
  const speakerNotes = Array.from(wrapper.querySelectorAll("[data-speaker-note]")).map(
    (n) => n.getAttribute("data-speaker-note") || ""
  );
  return { slides: slideRoots.map((root) => walk({ element: root })), speakerNotes };
}
