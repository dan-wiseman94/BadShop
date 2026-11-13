import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "./fixtures";
import type { Session } from "../src/types";

const root = fileURLToPath(new URL("../../", import.meta.url));

test("personal previews stay outside history and the chosen layout survives reopening", async ({ page, emptyCore }, info) => {
  await emptyCore.call("settings.set", { values: { no_remote: true } });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await expect(page.getByAltText("Preview with your picture")).toHaveCount(6);
  const before = await emptyCore.call("session.get") as Session;
  expect(before.steps).toHaveLength(0);
  const card = page.getByRole("button", { name: /A deeply useless trading card/ });
  const preview = await card.locator("img").getAttribute("src");
  await card.click();
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect(page.locator(".canvas-image")).toHaveAttribute("src", preview!);
  const created = await emptyCore.call("session.get") as Session;
  expect(created.steps).toHaveLength(1);
  expect(created.steps[0].params.images).toEqual([Object.keys(before.artifacts).find(id => before.artifacts[id].width <= 1000 && !before.artifacts[id].produced_by)]);
  const saved = info.outputPath("personal.badshop");
  await emptyCore.call("session.save_as", { path: saved });
  await emptyCore.call("session.new", { discard_unsaved: true });
  await emptyCore.call("session.open", { path: saved });
  const reopened = await emptyCore.call("session.get") as Session;
  expect(reopened.steps).toEqual(created.steps);
  await page.screenshot({ path: info.outputPath("personal-ideas.png") });
});
