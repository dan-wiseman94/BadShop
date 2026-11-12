import path from "node:path";
import { test, expect, root } from "./fixtures";
import type { Session, Step } from "../src/types";

test("basic manual toolbar resizes and rotates without an AI turn", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  const manual = page.locator(".manual-tools");
  await manual.locator("summary").click();
  await manual.getByRole("button", { name: "Crop / resize / rotate / flip", exact: true }).click();
  await manual.getByLabel("Width", { exact: true }).fill("32");
  await manual.getByLabel("Height", { exact: true }).fill("24");
  await manual.getByLabel("Rotate", { exact: true }).selectOption("90");
  await manual.getByRole("button", { name: "Apply crop / resize / rotate / flip" }).click();
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0]?.status).toBe("done");
  const session = await emptyCore.call("session.get") as Session;
  expect(session.steps[0].tool).toBe("transform");
  expect(session.artifacts[session.steps[0].outputs[0]]).toMatchObject({ width: 24, height: 32 });
  const output = await emptyCore.call("artifacts.get", { id: session.steps[0].outputs[0] });
  const project = path.join(emptyCore.folder, "manual-transform.badshop");
  await emptyCore.call("session.save_as", { path: project });
  await emptyCore.call("session.open", { path: project });
  expect(await emptyCore.call("artifacts.get", { id: session.steps[0].outputs[0] })).toEqual(output);
});

test("manual correction preview cancels, applies, bypasses and survives reopening", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", {
    path: path.join(root, "core/tests/fixtures/lincoln.png"),
  }) as { working: { id: string } };
  const step = await emptyCore.call("tools.run", {
    tool: "deepfry", params: { image: imported.working.id, level: 2, seed: 1 },
  }) as Step;
  await expect(page.locator(".step").first()).toBeVisible();
  await page.locator(".step").first().click();
  const details = page.locator(".step-detail");
  const before = await emptyCore.call("session.get") as Session;
  await details.getByLabel("Seed", { exact: false }).fill("17");
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  await expect(details.getByAltText("Uncommitted preview 1")).toBeVisible();
  const preview = await details.getByAltText("Uncommitted preview 1").getAttribute("src");
  const uncommitted = await emptyCore.call("session.get") as Session;
  expect(uncommitted.steps).toEqual(before.steps);
  expect(uncommitted.document_revision).toBe(before.document_revision);
  expect(uncommitted.artifacts).toEqual(before.artifacts);
  await details.getByRole("button", { name: "Cancel changes" }).click();
  await expect(details.getByAltText("Uncommitted preview 1")).toHaveCount(0);
  await details.getByLabel("Seed", { exact: false }).fill("17");
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].params.seed).toBe(17);
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].status).toBe("done");
  const applied = await emptyCore.call("session.get") as Session;
  const output = await emptyCore.call("artifacts.get", { id: applied.steps[0].outputs[0] }) as { data: string };
  expect(preview?.split(",")[1]).toBe(output.data);
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  await expect(details.getByAltText("Uncommitted preview 1")).toBeVisible();
  await emptyCore.call("steps.edit", { step_id: step.id, params: { ...applied.steps[0].params, seed: 18 } });
  await expect(details.getByAltText("Uncommitted preview 1")).toHaveCount(0);
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].status).toBe("done");
  await details.getByRole("button", { name: "Bypass effect" }).click();
  await expect(details.getByRole("button", { name: "Enable effect" })).toBeVisible();
  const project = path.join(emptyCore.folder, "manual.badshop");
  await emptyCore.call("session.save_as", { path: project });
  await emptyCore.call("session.open", { path: project });
  const reopened = await emptyCore.call("session.get") as Session;
  expect(reopened.steps[0].bypassed).toBe(true);
  expect(reopened.steps[0].params.seed).toBe(18);
  expect(reopened.steps[0].id).toBe(step.id);
  await page.screenshot({ path: path.join(root, "artifacts/verification/manual-controls.png"), fullPage: true });
});

test("manual placement nudge and a selected variant commit through replay", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", {
    path: path.join(root, "core/tests/fixtures/lincoln.png"),
  }) as { working: { id: string } };
  await emptyCore.call("tools.run", { tool: "paste", params: {
    base: imported.working.id, piece: imported.working.id, fit_box: [40, 40, 140, 180],
  } });
  await page.locator(".step").first().click();
  const detail = page.locator(".step-detail");
  await detail.getByLabel("Placement controls").focus();
  await page.keyboard.press("Shift+ArrowRight");
  await detail.getByRole("button", { name: "Compare three rotate choices" }).click();
  await detail.getByRole("button", { name: /rotate: 15/ }).click();
  expect(((await emptyCore.call("session.get")) as Session).steps).toHaveLength(1);
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].params.rotate).toBe(15);
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].status).toBe("done");
  const result = ((await emptyCore.call("session.get")) as Session).steps[0];
  expect(result.params.at).toEqual([100, 110]);
  expect(result.params.anchor).toBe("center");
  expect(result.params.fit_box).toBeNull();
  expect(Number(result.params.width)).toBeGreaterThan(0);
  await detail.getByText("Keep these settings for AI", { exact: true }).click();
  await detail.getByLabel("Pin Placement").click();
  await expect(detail.getByLabel("Pin Placement")).toBeChecked();
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].locked_fields).toContain("at");
  const oldIds = new Set(Object.keys(((await emptyCore.call("session.get")) as Session).artifacts));
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/trump.png"));
  await expect.poll(async () => Object.keys(((await emptyCore.call("session.get")) as Session).artifacts)
    .some((id) => !oldIds.has(id))).toBe(true);
  const available = Object.values(((await emptyCore.call("session.get")) as Session).artifacts);
  const replacement = available.find((artifact) => !oldIds.has(artifact.id) &&
    !available.some((other) => other.original_id === artifact.id))!;
  await detail.getByRole("combobox", { name: /Piece/ }).selectOption(replacement.id);
  await detail.getByRole("button", { name: "Preview changes", exact: true }).click();
  await expect(detail.getByAltText("Uncommitted preview 1")).toBeVisible();
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => ((await emptyCore.call("session.get")) as Session).steps[0].params.piece).toBe(replacement.id);
  const replaced = ((await emptyCore.call("session.get")) as Session).steps[0];
  expect(replaced.params.at).toEqual(result.params.at);
  expect(replaced.params.rotate).toBe(result.params.rotate);
  expect(replaced.params.width).toBe(result.params.width);
});
