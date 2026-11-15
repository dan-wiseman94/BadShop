import path from "node:path";
import { test, expect, root, expectImageBytes } from "./fixtures";
import type { Session } from "../src/types";

test("finds manual tools by intent and saves a seed after changing basic strength", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Run a tool" });
  const search = dialog.getByRole("textbox", { name: "Search tools" });
  await search.fill("paint a masterpiece");
  await expect(dialog.getByText(/No tools match/)).toBeVisible();
  await expect(dialog.locator(".tool-option")).toHaveCount(0);
  for (const [query, tool] of [
    [" remove BACKGROUND ", "cutout"],
    ["put picture on picture", "paste"],
    ["add words", "text"],
    ["blur face", "censor"],
    ["pixelate", "censor"],
    ["text", "text"],
    ["tex", "text"],
    ["resize", "transform"],
    ["rotate", "transform"],
    ["deep fry", "deepfry"],
  ]) {
    await search.fill(query);
    await expect(dialog.locator(".tool-option").first()).toHaveAccessibleName(new RegExp(`^${tool} `));
  }
  await dialog.getByRole("button", { name: /^deepfry / }).click();
  await expect(dialog.getByLabel("Seed", { exact: false })).toBeHidden();
  await dialog.getByText("Advanced controls", { exact: true }).click();
  await dialog.getByLabel("Seed", { exact: false }).fill("17");
  await dialog.getByText("Advanced controls", { exact: true }).click();
  await dialog.getByLabel("Level", { exact: false }).fill("4");
  await dialog.getByRole("button", { name: "Run tool", exact: true }).click();

  const snapshot = async () => await core.call("session.get") as Session;
  await expect.poll(async () => (await snapshot()).steps[0]?.status).toBe("done");
  const [first] = (await snapshot()).steps;
  expect(first.params).toMatchObject({ level: 4, seed: 17 });
  const inspector = page.locator(".step-detail");
  await expect(inspector.getByLabel("Seed", { exact: false })).toBeHidden();
  await inspector.getByText("Advanced controls", { exact: true }).click();
  await inspector.getByLabel("Seed", { exact: false }).fill("23");
  await inspector.getByText("Advanced controls", { exact: true }).click();
  await inspector.getByLabel("Level", { exact: false }).fill("5");
  await inspector.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => {
    const [applied] = (await snapshot()).steps;
    return applied.status === "done" && applied.outputs[0] !== first.outputs[0];
  }).toBe(true);
  const [step] = (await snapshot()).steps;
  expect(step.id).toBe(first.id);
  expect(step.params).toMatchObject({ level: 5, seed: 23 });
  const output = await core.call("artifacts.get", { id: step.outputs[0] }) as { data: string };
  const project = path.join(core.folder, "tool-discovery.badshop");
  await core.call("session.save_as", { path: project });
  await core.call("session.open", { path: project });
  expect((await snapshot()).steps[0].params).toMatchObject({ level: 5, seed: 23 });
  await expectImageBytes(page.locator(".canvas-image"), output.data);
  await page.locator(".step").first().click();
  await inspector.getByText("Advanced controls", { exact: true }).click();
  await expect(inspector.getByLabel("Seed", { exact: false })).toHaveValue("23");
  await page.screenshot({ path: path.join(root, "artifacts/verification/tool-discovery.png"), fullPage: true });
});
