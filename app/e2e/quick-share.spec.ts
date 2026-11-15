import { createHash } from "node:crypto";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { test, expect, expectImageBytes, root } from "./fixtures";
import type { Session } from "../src/types";

test("a new user makes, revises, copies and exports a credited shitpost without a provider or network", async ({ page, context, emptyCore }, info) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await emptyCore.call("settings.set", { values: { no_remote: true } });
  const external: string[] = [];
  let branchRequest: number | undefined;
  let releaseBranch = () => {};
  let branchHeld = false;
  await page.routeWebSocket(`ws://127.0.0.1:${emptyCore.port}/`, client => {
    const server = client.connectToServer();
    client.onMessage(frame => {
      const message = JSON.parse(String(frame));
      if (message.method === "branches.create") branchRequest = message.id;
      server.send(frame);
    });
    server.onMessage(frame => {
      if (typeof frame !== "string") { client.send(frame); return; }
      const message = JSON.parse(String(frame));
      if (branchRequest !== undefined && message.id === branchRequest) {
        branchHeld = true;
        releaseBranch = () => client.send(frame);
      } else client.send(frame);
    });
  });
  page.on("request", request => { if (!/^https?:\/\/127\.0\.0\.1/.test(request.url()) && !request.url().startsWith("data:") && !request.url().startsWith("blob:")) external.push(request.url()); });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeHidden();
  await page.getByRole("button", { name: /An error with no solution/ }).click();
  await page.getByLabel("Punchline", { exact: true }).fill("My last brain cell has left the meeting.");
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect(page.locator(".canvas-image")).toBeVisible();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  await expect(page.getByRole("button", { name: "Apply changes", exact: true })).toBeVisible();
  let session = await emptyCore.call("session.get") as Session;
  expect(session.steps).toHaveLength(1);
  const initial = session.steps[0];
  const originalImage = initial.params.images;
  expect(session.provider_profile_id).toBeNull();
  await page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/).fill("Brain cell unavailable. Please hold.");
  await page.getByRole("button", { name: "Apply changes", exact: true }).click();
  await expect.poll(async () => {
    const step = (await emptyCore.call("session.get") as Session).steps[0];
    return step.status === "done" && (step.params.captions as string[] | undefined)?.[0] === "Brain cell unavailable. Please hold."
      && !!step.outputs[0] && step.outputs[0] !== initial.outputs[0];
  }).toBe(true);
  session = await emptyCore.call("session.get") as Session;
  const revised = session.steps[0];
  expect(revised.params.images).toEqual(originalImage);
  expect(revised.params.template).toBe(initial.params.template);
  expect(revised.params.title).toBe(initial.params.title);
  expect(revised.params.captions).toEqual(["Brain cell unavailable. Please hold."]);
  const artifact = await emptyCore.call("artifacts.get", { id: revised.outputs[0] }) as { data: string; mime: string };
  await expectImageBytes(page.locator(".canvas-image"), artifact.data);
  await page.getByRole("button", { name: "Copy image", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Image copied");
  const clipboard = await page.evaluate(async () => {
    const item = (await navigator.clipboard.read())[0];
    const bitmap = await createImageBitmap(await item.getType("image/png"));
    const canvas = document.createElement("canvas"); canvas.width = bitmap.width; canvas.height = bitmap.height;
    const context = canvas.getContext("2d")!; context.drawImage(bitmap, 0, 0); bitmap.close();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const digest = await crypto.subtle.digest("SHA-256", pixels);
    return { width: canvas.width, height: canvas.height, hash: Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, "0")).join("") };
  });
  const displayed = await page.locator(".canvas-image").evaluate(async node => {
    const image = node as HTMLImageElement; const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d")!; context.drawImage(image, 0, 0);
    const digest = await crypto.subtle.digest("SHA-256", context.getImageData(0, 0, canvas.width, canvas.height).data);
    return { width: canvas.width, height: canvas.height, hash: Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, "0")).join("") };
  });
  expect(clipboard).toEqual(displayed);
  await page.screenshot({ path: info.outputPath("quick-idea.png") });
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Export image", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Share selected image" })).toContainText("920 × 620");
  await page.getByRole("button", { name: "Save image" }).click();
  await expect(page.getByRole("status")).toContainText("Exported to ");
  const filename = (await page.getByRole("status").innerText()).replace("Exported to ", "").trim();
  const bytes = await readFile(filename);
  const exportedState = await emptyCore.call("session.get") as Session;
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(exportedState.artifacts[revised.outputs[0]].blob_id);
  const credits = JSON.parse(await readFile(filename + ".credits.json", "utf8"));
  expect(credits.sources).toContainEqual(expect.objectContaining({ license: "CC0-1.0", title: "Geometric pigeon" }));
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Export image", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Duplicate take" }).click();
  await expect.poll(() => branchHeld).toBe(true);
  await expect(page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/)).toBeDisabled();
  releaseBranch();
  await expect(page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/)).toBeEnabled();
  await expect(page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/)).toHaveValue("Brain cell unavailable. Please hold.");
  await page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/).fill("This pigeon has administrator privileges.");
  await page.getByRole("button", { name: "Apply changes", exact: true }).click();
  await expect.poll(async () => {
    const step = (await emptyCore.call("session.get") as Session).steps[0];
    return step.status === "done" && (step.params.captions as string[] | undefined)?.[0] === "This pigeon has administrator privileges."
      && !!step.outputs[0] && step.outputs[0] !== revised.outputs[0];
  }).toBe(true);
  await page.getByRole("button", { name: "Versions", exact: true }).click();
  const versions = page.getByRole("dialog", { name: "Versions" });
  await versions.getByRole("article").filter({ has: page.getByText("Original", { exact: true }) })
    .getByRole("button", { name: "Open take", exact: true }).click();
  await versions.getByRole("button", { name: /Close/ }).click();
  await expect(page.getByRole("form", { name: "Edit this joke" }).getByLabel(/^Caption/)).toHaveValue("Brain cell unavailable. Please hold.");
  expect((await emptyCore.call("session.get") as Session).steps[0].outputs[0]).toBe(revised.outputs[0]);
  expect(external).toEqual([]);
});

test("quick ideas and export remain usable at 200 percent text with keyboard focus", async ({ page, emptyCore }, info) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.addInitScript(() => {
    localStorage.setItem("badshop.textScale", "200");
    localStorage.setItem("badshop.theme", "light");
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByRole("button", { name: /An error with no solution/ }).click();
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect(page.locator(".canvas-image")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("navigation", { name: "Workspace panels" }).getByRole("button", { name: "Ideas" }).click();
  await page.getByRole("button", { name: "Share", exact: true }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Export image", exact: true });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.getByRole("button", { name: "Save image" }).scrollIntoViewIfNeeded();
  const bounds = await page.getByRole("button", { name: "Save image" }).boundingBox();
  expect(bounds!.height).toBeGreaterThanOrEqual(24);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(600);
  await page.screenshot({ path: info.outputPath("quick-share-200-percent.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Share", exact: true })).toBeFocused();
  // Wrapped pane headings must keep their controls above the scrolling cards.
  await page.evaluate(() => { document.documentElement.dataset.theme = "terminal"; });
  await page.getByRole("navigation", { name: "Workspace panels" }).getByRole("button", { name: "Ideas" }).click();
  await page.getByRole("button", { name: /^all tools$/i }).click();
  await expect(page.getByRole("button", { name: "Run tool", exact: true })).toBeVisible();
});

test("a two-panel Quick idea keeps every edit and the exact result across undo and reopen", async ({ page, emptyCore }) => {
  const snapshot = async () => await emptyCore.call("session.get") as Session;
  const { working: replacement } = await emptyCore.call("artifacts.import", {
    path: path.join(root, "core/tests/fixtures/lincoln.png"),
  }) as { working: { id: string } };
  await emptyCore.call("library.save", { artifact_id: replacement.id, name: "Panel replacement" });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByRole("button", { name: /Two panels, one bad decision/ }).click();
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  const editor = page.getByRole("form", { name: "Edit this joke" });
  await expect(editor).toBeVisible();
  const before = await snapshot();
  const previous = before.steps[0];
  await editor.getByLabel("Headline").fill("It seemed like a good idea");
  await editor.getByLabel(/^Caption/).first().fill("First line\nSecond line");
  await editor.getByLabel(/^Caption/).last().fill("");
  await editor.getByRole("button", { name: /^Find a replacement for/ }).last().click();
  const browser = page.getByRole("dialog", { name: "Replace picture in slot 2" });
  await browser.getByRole("button", { name: "Junk drawer", exact: true }).click();
  await browser.getByRole("article").filter({ hasText: "Panel replacement" })
    .getByRole("button", { name: "Replace picture in slot 2", exact: true }).click();
  await expect(browser).toBeHidden();
  await expect(editor.getByLabel("Headline")).toHaveValue("It seemed like a good idea");
  const assigned = await editor.getByLabel(/^Picture for/).last().inputValue();
  expect(assigned).not.toBe(replacement.id);
  const imported = (await snapshot()).artifacts[assigned];
  expect(imported.produced_by).toBeNull();
  expect(imported.blob_id).toBe(before.artifacts[replacement.id].blob_id);
  const preview = editor.getByAltText("Uncommitted joke preview");
  await expect(preview).toBeVisible();
  const previewBytes = (await preview.getAttribute("src"))!.split(",")[1];
  expect((await snapshot()).steps[0]).toEqual(previous);
  await editor.getByRole("button", { name: "Apply changes", exact: true }).click();
  await expect.poll(async () => (await snapshot()).steps[0].params.title).toBe("It seemed like a good idea");
  const revised = (await snapshot()).steps[0];
  expect(revised.params.captions).toEqual(["First line\nSecond line", ""]);
  expect(revised.params.images).toEqual([(previous.params.images as string[])[0], assigned]);
  expect(revised.outputs[0]).not.toBe(previous.outputs[0]);
  const pixels = await emptyCore.call("artifacts.get", { id: revised.outputs[0] }) as { data: string };
  expect(pixels.data).toBe(previewBytes);
  await expectImageBytes(page.locator(".canvas-image"), pixels.data);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect.poll(async () => (await snapshot()).steps[0]).toEqual(previous);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect.poll(async () => (await snapshot()).steps[0]).toEqual(revised);
  const filename = path.join(emptyCore.folder, "two-panel.badshop");
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: "Save session", exact: true }).click();
  await expect.poll(async () => (await snapshot()).unsaved_changes).toBe(false);
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await expect(editor.getByLabel("Headline")).toHaveValue("It seemed like a good idea");
  await expect.poll(async () => (await snapshot()).steps[0]).toEqual(revised);
  await expectImageBytes(page.locator(".canvas-image"), pixels.data);
});
