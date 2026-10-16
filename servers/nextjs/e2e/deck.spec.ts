import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";

import { expect, test } from "@playwright/test";

// The whole product in one test: prompt -> outline -> deck -> edit -> PPTX.
// Runs against the mock LLM and mock image provider (e2e/stack.py), so it needs no keys.

const EDIT = "Edited by the e2e test";

test("prompt to a 4-slide deck, edit a field, export PPTX", async ({ page, request }) => {
  await page.goto("/");
  await page.waitForURL("**/upload");

  await page.getByTestId("prompt-input").fill("Four slides about solar power for a city council");
  await page.getByTestId("slides-select").click();
  const customCount = page.getByPlaceholder("--");
  await customCount.fill("4");
  await customCount.blur();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("slides-select")).toHaveText(/4 slides/);
  await page.getByRole("button", { name: "Get Started" }).click();

  await page.waitForURL("**/outline");
  await expect(page.getByText("Slide 4", { exact: true })).toBeVisible();
  // The outline page ignores tab switches until the stream ends ("Loading..." -> "Select a Template").
  await expect(page.getByRole("button", { name: "Select a Template" })).toBeVisible();
  const templateTab = page.getByRole("tab", { name: "Select Template" });
  await templateTab.click();
  await expect(templateTab).toHaveAttribute("aria-selected", "true");
  await page.locator("h3", { hasText: /^general$/i }).first().click();
  await page.getByRole("button", { name: /Generate Presentation/ }).click();

  await page.waitForURL(/\/presentation\?id=/);
  const id = new URL(page.url()).searchParams.get("id");
  expect(id).toBeTruthy();
  await expect
    .poll(async () => (await (await request.get(`/api/v1/ppt/presentation/${id}`)).json()).slides?.length)
    .toBe(4);
  const exportButton = page.getByRole("button", { name: "Export" });
  await expect(exportButton).toBeEnabled();

  const field = page.locator("#slide-0 [contenteditable=true]").first();
  await field.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type(EDIT);
  await page.locator("#slide-0").click({ position: { x: 5, y: 5 } }); // blur commits the edit
  await expect(field).toHaveText(EDIT);

  await exportButton.click();
  const downloading = page.waitForEvent("download", { timeout: 120_000 });
  await page.getByRole("button", { name: "PPTX", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/\.pptx$/);

  const pptx = readFileSync(await download.path());
  expect(pptx.subarray(0, 2).toString()).toBe("PK");
  const slides = zipEntries(pptx).filter(([name]) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  expect(slides).toHaveLength(4);
  expect(slides.some(([, xml]) => xml.includes(EDIT))).toBe(true);
});

/** Read a zip's entries from its central directory (stored or deflated only, which is what PPTX uses). */
function zipEntries(zip: Buffer): [string, string][] {
  const eocd = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = zip.readUInt16LE(eocd + 10);
  let at = zip.readUInt32LE(eocd + 16);
  const entries: [string, string][] = [];
  for (let i = 0; i < count; i++) {
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLen = zip.readUInt16LE(at + 28);
    const extraLen = zip.readUInt16LE(at + 30);
    const commentLen = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLen);
    const dataAt = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    const raw = zip.subarray(dataAt, dataAt + size);
    entries.push([name, (method === 8 ? inflateRawSync(raw) : raw).toString("utf8")]);
    at += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}
