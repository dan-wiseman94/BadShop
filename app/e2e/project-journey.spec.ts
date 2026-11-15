import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Page } from "@playwright/test";
import { test, expect, expectImageBytes, root, startCore, type Core } from "./fixtures";
import type { Session } from "../src/types";

const snapshot = async (core: Core) => await core.call("session.get") as Session;
const hash = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");

async function connect(page: Page, core: Core) {
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

async function deepfry(page: Page) {
  const previous = await page.locator(".step").count();
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("deepfry");
  await page.getByRole("dialog").getByRole("button", { name: /^deepfry / }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(page.locator(".step")).toHaveCount(previous + 1);
  await expect(page.locator(".step").last()).toContainText("done");
}

async function save(page: Page, core: Core, filename: string) {
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect.poll(async () => (await snapshot(core)).unsaved_changes).toBe(false);
  expect((await readFile(filename)).length).toBeGreaterThan(0);
}

async function expectImage(page: Page, core: Core, id: string) {
  const artifact = await core.call("artifacts.get", { id }) as { mime: string; data: string };
  const image = page.locator(".canvas-image");
  await expectImageBytes(image, artifact.data);
  await expect.poll(() => image.evaluate(node => {
    const img = node as HTMLImageElement;
    return img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;
  })).toBe(true);
  expect(hash(Buffer.from(artifact.data, "base64"))).toBe((await snapshot(core)).artifacts[id].blob_id);
  return Buffer.from(artifact.data, "base64");
}

async function exported(page: Page, previous = "") {
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await page.getByRole("button", { name: "Save image", exact: true }).click();
  let filename = "";
  await expect.poll(async () => {
    const message = await page.getByRole("status").innerText();
    filename = message.startsWith("Exported to ") ? message.slice("Exported to ".length).trim() : "";
    return filename !== "" && filename !== previous;
  }).toBe(true);
  await page.getByRole("button", { name: "Close export" }).click();
  return { filename, bytes: await readFile(filename) };
}

test("compact workspace imports, edits and reopens the saved canvas from More tools", async ({ page, emptyCore }) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await connect(page, emptyCore);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const viewer = page.getByRole("region", { name: "Image viewer" });
  await viewer.getByRole("button", { name: "Add images", exact: true }).click();
  const selecting = page.waitForEvent("filechooser");
  await page.getByRole("dialog", { name: "Add material" }).getByRole("button", { name: "Choose files" }).click();
  await (await selecting).setFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await expect(viewer.locator(".canvas-image")).toHaveAttribute("alt", /lincoln_work/);
  await page.getByRole("button", { name: "More tools", exact: true }).click();
  const palette = page.getByRole("dialog", { name: "Run a tool" });
  await palette.getByLabel("Search tools").fill("deepfry");
  await palette.getByRole("button", { name: /^deepfry / }).click();
  await palette.getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(viewer.locator(".canvas-image")).toHaveAttribute("alt", /_deepfried$/);
  const before = await snapshot(emptyCore);
  expect(before.steps).toHaveLength(1);
  expect(before.steps[0]).toMatchObject({ tool: "deepfry", status: "done" });
  const output = before.steps[0].outputs[0];
  const expected = await expectImage(page, emptyCore, output);

  const project = path.join(emptyCore.folder, "compact.badshop");
  await save(page, emptyCore, project);
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(project));
  await page.getByRole("button", { name: /^Open session/ }).click();
  expect(await expectImage(page, emptyCore, output)).toEqual(expected);
  expect((await snapshot(emptyCore)).steps).toEqual(before.steps);
});

test("manual editing, replay, a fresh process reopen and export preserve the actual image bytes", async ({ page, context, emptyCore }) => {
  await connect(page, emptyCore);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  expect(Object.keys((await snapshot(emptyCore)).artifacts)).toHaveLength(0);
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await deepfry(page);
  await deepfry(page);
  const before = await snapshot(emptyCore);
  expect(before.steps[1].params.image).toBe(before.steps[0].outputs[0]);
  await page.locator(".step").first().click();
  const detail = page.locator(".step-detail");
  await detail.getByText("Advanced controls", { exact: true }).click();
  await detail.getByLabel("Seed", { exact: false }).fill("19");
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => {
    const current = await snapshot(emptyCore);
    return current.steps.every(step => step.status === "done") &&
      current.steps[1].outputs[0] !== before.steps[1].outputs[0];
  }).toBe(true);
  const edited = await snapshot(emptyCore);
  expect(edited.steps[0].params.seed).toBe(19);
  expect(edited.steps[1].params.image).toBe(edited.steps[0].outputs[0]);
  await page.locator(".step").last().click();
  const expected = await expectImage(page, emptyCore, edited.steps[1].outputs[0]);
  const project = path.join(emptyCore.folder, "edited.badshop");
  await save(page, emptyCore, project);
  const savedFile = await readFile(project);
  await page.close();
  await emptyCore.close();

  // A separate profile has neither this session nor an autosave to mask a broken project file.
  const fresh = await startCore(path.join(emptyCore.folder, "fresh-profile"));
  try {
    expect(Object.keys((await snapshot(fresh)).artifacts)).toHaveLength(0);
    const reopened = await context.newPage();
    await connect(reopened, fresh);
    await reopened.locator(".session-name").click();
    reopened.once("dialog", dialog => dialog.accept(project));
    await reopened.getByRole("button", { name: /^Open session/ }).click();
    await expect(reopened.locator(".step")).toHaveCount(2);
    const restored = await snapshot(fresh);
    expect(restored.id).toBe(edited.id);
    expect(restored.steps).toEqual(edited.steps);
    // Saving intentionally drops superseded replay outputs. Keep every imported
    // source/working copy and the active dependency chain, with exact metadata.
    const required = new Set([
      ...Object.values(edited.artifacts).filter(artifact => !artifact.produced_by).map(artifact => artifact.id),
      ...edited.steps.flatMap(step => step.outputs),
    ]);
    expect(restored.artifacts).toEqual(Object.fromEntries(
      [...required].map(id => [id, edited.artifacts[id]]),
    ));
    await reopened.locator(".step").last().click();
    expect(await expectImage(reopened, fresh, edited.steps[1].outputs[0])).toEqual(expected);
    const first = await exported(reopened);
    const second = await exported(reopened, first.filename);
    expect(first.bytes).toEqual(expected);
    expect(second.bytes).toEqual(expected);
    expect(await readFile(first.filename)).toEqual(expected);
    await reopened.getByRole("button", { name: "Before", exact: true }).click();
    const input = await expectImage(reopened, fresh, String(edited.steps[1].params.image));
    expect((await exported(reopened, second.filename)).bytes).toEqual(input);
    expect(input).not.toEqual(expected);
    expect(await readFile(project)).toEqual(savedFile);
    await reopened.close();
  } finally { await fresh.close(); }
});

test("opening a damaged project preserves the current document, draft, image and last good save", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await connect(page, core);
  await deepfry(page);
  const project = path.join(core.folder, "last-good.badshop");
  await save(page, core, project);
  const savedFile = await readFile(project);
  const before = await snapshot(core);
  const picture = await expectImage(page, core, before.steps[0].outputs[0]);
  await page.getByLabel("Message your agent").fill("Keep my unsent idea");
  const damaged = path.join(core.folder, "damaged.badshop");
  await writeFile(damaged, "This is not a project ZIP");
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(damaged));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await expect(page.getByRole("alert")).toContainText(/isn't a badshop project|damaged/);
  await expect(page.getByLabel("Message your agent")).toHaveValue("Keep my unsent idea");
  const current = await snapshot(core);
  expect(current.id).toBe(before.id);
  expect(current.steps).toEqual(before.steps);
  expect(current.artifacts).toEqual(before.artifacts);
  expect(await expectImage(page, core, before.steps[0].outputs[0])).toEqual(picture);
  expect(await readFile(project)).toEqual(savedFile);
  expect((await exported(page)).bytes).toEqual(picture);
});

test("replaying a selected output refreshes the canvas and exported bytes", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await connect(page, core);
  await deepfry(page);
  const before = (await snapshot(core)).steps[0].outputs[0];
  const detail = page.locator(".step-detail");
  await detail.locator(".provenance .artifact-thumb").click();
  const oldBytes = await expectImage(page, core, before);

  await detail.getByText("Advanced controls", { exact: true }).click();
  await detail.getByLabel("Seed", { exact: false }).fill("19");
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => {
    const step = (await snapshot(core)).steps[0];
    return step.status === "done" && step.outputs[0] !== before;
  }).toBe(true);
  const after = (await snapshot(core)).steps[0];
  expect(after.status).toBe("done");
  const newBytes = await expectImage(page, core, after.outputs[0]);
  expect(newBytes).not.toEqual(oldBytes);
  expect((await exported(page)).bytes).toEqual(newBytes);
});

test("Versions compares stored pixels without switching and preserves renamed takes after reopen", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  const source = Object.keys((await snapshot(core)).artifacts)[0];
  const first = await core.call("tools.run", {
    tool: "deepfry", params: { image: source, seed: 7, level: 1 },
  }) as Session["steps"][number];
  await connect(page, core);
  const original = await core.call("artifacts.get", { id: first.outputs[0] }) as { data: string };
  const versions = page.getByRole("button", { name: "Versions", exact: true });
  const panel = page.getByRole("dialog", { name: "Versions", exact: true });
  const close = panel.getByRole("button", { name: "Close Versions" });
  const take = panel.getByRole("article", { name: "Fried version", exact: true });
  const originalTake = panel.getByRole("article", { name: "Original", exact: true });

  await versions.click();
  await panel.getByLabel("New take name").fill("Fried version");
  await panel.getByRole("button", { name: "Duplicate", exact: true }).click();
  await expect(take).toContainText("Active");
  await expect(take).toContainText("1 step");
  await expect(panel.getByRole("status")).toContainText("Save project to keep them on disk.");
  await close.click();
  await expect(versions).toBeFocused();

  const second = await core.call("tools.run", {
    tool: "deepfry", params: { image: first.outputs[0], seed: 73, level: 2 },
  }) as Session["steps"][number];
  const expectedBytes = await expectImage(page, core, second.outputs[0]);
  const secondImage = Buffer.from(expectedBytes).toString("base64");

  await versions.click();
  await expect(take).toContainText("2 steps");
  await originalTake.getByRole("checkbox", { name: "Compare", exact: true }).check();
  await take.getByRole("checkbox", { name: "Compare", exact: true }).check();
  const comparison = panel.getByRole("region", { name: "Take comparison" });
  await expectImageBytes(comparison.getByRole("img", { name: "Original" }), original.data);
  await expectImageBytes(comparison.getByRole("img", { name: "Fried version" }), secondImage);
  await expect(comparison.getByText(/\d+ × \d+/)).toHaveCount(2);
  expect((await snapshot(core)).steps).toEqual([first, second]);
  await expectImageBytes(page.locator(".canvas-image"), secondImage);

  await take.getByRole("button", { name: "Rename", exact: true }).click();
  await take.getByLabel("Take name").fill("Extra crispy");
  await take.getByRole("button", { name: "Save name", exact: true }).click();
  const renamed = panel.getByRole("article", { name: "Extra crispy", exact: true });
  await expect(renamed).toContainText("Active");
  await originalTake.getByRole("button", { name: "Open take", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("Editing: Original");
  await close.click();
  await expectImage(page, core, first.outputs[0]);

  const filename = path.join(core.folder, "two-takes.badshop");
  await core.call("session.save_as", { path: filename });
  expect((await readFile(filename)).length).toBeGreaterThan(0);
  await core.call("session.open", { path: filename });
  await page.reload();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await versions.click();
  await expect(originalTake).toContainText("Active");
  await renamed.getByRole("button", { name: "Open take", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("Editing: Extra crispy");
  await close.click();
  expect((await snapshot(core)).steps).toEqual([first, second]);
  expect(await expectImage(page, core, second.outputs[0])).toEqual(expectedBytes);

  await versions.click();
  await originalTake.getByRole("button", { name: "Delete", exact: true }).click();
  await originalTake.getByRole("button", { name: "Delete take", exact: true }).click();
  await expect(originalTake).toHaveCount(0);
  const shared = await core.call("artifacts.get", { id: first.outputs[0] }) as { data: string };
  expect(shared.data).toBe(original.data);
});

test("Versions protects a dirty Quick ideas draft until the user chooses to discard it", async ({ page, core }) => {
  await connect(page, core);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByRole("button", { name: /An error with no solution/ }).click();
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  const edit = page.getByRole("textbox", { name: "Headline", exact: true });
  await expect(edit).toBeVisible();
  const versions = page.getByRole("button", { name: "Versions", exact: true });
  const panel = page.getByRole("dialog", { name: "Versions", exact: true });
  const close = panel.getByRole("button", { name: "Close Versions" });
  await versions.click();
  await panel.getByLabel("New take name").fill("Working copy");
  await panel.getByRole("button", { name: "Duplicate", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Editing: Working copy");
  await close.click();
  await edit.fill("Unsaved punchline");
  const before = await snapshot(core);
  const openOriginal = panel.getByRole("article", { name: "Original", exact: true })
    .getByRole("button", { name: "Open take", exact: true });
  await versions.click();
  await openOriginal.click();
  const decision = page.getByRole("dialog", { name: "Unsaved changes to this joke" });
  await decision.getByRole("button", { name: "Keep editing" }).click();
  await close.click();
  await expect(edit).toHaveValue("Unsaved punchline");
  expect((await snapshot(core)).context?.branch_id).toBe(before.context?.branch_id);

  await versions.click();
  await openOriginal.click();
  await decision.getByRole("button", { name: "Discard changes" }).click();
  await expect(panel.getByRole("status")).toContainText("Editing: Original");
  await close.click();
  expect((await snapshot(core)).steps).toEqual(before.steps);
  await expect(edit).toHaveValue(String(before.steps.at(-1)?.params.title));
});

test("a failed crop can be saved, reopened and repaired without losing its dependent output", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await connect(page, core);
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("cutout");
  await page.getByRole("button", { name: /^cutout crop/ }).click();
  const dialog = page.getByRole("dialog", { name: "Run a tool" });
  await dialog.getByLabel(/^No Ai/i).check();
  await dialog.getByLabel("Box X2", { exact: true }).fill("90");
  await dialog.getByLabel("Box Y2", { exact: true }).fill("90");
  await dialog.getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(page.locator(".step").first()).toContainText("done");
  await deepfry(page);
  const before = await snapshot(core);
  const [crop, fried] = before.steps;
  const image = before.artifacts[String(crop.params.image)];
  expect(fried.params.image).toBe(crop.outputs[0]);
  const original = await expectImage(page, core, fried.outputs[0]);
  const detail = page.locator(".step-detail");
  await page.locator(".step").first().click();
  await detail.getByLabel("Box X1", { exact: true }).fill(String(image.width + 1));
  await detail.getByLabel("Box X2", { exact: true }).fill(String(image.width + 20));
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect(detail.locator(".inline-error")).toContainText("empty or lies outside");
  await expect(page.locator(".step").last()).toContainText("stale");
  const failed = (await snapshot(core)).steps;
  expect(failed[0].outputs).toEqual([]);
  expect(failed[1].params.image).toBe(crop.outputs[0]);
  expect(failed[1].outputs).toEqual(fried.outputs);

  const filename = path.join(core.folder, "failed-crop.badshop");
  await save(page, core, filename);
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(filename));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await expect(detail).toHaveCount(0);
  expect((await snapshot(core)).steps).toEqual(failed);
  await page.locator(".step").first().click();
  await expect(detail.locator(".inline-error")).toContainText("empty or lies outside");
  await detail.getByLabel("Box X1", { exact: true }).fill("0");
  await detail.getByLabel("Box X2", { exact: true }).fill("120");
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => (await snapshot(core)).steps.map(step => step.status)).toEqual(["done", "done"]);
  const [repaired, replayed] = (await snapshot(core)).steps;
  expect(repaired.outputs[0]).not.toBe(crop.outputs[0]);
  expect(replayed.params.image).toBe(repaired.outputs[0]);
  await page.locator(".step").last().click();
  const corrected = await expectImage(page, core, replayed.outputs[0]);
  expect(corrected).not.toEqual(original);
  expect((await exported(page)).bytes).toEqual(corrected);
});

test("a later sprite output stays selected when replay changes every cell", async ({ page, core }) => {
  const image = Object.values((await snapshot(core)).artifacts).find(artifact => artifact.label.includes("work"))!;
  // Seed the completed sheet. Selecting the cell, editing its grid and exporting all use the UI.
  await core.call("tools.run", { tool: "slice_sheet", params: { image: image.id, rows: 1, columns: 2 } });
  const before = (await snapshot(core)).steps[0];
  expect(before.outputs).toHaveLength(2);
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await connect(page, core);
  await page.locator(".step").first().click();
  const detail = page.locator(".step-detail");
  await detail.locator(".provenance .artifact-thumb").nth(1).click();
  await expectImage(page, core, before.outputs[1]);

  await detail.getByLabel(/^Rows/).press("ArrowRight");
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect(detail.locator(".provenance")).toHaveCount(4);
  const after = (await snapshot(core)).steps[0];
  expect(after.params.rows).toBe(2);
  expect(after.outputs[1]).not.toBe(before.outputs[1]);
  const selected = await expectImage(page, core, after.outputs[1]);
  expect((await exported(page)).bytes).toEqual(selected);
});
