import { test, expect } from "./fixtures";
import path from "node:path";
import type { Session } from "../src/types";

test("saved assets survive project reopen", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Materials", exact: true })
    .click();
  await page.getByRole("button", { name: "Junk drawer", exact: true }).click();
  await page.getByLabel("Save selected image as").fill("Lincoln head source");
  await page
    .getByLabel("Tags, separated by commas")
    .fill("portrait, president");
  await page.getByRole("button", { name: "Save to junk drawer" }).click();
  await expect(
    page.locator(".studio-card").getByText("Lincoln head source", { exact: true }),
  ).toBeVisible();
  const file = path.join(core.folder, "directions.badshop");
  await core.call("session.save_as", { path: file });
  await core.call("session.open", { path: file });
  await page.reload();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Materials", exact: true })
    .click();
  await page.getByRole("button", { name: "Junk drawer", exact: true }).click();
  const before = await core.call("session.get") as Session;
  await page.getByRole("button", { name: "Add to Materials", exact: true }).click();
  await expect.poll(async () => Object.keys((await core.call("session.get") as Session).artifacts).length)
    .toBeGreaterThan(Object.keys(before.artifacts).length);
  await page.getByRole("button", { name: "Close materials" }).click();
  await expect(page.getByRole("status")).toContainText("Picture added to Materials");
  await expect(page.locator(".composer .attachments img")).toHaveCount(0);
  await page.getByText("Direction options", { exact: true }).click();
  await expect(page.getByLabel("Creative style")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("badshop-studio.png") });
});

test("discovery controls and header fit the minimum desktop window", async ({
  page,
  core,
}) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const exportBox = await page
    .getByRole("button", { name: "Share", exact: true })
    .boundingBox();
  expect(exportBox!.x + exportBox!.width).toBeLessThanOrEqual(900);
  await page
    .getByRole("button", { name: "Materials", exact: true })
    .click();
  await expect(page.getByLabel("Subject or scene")).toBeVisible();
  await expect(page.getByRole("button", { name: "Find candidates" })).toBeInViewport();
  await page.getByText("Search filters", { exact: true }).click();
  await expect(page.getByLabel("Pose / framing")).toBeVisible();
  await page.getByLabel(/^Collection/).selectOption("met");
  await expect(page.getByLabel(/^Collection/)).toHaveValue("met");
  expect(
    await page
      .locator(".studio")
      .evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await page.screenshot({ path: test.info().outputPath("badshop-discovery.png") });
});
