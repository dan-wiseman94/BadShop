import { test, expect, root } from "./fixtures";
import path from "node:path";
import type { Session, Step } from "../src/types";
const connect = async (
  page: import("@playwright/test").Page,
  core: { port: number; token: string },
) => {
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    localStorage.setItem("badshop.theme", "dark");
  });
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
};

test("coordinate picking follows the chosen form image instead of the viewer selection", async ({
  page,
  core,
}) => {
  const other = (await core.call("artifacts.import", {
    path: path.join(root, "core/tests/fixtures/trump.png"),
  })) as { working: { id: string; label: string } };
  await connect(page, core);
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("cutout");
  await page.getByRole("button", { name: /^cutout crop/ }).click();
  const dialog = page.getByRole("dialog", { name: "Run a tool" });
  await dialog
    .getByLabel("Image", { exact: false })
    .selectOption(other.working.id);
  await dialog.getByRole("button", { name: "Pick on image" }).click();
  await expect(page.locator(".canvas-image")).toHaveAttribute(
    "alt",
    other.working.label,
  );
  await expect(page.locator(".pick-hint")).toContainText(other.working.label);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toBeVisible();
});

test("replay refreshes a selected step input while preserving an active parameter draft", async ({
  page,
  core,
}) => {
  const session = (await core.call("session.get")) as Session;
  const image = Object.values(session.artifacts).find((artifact) =>
    artifact.label.includes("work"),
  )!.id;
  const first = (await core.call("tools.run", {
    tool: "deepfry",
    params: { image, level: 1, seed: 1 },
  })) as Step;
  const second = (await core.call("tools.run", {
    tool: "deepfry",
    params: { image: first.outputs[0], level: 1, seed: 2 },
  })) as Step;
  await connect(page, core);
  await page.locator(".step").nth(1).click();
  const detail = page.locator(".step-detail");
  await detail.getByLabel("Seed", { exact: false }).fill("99");
  await core.call("steps.edit", {
    step_id: first.id,
    params: { ...first.params, seed: 22 },
  });
  let remapped = "";
  await expect
    .poll(async () => {
      const current = (await core.call("session.get")) as Session;
      const step = current.steps.find((s) => s.id === second.id)!;
      remapped = String(step.params.image);
      return step.status === "done" && remapped !== first.outputs[0];
    })
    .toBe(true);
  await expect(detail.getByLabel("Image", { exact: false })).toHaveValue(
    remapped,
  );
  await expect(detail.getByLabel("Seed", { exact: false })).toHaveValue("99");
  await detail.getByRole("button", { name: "Apply & replay" }).click();
  await expect
    .poll(async () => {
      const current = (await core.call("session.get")) as Session;
      return current.steps.find((s) => s.id === second.id)?.params;
    })
    .toMatchObject({ image: remapped, seed: 99 });
});

test("a setup error is visible inside the settings dialog and has no unrelated chat retry", async ({
  page,
  core,
}) => {
  await connect(page, core);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Add provider", exact: true }).click();
  await page.getByLabel("Provider type").selectOption("local");
  await page.getByLabel("Profile name").fill("Invalid endpoint");
  await page.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await page
    .getByLabel("API base URL", { exact: false })
    .fill("http://localhost:11434?invalid=1");
  await page.getByRole("button", { name: "Save provider" }).click();
  const alert = page.getByRole("dialog").getByRole("alert");
  await expect(alert).toContainText("invalid provider profile");
  await expect(alert.getByRole("button", { name: "Retry turn" })).toHaveCount(
    0,
  );
});

test("repeatable drawing sections have visible labels and accessible coordinate controls", async ({
  page,
  core,
}) => {
  await connect(page, core);
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("draw");
  await page
    .locator(".tool-option")
    .filter({ has: page.locator("strong", { hasText: /^draw$/ }) })
    .click();
  const dialog = page.getByRole("dialog");
  for (const name of ["Circle", "Arrow", "Line", "Rect"])
    await expect(
      dialog.locator("legend").filter({ hasText: new RegExp(`^${name}$`) }),
    ).toBeVisible();
  await expect(dialog.getByLabel("Color swatch")).toHaveValue("#ff0000");
  const arrows = dialog.getByRole("group", { name: "Arrow", exact: true });
  await arrows.getByRole("button", { name: "Add item", exact: true }).click();
  await expect(arrows.getByLabel("arrow 1 X1", { exact: true })).toBeVisible();
  await arrows
    .getByRole("button", { name: "Remove item", exact: true })
    .click();
  await expect(arrows.getByLabel("arrow 1 X1", { exact: true })).toHaveCount(0);
});

test("the empty chat remains at the top at the minimum desktop size", async ({
  page,
  core,
}) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await connect(page, core);
  await expect
    .poll(() =>
      page.locator(".chat-history").evaluate((node) => node.scrollTop),
    )
    .toBe(0);
  const visible = await page
    .locator(".chat-welcome h1")
    .evaluate(
      (node) =>
        node.getBoundingClientRect().top >=
        node.closest(".chat-history")!.getBoundingClientRect().top,
    );
  expect(visible).toBe(true);
});

test("first run with saved profiles explicitly selects a provider before continuing", async ({
  page,
  core,
}) => {
  const profile = (await core.call("providers.save", {
    profile: {
      kind: "local",
      label: "Saved local vision",
      model: "ollama_chat/llava",
    },
  })) as { id: string };
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await expect(
    welcome.getByRole("button", { name: "Use Saved local vision" }),
  ).toBeVisible();
  await expect(
    welcome.getByRole("button", { name: "Start making badshops" }),
  ).toHaveCount(0);
  await welcome.getByRole("button", { name: "Use Saved local vision" }).click();
  await expect(
    welcome.getByRole("button", { name: "Start making badshops" }),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        ((await core.call("session.get")) as Session).provider_profile_id,
    )
    .toBe(profile.id);
  await welcome.getByRole("button", { name: "Start making badshops" }).click();
  await expect(
    page.getByRole("combobox", { name: "Active provider" }),
  ).toHaveValue(profile.id);
});
