import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";

import { expect, test } from "@playwright/test";

// A template folder dropped into <data>/templates/ (e2e/fixtures/templates/desk, copied in
// by e2e/stack.py) shows up in the picker, generates, renders in the editor with its own
// Tailwind classes (compiled locally by /api/template/css, no CDN) and exports. No rebuild.
// The deck also picks up e2e/fixtures/themes/ink.json (the default theme in chatppt.toml)
// and e2e/fixtures/hooks.py.

test("a dropped-in template folder generates, renders and exports", async ({ page, request }) => {
  const listed = await (await request.get("/api/v1/ppt/template/all")).json();
  expect(listed.map((t: { id: string }) => t.id)).toContain("desk");

  await page.goto("/upload");
  // The template is picked with the prompt, so the outline call also picks each slide's layout.
  await page.getByTestId("template-select").selectOption("desk");
  await page.getByTestId("slides-select").selectOption("3");
  await page.getByTestId("prompt-input").fill("Three slides on a trading desk's weekly review");
  await page.getByTestId("prompt-input").press("Enter");

  await page.waitForURL("**/outline");
  await expect(page.getByTestId("generate-deck")).toBeEnabled();
  await page.getByTestId("generate-deck").click();

  await page.waitForURL(/\/presentation\?id=/);
  const id = new URL(page.url()).searchParams.get("id");
  const presentation = async () => (await request.get(`/api/v1/ppt/presentation/${id}`)).json();
  await expect.poll(async () => (await presentation()).slides?.length).toBe(3);
  const { slides, theme } = await presentation();
  expect(theme?.id).toBe("ink"); // <data>/themes/ink.json via defaults.theme in chatppt.toml
  expect(slides.every((s: { layout_group: string }) => s.layout_group === "desk")).toBe(true);
  expect(slides.every((s: { layout: string }) => /^desk:desk-(title|points)$/.test(s.layout))).toBe(true);
  // e2e/fixtures/hooks.py after_slide prefixes every title.
  expect(slides.every((s: { content: { title: string } }) => s.content.title.startsWith("Desk: "))).toBe(true);

  const slide = page.locator("#slide-0 [data-testid=desk-slide]");
  await expect(slide).toBeVisible();
  await expect(page.locator("#slide-0 [data-testid=desk-rule]")).toBeVisible(); // helper module
  await expect(slide).toHaveCSS("background-color", "rgb(11, 18, 32)"); // bg-[#0b1220]
  const wrapper = page.locator("#presentation-slides-wrapper");
  await expect
    .poll(() => wrapper.evaluate((el) => el.style.getPropertyValue("--background-color")))
    .toBe("#0a0a0a");

  const exportButton = page.getByRole("button", { name: "Export" });
  await expect(exportButton).toBeEnabled();
  await exportButton.click();
  const downloading = page.waitForEvent("download", { timeout: 120_000 });
  await page.getByRole("button", { name: "PPTX", exact: true }).click();
  const pptx = readFileSync(await (await downloading).path());
  const slideXml = zipEntries(pptx).filter(([name]) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  expect(slideXml).toHaveLength(3);
  // ... and before_export marks the titles in the export only.
  expect(slideXml.every(([, xml]) => xml.includes("[export]"))).toBe(true);
  expect((await presentation()).slides[0].content.title).not.toContain("[export]");
});

/** Read a zip's entries from its central directory (stored or deflated, as PPTX uses). */
function zipEntries(zip: Buffer): [string, string][] {
  const eocd = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = zip.readUInt16LE(eocd + 10);
  let at = zip.readUInt32LE(eocd + 16);
  const entries: [string, string][] = [];
  for (let i = 0; i < count; i++) {
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLen = zip.readUInt16LE(at + 28);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLen);
    const dataAt = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    const raw = zip.subarray(dataAt, dataAt + size);
    entries.push([name, (method === 8 ? inflateRawSync(raw) : raw).toString("utf8")]);
    at += 46 + nameLen + zip.readUInt16LE(at + 30) + zip.readUInt16LE(at + 32);
  }
  return entries;
}
