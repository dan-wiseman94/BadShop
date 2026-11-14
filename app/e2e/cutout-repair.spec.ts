import path from "node:path";
import { test, expect, root } from "./fixtures";
import type { Session } from "../src/types";

test("polygon repair previews without mutation and survives save reopen and replay", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Edit a photo without AI" }).click();
  const imported = await emptyCore.call("artifacts.import", {
    path: path.join(root, "core/tests/fixtures/lincoln.png"),
  }) as { working: { id: string } };
  await emptyCore.call("tools.run", { tool: "cutout", params: { image: imported.working.id, no_ai: true } });
  await page.locator(".step").first().click();
  const details = page.locator(".step-detail");
  const region = details.getByRole("region", { name: "Repair cutout selection" });
  await region.getByLabel("Region action").selectOption("remove_regions");
  const svg = region.getByRole("img", { name: "Original picture for cutout regions" });
  const bounds = (await svg.boundingBox())!;
  for (const [x, y] of [[0.3, 0.3], [0.6, 0.3], [0.6, 0.6], [0.3, 0.6]]) {
    await svg.click({ position: { x: bounds.width * x, y: bounds.height * y } });
  }
  await region.getByRole("button", { name: "Add region", exact: true }).click();
  const before = await emptyCore.call("session.get") as Session;
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = details.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  const pixels = (await preview.getAttribute("src"))!.split(",")[1];
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(before.steps);
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0].status).toBe("done");
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0].outputs[0]).not.toBe(before.steps[0].outputs[0]);
  const edited = (await emptyCore.call("session.get") as Session).steps[0];
  expect(edited.params.remove_regions).toHaveLength(1);
  expect((await emptyCore.call("artifacts.get", { id: edited.outputs[0] }) as { data: string }).data).toBe(pixels);
  const file = path.join(emptyCore.folder, "repair.badshop");
  await emptyCore.call("session.save_as", { path: file });
  await emptyCore.call("session.open", { path: file });
  await emptyCore.call("steps.edit", { step_id: edited.id, params: edited.params });
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0].status).toBe("done");
  expect((await emptyCore.call("session.get") as Session).steps[0].outputs).toEqual(edited.outputs);
});
