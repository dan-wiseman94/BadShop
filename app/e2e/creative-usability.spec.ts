import path from "node:path";
import type { Page } from "@playwright/test";
import { test, expect, root, type Core } from "./fixtures";
import type { Session, Step } from "../src/types";

async function openStudio(page: Page, core: Core, selectStep = false) {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  if (selectStep) await page.locator(".step").last().click();
  await page.getByRole("button", { name: "Images & directions", exact: true }).click();
}

test("quick idea uses the photo added from its own import button", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByRole("button", { name: /An error with no solution/ }).click();
  const picker = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add my own image" }).click();
  await page.getByRole("dialog", { name: "Add material" }).getByRole("button", { name: "Choose files" }).click();
  await (await picker).setFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await expect.poll(async () => Object.keys((await emptyCore.call("session.get") as Session).artifacts).length).toBeGreaterThan(0);
  const imported = await emptyCore.call("session.get") as Session;
  const photo = Object.values(imported.artifacts).find(image => !Object.values(imported.artifacts).some(other => other.original_id === image.id))!;
  await expect(page.getByRole("combobox", { name: "Picture", exact: true })).toHaveValue(photo.id);
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps.at(-1)?.status).toBe("done");
  const built = (await emptyCore.call("session.get") as Session).steps.at(-1)!;
  expect(built.params.images).toEqual([photo.id]);
  const expected = await emptyCore.call("tools.run", { tool: "layout", params: { ...built.params, images: [photo.id] } }) as Step;
  expect(built.outputs).toEqual(expected.outputs);
  const pixels = await emptyCore.call("artifacts.get", { id: built.outputs[0] }) as { mime: string; data: string };
  await expect(page.locator(".canvas-image")).toHaveAttribute("src", `data:${pixels.mime};base64,${pixels.data}`);
});

test("preparing a source search preserves the generated idea briefs", async ({ page, core }) => {
  await openStudio(page, core);
  await page.getByRole("button", { name: "Idea mixer", exact: true }).click();
  await page.getByLabel("Idea subject").fill("A pigeon with administrator privileges");
  await page.getByRole("button", { name: "Mix six ideas", exact: true }).click();
  await expect(page.locator(".idea-cards article")).toHaveCount(6);
  const briefs = await page.locator(".idea-cards pre").allTextContents();
  await page.getByRole("button", { name: "Prepare a source search", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Find candidates", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Idea mixer", exact: true }).click();
  await expect(page.locator(".idea-cards article")).toHaveCount(6);
  expect(await page.locator(".idea-cards pre").allTextContents()).toEqual(briefs);
});

test("layout drafts survive visiting another material source", async ({ page, core }) => {
  await openStudio(page, core);
  await page.getByRole("button", { name: "Layouts & packs", exact: true }).click();
  await page.getByLabel("Layout title").fill("My unfinished card");
  await page.getByRole("textbox", { name: "Caption for Character", exact: true }).fill("Keep this punchline");
  await page.getByRole("button", { name: "Find images", exact: true }).click();
  await page.getByRole("button", { name: "Layouts & packs", exact: true }).click();
  await expect(page.getByLabel("Layout title")).toHaveValue("My unfinished card");
  await expect(page.getByRole("textbox", { name: "Caption for Character", exact: true })).toHaveValue("Keep this punchline");
  await page.getByRole("button", { name: "Branches", exact: true }).click();
  await page.getByLabel("New branch name").fill("A fresh direction");
  await page.getByRole("button", { name: "Create & switch", exact: true }).click();
  await expect(page.getByText("A fresh direction (current)")).toBeVisible();
  await page.getByRole("button", { name: "Layouts & packs", exact: true }).click();
  await expect(page.getByLabel("Layout title")).toHaveValue("");
  await expect(page.getByRole("textbox", { name: "Caption for Character", exact: true })).toHaveValue("");
});

test("saving retro defaults persists the displayed seed into a new project", async ({ page, core }) => {
  await openStudio(page, core);
  await page.getByRole("button", { name: "Retro workbench", exact: true }).click();
  await page.getByLabel("Seed", { exact: true }).fill("42");
  await page.getByRole("button", { name: "Use these defaults for new projects", exact: true }).click();
  await expect.poll(async () => (await core.call("settings.get") as { creative_defaults: { seed: number } }).creative_defaults.seed).toBe(42);
  await core.call("session.new", { name: "Uses my seed", expected_revision: (await core.call("session.get") as Session).document_revision, discard_unsaved: true });
  expect((await core.call("session.get") as Session).creative?.seed).toBe(42);
  await page.reload();
  await page.getByRole("button", { name: "Images & directions", exact: true }).click();
  await page.getByRole("button", { name: "Retro workbench", exact: true }).click();
  await expect(page.getByLabel("Seed", { exact: true })).toHaveValue("42");
});

test("inspecting a branch result reveals its actual image at full size", async ({ page, core }) => {
  const session = await core.call("session.get") as Session;
  const source = Object.keys(session.artifacts)[0];
  const first = await core.call("tools.run", { tool: "deepfry", params: { image: source, seed: 1, level: 1 } }) as Step;
  await core.call("branches.create", { name: "Another take" });
  await core.call("tools.run", { tool: "deepfry", params: { image: source, seed: 2, level: 1 } });
  await openStudio(page, core, true);
  await page.getByRole("button", { name: "Retro workbench", exact: true }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("checkbox", { name: "Original", exact: true }).check();
  await page.getByRole("button", { name: "Inspect full size", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Images & directions", exact: true })).toBeHidden();
  const image = await core.call("artifacts.get", { id: first.outputs[0] }) as { mime: string; data: string };
  await expect(page.locator(".canvas-image")).toHaveAttribute("src", `data:${image.mime};base64,${image.data}`);
  await expect(page.getByRole("combobox", { name: "Zoom", exact: true })).toHaveValue("1");
  await expect(page.getByRole("button", { name: "Before", exact: true })).toBeDisabled();
});
