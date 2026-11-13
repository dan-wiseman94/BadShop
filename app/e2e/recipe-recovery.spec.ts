import path from "node:path";
import { test, expect, root } from "./fixtures";
import type { Session, Recipe } from "../src/types";

test("a failed recipe keeps completed pixels, explains the failure and can be repaired", async ({ page, emptyCore }) => {
  const recipe: Recipe = { version: 1, name: "Repairable crop", steps: [
    { tool: "transform", params: { image: "$input", width: 32, height: 32 } },
    { tool: "cutout", params: { image: "$step0", box: [100, 100, 120, 120], no_ai: true } },
  ] };
  await emptyCore.call("recipes.save", { recipe });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await page.getByText("Save a reusable recipe", { exact: true }).click();
  const studio = page.getByRole("region", { name: "Visual recipes" });
  await studio.getByLabel("Saved recipes").selectOption(recipe.name);
  await studio.getByRole("checkbox").first().check();
  await studio.getByRole("button", { name: "Run recipe on selected pictures" }).click();
  await expect(studio.getByRole("status")).toContainText("1 steps completed");
  await expect(studio.getByRole("status")).toContainText("empty or lies outside");
  const failed = await emptyCore.call("session.get") as Session;
  expect(failed.steps.map(step => step.status)).toEqual(["done", "error"]);
  const kept = failed.steps[0].outputs[0];
  const bytes = await emptyCore.call("artifacts.get", { id: kept });
  await studio.getByRole("button", { name: "Edit recipe step 2: cutout" }).click();
  await studio.getByLabel("Box X1", { exact: true }).fill("0");
  await studio.getByLabel("Box Y1", { exact: true }).fill("0");
  await studio.getByLabel("Box X2", { exact: true }).fill("16");
  await studio.getByLabel("Box Y2", { exact: true }).fill("16");
  await studio.getByRole("button", { name: "Keep these recipe controls" }).click();
  await studio.getByRole("button", { name: "Save recipe", exact: true }).click();
  await studio.getByRole("button", { name: "Run recipe on selected pictures" }).click();
  await expect(studio.getByRole("status")).toContainText("2 steps completed");
  const repaired = await emptyCore.call("session.get") as Session;
  expect(repaired.steps.slice(-2).map(step => step.status)).toEqual(["done", "done"]);
  expect(repaired.artifacts[repaired.steps.at(-1)!.outputs[0]]).toMatchObject({ width: 16, height: 16 });
  expect(await emptyCore.call("artifacts.get", { id: kept })).toEqual(bytes);
  const project = path.join(emptyCore.folder, "repaired.badshop");
  page.once("dialog", dialog => dialog.accept(project));
  await page.getByRole("button", { name: "Save session", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).unsaved_changes).toBe(false);
  await emptyCore.call("session.open", { path: project });
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(repaired.steps);
  expect(await emptyCore.call("artifacts.get", { id: kept })).toEqual(bytes);
});

test("stopping a running recipe keeps finished images and permits another run", async ({ page, emptyCore }) => {
  const recipe: Recipe = { version: 1, name: "Many takes", steps: Array.from({ length: 40 }, (_, i) => (
    { tool: "deepfry", params: { image: "$input", seed: i + 1, level: 2 } }
  )) };
  await emptyCore.call("recipes.save", { recipe });
  await emptyCore.call("recipes.save", { recipe: { ...recipe, name: "One more", steps: recipe.steps.slice(0, 1) } });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await page.getByText("Save a reusable recipe", { exact: true }).click();
  const studio = page.getByRole("region", { name: "Visual recipes" });
  await studio.getByLabel("Saved recipes").selectOption(recipe.name);
  await studio.getByRole("checkbox").first().check();
  await studio.getByRole("button", { name: "Run recipe on selected pictures" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps.filter(step => step.status === "done").length,
    { intervals: [25, 50, 100] }).toBeGreaterThan(0);
  await studio.getByRole("button", { name: "Stop recipe batch" }).click();
  await expect(studio.getByRole("status")).toContainText("stopped");
  const stopped = await emptyCore.call("session.get") as Session;
  expect(stopped.batch_running).toBe(false);
  expect(stopped.steps.length).toBeLessThan(40);
  expect(stopped.steps.every(step => step.status !== "running")).toBe(true);
  const completed = stopped.steps.filter(step => step.status === "done");
  expect(completed.length).toBeGreaterThan(0);
  const kept = completed[0].outputs[0];
  const bytes = await emptyCore.call("artifacts.get", { id: kept });
  await studio.getByLabel("Saved recipes").selectOption("One more");
  await studio.getByRole("button", { name: "Run recipe on selected pictures" }).click();
  await expect(studio.getByRole("status")).toHaveText("1 steps completed. ");
  expect((await emptyCore.call("session.get") as Session).steps.at(-1)?.status).toBe("done");
  const project = path.join(emptyCore.folder, "stopped.badshop");
  page.once("dialog", dialog => dialog.accept(project));
  await page.getByRole("button", { name: "Save session", exact: true }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).unsaved_changes).toBe(false);
  await emptyCore.call("session.open", { path: project });
  expect(await emptyCore.call("artifacts.get", { id: kept })).toEqual(bytes);
});
