import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test, expect } from "./fixtures";
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
      const message = JSON.parse(String(frame));
      if (branchRequest !== undefined && message.id === branchRequest) {
        branchHeld = true;
        releaseBranch = () => client.send(frame);
      } else client.send(frame);
    });
  });
  page.on("request", request => { if (!/^https?:\/\/127\.0\.0\.1/.test(request.url()) && !request.url().startsWith("data:")) external.push(request.url()); });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeHidden();
  await page.getByRole("button", { name: /An error with no solution/ }).click();
  await page.getByLabel("Punchline", { exact: true }).fill("My last brain cell has left the meeting.");
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect(page.locator(".canvas-image")).toBeVisible();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  await expect(page.getByRole("button", { name: "Change caption only" })).toBeEnabled();
  let session = await emptyCore.call("session.get") as Session;
  expect(session.steps).toHaveLength(1);
  const initial = session.steps[0];
  const originalImage = initial.params.images;
  expect(session.provider_profile_id).toBeNull();
  await page.getByLabel("Revised punchline").fill("Brain cell unavailable. Please hold.");
  await page.getByRole("button", { name: "Change caption only" }).click();
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
  await expect(page.locator(".canvas-image")).toHaveAttribute("src", `data:${artifact.mime};base64,${artifact.data}`);
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
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Export image", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Share selected image" })).toContainText("920 × 620");
  await page.getByRole("button", { name: "Save image file" }).click();
  await expect(page.getByRole("status")).toContainText("Exported to ");
  const filename = (await page.getByRole("status").innerText()).replace("Exported to ", "").trim();
  const bytes = await readFile(filename);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(revised.outputs[0]);
  const credits = JSON.parse(await readFile(filename + ".credits.json", "utf8"));
  expect(credits.sources).toContainEqual(expect.objectContaining({ license: "CC0-1.0", title: "Geometric pigeon" }));
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Export image", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Keep this take & make a variant" }).click();
  await expect.poll(() => branchHeld).toBe(true);
  await expect(page.getByLabel("Revised punchline")).toBeDisabled();
  releaseBranch();
  await expect(page.getByLabel("Revised punchline")).toBeEnabled();
  await expect(page.getByLabel("Revised punchline")).toHaveValue("Brain cell unavailable. Please hold.");
  await page.getByLabel("Revised punchline").fill("This pigeon has administrator privileges.");
  await page.getByRole("button", { name: "Change caption only" }).click();
  await expect.poll(async () => {
    const step = (await emptyCore.call("session.get") as Session).steps[0];
    return step.status === "done" && (step.params.captions as string[] | undefined)?.[0] === "This pigeon has administrator privileges."
      && !!step.outputs[0] && step.outputs[0] !== revised.outputs[0];
  }).toBe(true);
  await page.getByText("Saved takes", { exact: true }).click();
  await page.getByRole("button", { name: "Original", exact: true }).click();
  await expect(page.getByLabel("Revised punchline")).toHaveValue("Brain cell unavailable. Please hold.");
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
  await page.getByRole("button", { name: "Export", exact: true }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Export image", exact: true });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.getByRole("button", { name: "Save image file" }).scrollIntoViewIfNeeded();
  const bounds = await page.getByRole("button", { name: "Save image file" }).boundingBox();
  expect(bounds!.height).toBeGreaterThanOrEqual(24);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(600);
  await page.screenshot({ path: info.outputPath("quick-share-200-percent.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeFocused();
  // Wrapped pane headings must keep their controls above the scrolling cards.
  await page.evaluate(() => { document.documentElement.dataset.theme = "terminal"; });
  await page.getByRole("navigation", { name: "Workspace panels" }).getByRole("button", { name: "Ideas" }).click();
  await page.getByRole("button", { name: /^all tools$/i }).click();
  await expect(page.getByRole("button", { name: "Run tool", exact: true })).toBeVisible();
});
