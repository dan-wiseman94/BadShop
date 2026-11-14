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

test("default workbench follows the desktop until an explicit skin is saved", async ({ page, emptyCore }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: test.info().outputPath("default-dark-empty.png") });
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({ path: test.info().outputPath("default-light-empty.png") });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await page.locator(".theme-card").filter({ has: page.getByText("Dark", { exact: true }) }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  // Returning to Follow system uses the current desktop, not the previous skin.
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await page.getByRole("combobox", { name: "Theme", exact: true }).selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

for (const [theme, name] of [
  ["dark", "Dark"],
  ["light", "Light"],
  ["classic", "Classic Desktop"],
  ["xp", "XP"],
  ["terminal", "Terminal"],
  ["geocities", "GeoCities"],
  ["y2k", "Y2K"],
  ["paper", "Paper"],
  ["arcade", "Arcade"],
]) test(`${theme} interface skin persists and keeps artwork pixels unchanged`, async ({
  page,
  core,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    // Do not set the theme here: reload must use the preference saved by the UI.
  });
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const before = (await core.call("session.get")) as Session;
  const artwork = page.locator(".canvas-image");
  await expect(artwork).toBeVisible();
  const source = await artwork.getAttribute("src");
  const artifactId = Object.keys(before.artifacts)[0];
  const bytes = await core.call("artifacts.get", { id: artifactId });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await page.locator(".theme-card").filter({ has: page.getByText(name, { exact: true }) }).click();
  await expect(page.getByRole("combobox", { name: "Theme", exact: true })).toHaveValue(theme);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await page.evaluate(() => document.fonts.ready);
  await page.locator(".theme-grid").screenshot({ path: test.info().outputPath(`theme-${theme}-picker.png`) });
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  await expect(page.getByRole("button", { name: "Settings", exact: true }).locator("svg")).toHaveAttribute("data-icon-skin", theme);
  await expect(page.getByRole("button", { name: "Replay all steps", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Run a tool", exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-tools.png`) });
  // Exercise real form controls and keyboard focus, then cancel without making a step.
  await page.getByLabel("Search tools").fill("cutout");
  await page.getByRole("button", { name: /^cutout crop/ }).click();
  const noAI = page.getByRole("dialog", { name: "Run a tool" }).getByLabel("No Ai", { exact: false });
  await noAI.check();
  await noAI.press("Space");
  await expect(noAI).not.toBeChecked();
  await expect(noAI).toBeFocused();
  await expect(noAI).not.toHaveCSS("outline-style", "none");
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-form.png`) });
  await page.getByRole("button", { name: "Close tools", exact: true }).click();
  expect(((await core.call("session.get")) as Session).steps).toEqual(before.steps);
  await page.getByRole("button", { name: "Images & directions", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Images & directions", exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-studio.png`) });
  await page.getByRole("button", { name: "Close images and directions", exact: true }).click();
  await expect(artwork).toHaveAttribute("src", source!);
  // A theme must not tint, blur or fade the image through any ancestor.
  const effects = await artwork.evaluate(image => {
    const result = [];
    for (let node: Element | null = image; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.filter !== "none" || style.opacity !== "1" || style.mixBlendMode !== "normal")
        result.push({ node: node.className, filter: style.filter, opacity: style.opacity, blend: style.mixBlendMode });
    }
    return result;
  });
  expect(effects).toEqual([]);
  await expect(artwork).toHaveCSS("image-rendering", "pixelated");
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-workbench.png`) });
  await page.getByRole("button", { name: "Quick ideas", exact: true }).click();
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-quick.png`) });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  // Both selectors use the same saved preference.
  await page.getByRole("combobox", { name: "Theme", exact: true }).selectOption("dark");
  await expect(page.getByRole("button", { name: "Close settings", exact: true }).locator("svg")).toHaveAttribute("data-icon-skin", "dark");
  await page.getByRole("combobox", { name: "Theme", exact: true }).selectOption(theme);
  await page.getByRole("combobox", { name: "Motion", exact: true }).selectOption("reduced");
  await page.getByRole("combobox", { name: "Text size", exact: true }).selectOption("130");
  await page.getByRole("combobox", { name: "Interface density", exact: true }).selectOption("compact");
  await page.setViewportSize({ width: 1100, height: 820 });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await expect(page.locator("html")).toHaveCSS("font-size", "16.9px");
  await expect(page.getByRole("button", { name: "Settings", exact: true }).locator("svg")).toHaveAttribute("data-icon-skin", theme);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Theme", exact: true })).toHaveValue(theme);
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-scaled-settings.png`) });
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  expect(await core.call("artifacts.get", { id: artifactId })).toEqual(bytes);
  expect(((await core.call("session.get")) as Session).artifacts).toEqual(
    before.artifacts,
  );
  // Selected list text must stay legible when the pointer remains over the row.
  await page.getByRole("button", { name: "History", exact: true }).click();
  await core.call("tools.run", { tool: "info", params: { image: artifactId } });
  const step = page.locator(".step").last();
  await step.click();
  await step.hover();
  const contrast = await step.evaluate(row => {
    const luminance = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    // Canvas normalizes CSS color-mix()/color(srgb ...) to RGB for the calculation.
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d")!;
    const normalize = (color: string) => {
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, 1, 1);
      return `rgb(${Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3).join(",")})`;
    };
    const style = getComputedStyle(row);
    const foreground = luminance(normalize(style.color));
    const background = luminance(normalize(style.backgroundColor));
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
  expect(contrast, "Selected step text contrast on hover").toBeGreaterThanOrEqual(4.5);
  await page.screenshot({ path: test.info().outputPath(`theme-${theme}-selected-step.png`) });
});
