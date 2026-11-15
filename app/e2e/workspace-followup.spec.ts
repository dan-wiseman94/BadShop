import path from "node:path";
import { test, expect, expectImageBytes } from "./fixtures";
import type { Session } from "../src/types";

test("the themed workspace transfers one layout draft and keeps the exact result through save and reopen", async ({ page, emptyCore }, info) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => localStorage.setItem("badshop.theme", "classic"));
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByRole("button", { name: /Two panels, one bad decision/ }).click();
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  const editor = page.getByRole("form", { name: "Edit this joke" });
  await expect(editor).toBeVisible();
  const original = await emptyCore.call("session.get") as Session;
  const image = original.steps[0].outputs[0];
  const saved = await emptyCore.call("artifacts.get", { id: image }) as { data: string };

  await editor.getByLabel("Headline").fill("Same draft in both modes");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const inspector = page.getByRole("region", { name: "Inspector", exact: true });
  await expect(inspector.getByLabel("Headline")).toHaveValue("Same draft in both modes");
  await expect(page.getByRole("dialog", { name: /Unsaved/ })).toHaveCount(0);
  await expect(editor).toHaveCount(1);
  await expectImageBytes(page.locator(".canvas-image"), saved.data);
  await inspector.getByRole("button", { name: "View preview on canvas" }).click();
  await expect(page.getByAltText("Draft preview on canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: "Share", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Return to saved image" }).click();
  await expectImageBytes(page.locator(".canvas-image"), saved.data);

  await inspector.getByLabel(/^Caption/).last().fill("The inspector can finish it.");
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(inspector).toBeVisible();
  await expect(page.getByRole("region", { name: "Image viewer" })).toBeVisible();
  await page.setViewportSize({ width: 840, height: 780 });
  await expect(inspector).toBeVisible();
  await expect(page.getByRole("region", { name: "Image viewer" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.getByRole("button", { name: "Quick ideas", exact: true }).click();
  await expect(editor.getByLabel(/^Caption/).last()).toHaveValue("The inspector can finish it.");
  expect((await emptyCore.call("session.get") as Session).document_revision).toBe(original.document_revision);
  await editor.getByRole("button", { name: "Apply changes", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0].params.title).toBe("Same draft in both modes");
  await page.getByRole("navigation", { name: "Workspace panels" }).getByRole("button", { name: "Canvas" }).click();
  const revised = (await emptyCore.call("session.get") as Session).steps[0];
  const result = await emptyCore.call("artifacts.get", { id: revised.outputs[0] }) as { data: string };
  expect(result.data).not.toBe(saved.data);
  await expectImageBytes(page.locator(".canvas-image"), result.data);
  await page.screenshot({ path: info.outputPath("classic-compact-canvas.png") });

  const filename = path.join(emptyCore.folder, "workspace-transfer.badshop");
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).unsaved_changes).toBe(false);
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await expectImageBytes(page.locator(".canvas-image"), result.data);
  expect((await emptyCore.call("session.get") as Session).steps[0].params).toEqual(revised.params);
});

test("a docked replacement keeps newer slot edits and a new tool cannot discard the draft", async ({ page, context, emptyCore }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const first = await emptyCore.call("artifacts.import", {
    path: path.resolve(import.meta.dirname, "../public/samples/pigeon.png"),
  }) as { working: { id: string } };
  const second = await emptyCore.call("artifacts.import", {
    path: path.resolve(import.meta.dirname, "../../core/tests/fixtures/lincoln.png"),
  }) as { working: { id: string } };
  await emptyCore.call("tools.run", { tool: "layout", params: {
    template: "comic", images: [first.working.id, first.working.id], captions: ["Before", "After"],
  } });
  const initial = await emptyCore.call("session.get") as Session;
  await page.setViewportSize({ width: 1440, height: 930 });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: /^Step 1 of 1: layout/ }).click();
  const editor = page.getByRole("region", { name: "Inspector", exact: true })
    .getByRole("form", { name: "Edit this joke" });
  await editor.getByLabel("Headline").fill("Kept across the dock");
  await editor.getByRole("button", { name: /^Find a replacement for/ }).first().click();
  const dock = page.getByRole("dialog", { name: "Replace picture in slot 1" });
  await dock.getByRole("button", { name: "Find images", exact: true }).click();
  const sourceCard = JSON.stringify({ badshop_source: 1, url: "https://example.invalid/replacement.png", title: "Fixture" });
  await page.evaluate(text => navigator.clipboard.writeText(text), sourceCard);
  const source = dock.getByLabel("Image URL or browser source card");
  await source.focus();
  await page.keyboard.press("Control+v");
  await expect(source).toHaveValue(sourceCard);
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(initial.steps);

  await dock.getByRole("button", { name: "In this project" }).click();
  await editor.getByLabel(/^Picture for/).last().selectOption(second.working.id);
  await dock.getByRole("article").filter({ hasText: "lincoln_work" })
    .getByRole("button", { name: "Replace picture in slot 1" }).click();
  await expect(dock).toBeHidden();
  await expect(editor.getByLabel(/^Picture for/).first()).toHaveValue(second.working.id);
  await expect(editor.getByLabel(/^Picture for/).last()).toHaveValue(second.working.id);
  await expect(editor.getByLabel("Headline")).toHaveValue("Kept across the dock");

  await page.getByRole("button", { name: "More tools" }).click();
  const palette = page.getByRole("dialog", { name: "Run a tool" });
  await palette.getByLabel("Search tools").fill("deepfry");
  await palette.getByRole("button", { name: /^deepfry / }).click();
  await palette.getByRole("button", { name: "Run tool", exact: true }).click();
  const warning = page.getByRole("dialog", { name: "Unsaved changes to this joke" });
  await warning.getByRole("button", { name: "Keep editing" }).click();
  await palette.getByRole("button", { name: "Close tools" }).click();
  await expect(editor.getByLabel("Headline")).toHaveValue("Kept across the dock");
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(initial.steps);
  await editor.getByRole("button", { name: "Apply changes", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0].params.images)
    .toEqual([second.working.id, second.working.id]);
});
