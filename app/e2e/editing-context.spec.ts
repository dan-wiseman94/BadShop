import { readFile } from "node:fs/promises";
import { test, expect, type Core } from "./fixtures";
import type { Page } from "@playwright/test";
import type { Session, Step } from "../src/types";

async function prepare(page: Page, core: Core) {
  const session = await core.call("session.get") as Session;
  const image = Object.values(session.artifacts).find(artifact => artifact.label.includes("work"))!.id;
  const first = await core.call("tools.run", { tool: "deepfry", params: { image, seed: 7, level: 1 } }) as Step;
  await core.call("tools.run", { tool: "deepfry", params: { image: first.outputs[0], seed: 9, level: 2 } });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.locator(".step").first().click();
  return first;
}

for (const before of [false, true]) test(`running a manual tool on an older selected step uses the ${before ? "Before" : "After"} image's pixels`, async ({ page, core }) => {
  const first = await prepare(page, core);
  if (before) await page.getByRole("button", { name: "Before", exact: true }).click();
  const source = before ? first.params.image : first.outputs[0];
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("deepfry");
  const dialog = page.getByRole("dialog", { name: "Run a tool" });
  await dialog.getByRole("button", { name: /^deepfry / }).click();
  await expect(dialog.getByLabel("Image", { exact: false })).toHaveValue(String(source));
  await dialog.getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(page.locator(".step")).toHaveCount(3);
  await expect.poll(async () => (await core.call("session.get") as Session).steps.at(-1)?.status).toBe("done");
  const actual = (await core.call("session.get") as Session).steps.at(-1)!;
  expect(actual.status).toBe("done");
  expect(actual.params.image).toBe(source);
  const expected = await core.call("tools.run", { tool: "deepfry", params: { ...actual.params, image: source } }) as Step;
  expect(actual.outputs).toEqual(expected.outputs);
});

test("selecting a step output leaves Before and exports the selected bytes", async ({ page, core }) => {
  const first = await prepare(page, core);
  await page.getByRole("button", { name: "Before", exact: true }).click();
  await page.locator(".step-detail .provenance button").first().click();
  const artifact = await core.call("artifacts.get", { id: first.outputs[0] }) as { mime: string; data: string };
  await expect(page.locator(".canvas-image")).toHaveAttribute("src", `data:${artifact.mime};base64,${artifact.data}`);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Save image file", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Exported to ");
  const filename = (await page.getByRole("status").innerText()).replace("Exported to ", "").trim();
  expect(await readFile(filename)).toEqual(Buffer.from(artifact.data, "base64"));
});
