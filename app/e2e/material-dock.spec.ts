import { test, expect } from "./fixtures";

test("Materials docks beside the canvas and restores filters and opener focus", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  const opener = page.getByRole("button", { name: "Materials", exact: true });
  await opener.click();
  const browser = page.getByRole("dialog", { name: "Materials", exact: true });
  await expect(browser).toBeVisible();
  expect(await browser.evaluate(node => node.matches(":modal"))).toBe(false);
  await expect(page.getByRole("region", { name: "Image viewer" })).toBeVisible();
  await expect(browser.getByRole("heading", { name: "Materials", exact: true })).toBeFocused();
  await browser.getByLabel("Subject or scene").fill("A remembered search");
  await browser.getByText("Search filters", { exact: true }).click();
  await browser.getByLabel("Pose / framing").fill("Facing left");
  await browser.getByRole("button", { name: "Close materials" }).click();
  await expect(opener).toBeFocused();
  await opener.click();
  await expect(browser.getByLabel("Subject or scene")).toHaveValue("A remembered search");
  await expect(browser.getByLabel("Pose / framing")).toHaveValue("Facing left");
  await page.setViewportSize({ width: 720, height: 700 });
  await expect.poll(() => browser.evaluate(node => node.matches(":modal"))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(browser).toBeHidden();
  await expect(opener).toBeFocused();
});
