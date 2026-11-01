import { test, expect } from "./fixtures";
import type { Session } from "../src/types";
import path from "node:path";

test("saved assets and independent branches survive project reopen", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await page.getByRole("button", { name: "Junk drawer", exact: true }).click();
  await page.getByLabel("Save selected image as").fill("Lincoln head source");
  await page
    .getByLabel("Tags, separated by commas")
    .fill("portrait, president");
  await page.getByRole("button", { name: "Save to junk drawer" }).click();
  await expect(
    page.getByText("Lincoln head source", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Branches", exact: true }).click();
  await page.getByLabel("New branch name").fill("Fried version");
  await page.getByRole("button", { name: "Create & switch" }).click();
  await expect(page.getByText("Fried version (current)")).toBeVisible();
  const session = (await core.call("session.get")) as Session;
  await core.call("tools.run", {
    tool: "deepfry",
    params: { image: Object.keys(session.artifacts)[0], seed: 7, level: 1 },
  });
  await page
    .getByRole("button", { name: "Switch to this take" })
    .first()
    .click();
  await expect(page.getByText("Original (current)")).toBeVisible();
  expect(((await core.call("session.get")) as Session).steps).toHaveLength(0);
  const file = path.join(core.folder, "directions.badshop");
  await core.call("session.save_as", { path: file });
  await core.call("session.open", { path: file });
  await page.reload();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await page.getByRole("button", { name: "Branches", exact: true }).click();
  await page
    .getByRole("button", { name: "Switch to this take" })
    .last()
    .click();
  await expect(page.getByText("Fried version (current)")).toBeVisible();
  expect(((await core.call("session.get")) as Session).steps[0].tool).toBe(
    "deepfry",
  );
  await page.getByRole("button", { name: "Junk drawer", exact: true }).click();
  await page.getByRole("button", { name: "Use image", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("attached to chat");
  await page
    .getByRole("button", { name: "Close images and directions" })
    .click();
  await expect(page.getByLabel("Creative style")).toBeVisible();
  await page.screenshot({ path: "/tmp/badshop-studio.png" });
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
    .getByRole("button", { name: "Export", exact: true })
    .boundingBox();
  expect(exportBox!.x + exportBox!.width).toBeLessThanOrEqual(900);
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await expect(page.getByLabel("Subject or scene")).toBeVisible();
  await expect(page.getByLabel("Pose / framing")).toBeVisible();
  await page.getByLabel("Collection").selectOption("met");
  await expect(page.getByLabel("Collection")).toHaveValue("met");
  expect(
    await page
      .locator(".studio")
      .evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/badshop-discovery.png" });
});
