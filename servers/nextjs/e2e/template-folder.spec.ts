import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

// A template folder dropped into <data>/templates/ (e2e/fixtures/templates/desk, copied in
// by e2e/stack.py) shows up in the picker, generates, renders in the editor with its own
// Tailwind classes (compiled locally by /api/template/css, no CDN) and exports. No rebuild.

test("a dropped-in template folder generates, renders and exports", async ({ page, request }) => {
  const listed = await (await request.get("/api/v1/ppt/template/all")).json();
  expect(listed.map((t: { id: string }) => t.id)).toContain("desk");

  await page.goto("/upload");
  await page.getByTestId("prompt-input").fill("Three slides on a trading desk's weekly review");
  await page.getByTestId("slides-select").click();
  const customCount = page.getByPlaceholder("--");
  await customCount.fill("3");
  await customCount.blur();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("slides-select")).toHaveText(/3 slides/);
  await page.getByRole("button", { name: "Get Started" }).click();

  await page.waitForURL("**/outline");
  await expect(page.getByRole("button", { name: "Select a Template" })).toBeVisible();
  const templateTab = page.getByRole("tab", { name: "Select Template" });
  await templateTab.click();
  await expect(templateTab).toHaveAttribute("aria-selected", "true");
  await page.locator("h3", { hasText: /^Desk$/ }).first().click();
  await page.getByRole("button", { name: /Generate Presentation/ }).click();

  await page.waitForURL(/\/presentation\?id=/);
  const id = new URL(page.url()).searchParams.get("id");
  const presentation = async () => (await request.get(`/api/v1/ppt/presentation/${id}`)).json();
  await expect.poll(async () => (await presentation()).slides?.length).toBe(3);
  const { slides } = await presentation();
  expect(slides.every((s: { layout_group: string }) => s.layout_group === "desk")).toBe(true);
  expect(slides.every((s: { layout: string }) => /^desk:desk-(title|points)$/.test(s.layout))).toBe(true);

  const slide = page.locator("#slide-0 [data-testid=desk-slide]");
  await expect(slide).toBeVisible();
  await expect(page.locator("#slide-0 [data-testid=desk-rule]")).toBeVisible(); // helper module
  await expect(slide).toHaveCSS("background-color", "rgb(11, 18, 32)"); // bg-[#0b1220]

  const exportButton = page.getByRole("button", { name: "Export" });
  await expect(exportButton).toBeEnabled();
  await exportButton.click();
  const downloading = page.waitForEvent("download", { timeout: 120_000 });
  await page.getByRole("button", { name: "PPTX", exact: true }).click();
  const pptx = readFileSync(await (await downloading).path());
  const slideXml = zipNames(pptx).filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  expect(slideXml).toHaveLength(3);
});

/** Entry names from a zip's central directory. */
function zipNames(zip: Buffer): string[] {
  const eocd = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = zip.readUInt16LE(eocd + 10);
  let at = zip.readUInt32LE(eocd + 16);
  const names: string[] = [];
  for (let i = 0; i < count; i++) {
    const nameLen = zip.readUInt16LE(at + 28);
    names.push(zip.toString("utf8", at + 46, at + 46 + nameLen));
    at += 46 + nameLen + zip.readUInt16LE(at + 30) + zip.readUInt16LE(at + 32);
  }
  return names;
}
