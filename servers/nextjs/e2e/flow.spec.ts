import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// The brief: a new user reaches an exported deck in three actions or fewer, mouse optional.
// Every user action goes through `act`, so the count is what a person does, not what we wait on.

test("prompt to an exported PPTX in three keyboard actions", async ({ page }) => {
  let actions = 0;
  const act = async (what: () => Promise<unknown>) => {
    actions += 1;
    await what();
  };

  await page.goto("/");
  await page.waitForURL("**/upload");
  await expect(page.getByTestId("prompt-input")).toBeFocused(); // no click needed to start typing

  await act(() => page.keyboard.type("Quarterly risk review for a macro fund"));
  await act(() => page.keyboard.press("ControlOrMeta+Enter")); // straight to the deck

  await page.waitForURL(/\/presentation\?id=/);
  await expect(page.getByRole("button", { name: "Export PPTX" })).toBeEnabled();

  const downloading = page.waitForEvent("download", { timeout: 120_000 });
  await act(() => page.keyboard.press("ControlOrMeta+e"));
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/\.pptx$/);
  expect(readFileSync(await download.path()).subarray(0, 2).toString()).toBe("PK");

  expect(actions).toBeLessThanOrEqual(3);
});

test("the editor works from the keyboard: J/K, E, Esc, ?", async ({ page }) => {
  await page.goto("/upload");
  await page.getByTestId("slides-select").selectOption("3");
  await page.getByTestId("prompt-input").fill("Three slides on rates volatility");
  await page.getByTestId("prompt-input").press("ControlOrMeta+Enter");
  await page.waitForURL(/\/presentation\?id=/);
  await expect(page.getByRole("button", { name: "Export PPTX" })).toBeEnabled();

  const selected = (page: Page) => page.locator("section.main-slide[aria-current=true]");
  await page.locator("body").press("j");
  await expect(selected(page)).toHaveAttribute("aria-label", "Slide 2");
  await page.keyboard.press("j");
  await page.keyboard.press("k");
  await expect(selected(page)).toHaveAttribute("aria-label", "Slide 2");

  const field = page.locator("#slide-1 [contenteditable=true]").first();
  await expect(field).toBeAttached(); // the slide's editors mount just after it renders
  await page.keyboard.press("e");
  await expect(field).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(field).not.toBeFocused();

  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
});
