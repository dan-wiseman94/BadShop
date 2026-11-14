import path from "node:path";
import { test, expect, root, python } from "./fixtures";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import type { Session, Step } from "../src/types";

test("HEIC file import displays decoded pixels and preserves original bytes across reopen", async ({ page, emptyCore }) => {
  const source = path.join(emptyCore.folder, "phone.heic");
  execFileSync(python, ["-c", "from PIL import Image; from pillow_heif import register_heif_opener; import sys; register_heif_opener(); Image.new('RGB',(64,32),(30,140,220)).save(sys.argv[1],format='HEIF',quality=-1)", source]);
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  await page.getByLabel("Import image files").setInputFiles(source);
  const canvas = page.locator(".canvas-image");
  await expect.poll(() => canvas.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([64, 32]);
  const before = await emptyCore.call("session.get") as Session;
  const original = Object.values(before.artifacts).find(item => item.format === "HEIF")!;
  expect(original).toBeTruthy();
  const bytes = await readFile(source);
  expect((await emptyCore.call("artifacts.get", { id: original.id }) as { data: string }).data).toBe(bytes.toString("base64"));
  const displayed = await canvas.getAttribute("src");
  const file = path.join(emptyCore.folder, "phone.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  await page.reload();
  await expect(canvas).toHaveAttribute("src", displayed!);
  expect((await emptyCore.call("artifacts.get", { id: original.id }) as { data: string }).data).toBe(bytes.toString("base64"));
});

test("recorded canvas elements open existing controls and survive replay and reopen", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/lincoln.png") }) as { working: { id: string } };
  const picture = await emptyCore.call("tools.run", { tool: "paste", params: {
    base: imported.working.id, piece: imported.working.id, width: 80, height: 60, at: [10, 100], rotate: 15,
  } }) as Step;
  const caption = await emptyCore.call("tools.run", { tool: "text", params: {
    image: picture.outputs[0], text: "Select me", size: 24, preserve_case: true,
  } }) as Step;
  const before = await emptyCore.call("session.get") as Session;
  const viewer = page.getByRole("region", { name: "Image viewer" });
  await viewer.getByRole("button", { name: "Select elements", exact: true }).click();
  await viewer.getByRole("button", { name: "Edit Caption: Select me", exact: true }).click();
  const details = page.locator(".step-detail");
  await expect(details.getByLabel("Exact caption", { exact: false })).toHaveValue("Select me");
  expect((await emptyCore.call("session.get") as Session).document_revision).toBe(before.document_revision);
  await viewer.getByRole("button", { name: /Edit Picture: step/ }).click();
  await details.getByLabel("Rotation", { exact: true }).fill("30");
  await details.getByLabel("Preview final result, including later steps").check();
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = details.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  const bytes = (await preview.getAttribute("src"))!.split(",")[1];
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(before.steps);
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => {
    const step = (await emptyCore.call("session.get") as Session).steps[1];
    return step.status === "done" && !!step.outputs[0] && step.outputs[0] !== caption.outputs[0];
  }).toBe(true);
  const after = await emptyCore.call("session.get") as Session;
  expect((await emptyCore.call("artifacts.get", { id: after.steps[1].outputs[0] }) as { data: string }).data).toBe(bytes);
  const file = path.join(emptyCore.folder, "elements.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  await page.reload();
  await viewer.getByRole("button", { name: "Select elements", exact: true }).click();
  await viewer.getByRole("button", { name: "Edit Caption: Select me", exact: true }).click();
  await expect(details.getByLabel("Exact caption", { exact: false })).toHaveValue("Select me");
  expect((await emptyCore.call("session.get") as Session).steps[0].data).toEqual(after.steps[0].data);
});

test("material roles and a reusable library picture feed manual composition and persist", async ({ page, emptyCore }) => {
  const imported = await emptyCore.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/lincoln.png") }) as { working: { id: string } };
  await emptyCore.call("library.save", { artifact_id: imported.working.id, name: "Recurring Lincoln", tags: ["cast"] });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  await page.getByText("Saved characters & materials", { exact: true }).click();
  await page.getByLabel("Find material", { exact: true }).fill("Recurring");
  await page.getByRole("button", { name: /Recurring Lincoln/ }).click();
  const viewer = page.getByRole("region", { name: "Image viewer" });
  await viewer.getByRole("button", { name: "Use as subject", exact: true }).click();
  await viewer.getByRole("button", { name: "Use as background", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).creative?.source_roles.background).toBe(imported.working.id);
  await viewer.getByText("Manual tools", { exact: true }).click();
  await viewer.getByRole("button", { name: "Compose subject on background", exact: true }).click();
  await viewer.getByRole("button", { name: "Apply compose subject on background", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  const session = await emptyCore.call("session.get") as Session;
  expect(session.steps[0].params.base).toBe(imported.working.id);
  expect(session.steps[0].params.piece).toBe(imported.working.id);
  const file = path.join(emptyCore.folder, "materials.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  expect((await emptyCore.call("session.get") as Session).creative?.source_roles).toEqual(session.creative?.source_roles);
});

test("final preview includes later steps and cancel leaves the project unchanged", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/lincoln.png") }) as { working: { id: string } };
  const first = await emptyCore.call("tools.run", { tool: "deepfry", params: { image: imported.working.id, level: 2, seed: 1 } }) as Step;
  await emptyCore.call("tools.run", { tool: "transform", params: { image: first.outputs[0], width: 64, height: 48 } });
  await page.locator(".step").first().click();
  const details = page.locator(".step-detail");
  const before = await emptyCore.call("session.get") as Session;
  await details.getByLabel("Seed", { exact: false }).fill("17");
  await details.getByLabel("Preview final result, including later steps").check();
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = details.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([64, 48]);
  const bytes = (await preview.getAttribute("src"))!.split(",")[1];
  const during = await emptyCore.call("session.get") as Session;
  expect(during.steps).toEqual(before.steps);
  expect(during.artifacts).toEqual(before.artifacts);
  expect(during.document_revision).toBe(before.document_revision);
  await details.getByRole("button", { name: "Cancel changes" }).click();
  await expect(preview).toHaveCount(0);
  await details.getByLabel("Seed", { exact: false }).fill("17");
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[1].outputs[0]).not.toBe(before.steps[1].outputs[0]);
  const after = await emptyCore.call("session.get") as Session;
  expect((await emptyCore.call("artifacts.get", { id: after.steps[1].outputs[0] }) as { data: string }).data).toBe(bytes);
});

test("manual caption retains exact wording and alignment after reopening", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await expect(page.locator(".canvas-image")).toBeVisible();
  const manual = page.locator(".manual-tools");
  await manual.locator("summary").click();
  await manual.getByRole("button", { name: "Text", exact: true }).click();
  await manual.getByLabel("Exact caption", { exact: false }).fill("Hello  World\n\nMixed Case");
  await manual.getByLabel("Align", { exact: true }).selectOption("left");
  await manual.getByLabel("Frame", { exact: true }).selectOption("bubble");
  await manual.getByLabel("Tail X", { exact: true }).fill("180");
  await manual.getByLabel("Tail Y", { exact: true }).fill("250");
  const before = await emptyCore.call("session.get") as Session;
  await manual.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = manual.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  const bytes = (await preview.getAttribute("src"))!.split(",")[1];
  expect((await emptyCore.call("session.get") as Session).artifacts).toEqual(before.artifacts);
  await manual.getByRole("button", { name: "Apply text", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  const session = await emptyCore.call("session.get") as Session;
  expect(session.steps[0].params).toMatchObject({ text: "Hello  World\n\nMixed Case", preserve_case: true,
    preserve_line_breaks: true, fit_exact: true, align: "left", font: "bundled", frame: "bubble", tail: [180, 250] });
  expect((await emptyCore.call("artifacts.get", { id: session.steps[0].outputs[0] }) as { data: string }).data).toBe(bytes);
  const file = path.join(emptyCore.folder, "exact-caption.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  await emptyCore.call("steps.edit", { step_id: session.steps[0].id, params: session.steps[0].params });
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  expect((await emptyCore.call("session.get") as Session).steps[0].outputs).toEqual(session.steps[0].outputs);
});

test("manual undo redo restores dependent output across project reopening", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/lincoln.png") }) as { working: { id: string } };
  const first = await emptyCore.call("tools.run", { tool: "deepfry", params: { image: imported.working.id, level: 2, seed: 1 } }) as Step;
  await emptyCore.call("tools.run", { tool: "transform", params: { image: first.outputs[0], width: 64, height: 48 } });
  const before = await emptyCore.call("session.get") as Session;
  await page.locator(".step").first().click();
  const details = page.locator(".step-detail");
  await details.getByLabel("Seed", { exact: false }).fill("19");
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[1].outputs[0]).not.toBe(before.steps[1].outputs[0]);
  const after = await emptyCore.call("session.get") as Session;
  const viewer = page.getByRole("region", { name: "Image viewer" });
  await viewer.getByRole("button", { name: "Undo", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[1].outputs).toEqual(before.steps[1].outputs);
  const file = path.join(emptyCore.folder, "manual-history.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  await page.reload();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await viewer.getByRole("button", { name: "Redo", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[1].outputs).toEqual(after.steps[1].outputs);
  await viewer.getByRole("button", { name: "Undo", exact: true }).click();
  await emptyCore.call("tools.run", { tool: "transform", params: { image: imported.working.id, width: 32 } });
  await expect(viewer.getByRole("button", { name: "Redo", exact: true })).toBeDisabled();
});
