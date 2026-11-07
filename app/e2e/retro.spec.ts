import { test, expect } from "./fixtures";
import type { Session, Step } from "../src/types";
import path from "node:path";

test("retro catalog, persisted defaults, recipes and credited export use real core pixels", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Retro workbench", exact: true })
    .click();
  await expect(page.locator(".retro-pick")).toHaveCount(28);
  await page
    .getByRole("button", { name: "88 x 31 web button 1990s", exact: false })
    .click();
  await page
    .getByRole("button", { name: "Favorite 88 x 31 web button", exact: true })
    .click();
  await page.getByLabel("Title", { exact: true }).fill("HELLO");
  await page
    .getByRole("button", { name: "Build retro layout", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        ((await core.call("session.get")) as Session).steps.at(-1)?.status,
    )
    .toBe("done");
  const session = (await core.call("session.get")) as Session;
  const output = session.artifacts[session.steps.at(-1)!.outputs[0]];
  expect([output.width, output.height]).toEqual([88, 31]);
  expect(session.creative?.favorite_styles).toContain("badge");
  const recipe = await core.call("recipes.capture", {
    step_id: session.steps.at(-1)!.id,
  });
  await core.call("recipes.save", { recipe });
  const saved = path.join(core.folder, "retro.badshop");
  await core.call("session.save_as", { path: saved });
  await core.call("session.open", { path: saved });
  const reopened = (await core.call("session.get")) as Session;
  expect(reopened.creative?.style).toBe("badge");
  expect(reopened.recipes).toHaveLength(1);
  await page.screenshot({ path: test.info().outputPath("retro-catalog.png") });
  const credits = (await core.call("credits.export", {
    artifact_id: output.id,
  })) as { path: string; credits: string };
  expect(credits.credits).toContain(".credits.json");
  await core.call("settings.set", { values: { no_remote: true } });
  const offline = (await core.call("tools.run", {
    tool: "collection_items",
    params: { kind: "lospec", identifier: "pico-8" },
  })) as Step;
  expect(offline.status).toBe("error");
  expect(offline.error?.message).toContain("disabled");
});

test("every interface skin persists and keeps artwork pixels unchanged", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const before = (await core.call("session.get")) as Session;
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  for (const theme of [
    "classic",
    "terminal",
    "geocities",
    "y2k",
    "paper",
    "arcade",
  ]) {
    await page.getByLabel("Theme", { exact: true }).selectOption(theme);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.screenshot({
      path: test.info().outputPath(`theme-${theme}.png`),
    });
  }
  await page.getByLabel("Motion", { exact: true }).selectOption("reduced");
  await page.getByLabel("Text size", { exact: true }).selectOption("130");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "arcade");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  expect(((await core.call("session.get")) as Session).artifacts).toEqual(
    before.artifacts,
  );
});
