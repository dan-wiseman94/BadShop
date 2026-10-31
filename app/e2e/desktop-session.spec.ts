import { test, expect, root, type Core } from "./fixtures";
import type { Page } from "@playwright/test";
import type { Session } from "../src/types";
import { mkdir, stat } from "node:fs/promises";
import path from "node:path";

async function connect(page: Page, core: Core) {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

async function newSession(page: Page, name: string) {
  await page.locator(".session-name").click();
  await page.getByRole("button", { name: "New session", exact: true }).click();
  await page.getByLabel("Session name", { exact: true }).fill(name);
  await page
    .getByRole("button", { name: "Create session", exact: true })
    .click();
  return page.getByRole("dialog", { name: /Save changes to/ });
}

test("session replacement respects Cancel, file picker cancellation, and Save", async ({
  page,
  core,
}) => {
  await connect(page, core);
  const initial = (await core.call("session.get")) as Session;
  expect(initial.unsaved_changes).toBe(true);
  let dialog = await newSession(page, "A fresh project");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(((await core.call("session.get")) as Session).id).toBe(initial.id);

  dialog = await newSession(page, "A fresh project");
  page.once("dialog", (picker) => picker.dismiss());
  await dialog
    .getByRole("button", { name: "Save & continue", exact: true })
    .click();
  await expect(
    dialog.getByRole("button", { name: "Save & continue", exact: true }),
  ).toBeEnabled();
  expect(((await core.call("session.get")) as Session).id).toBe(initial.id);
  const project = path.join(core.folder, "preserved.badshop");
  page.once("dialog", (picker) => picker.accept(project));
  await dialog
    .getByRole("button", { name: "Save & continue", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".session-label")).toHaveText("A fresh project");
  const fresh = (await core.call("session.get")) as Session;
  expect(fresh.id).not.toBe(initial.id);
  expect(fresh.unsaved_changes).toBe(false);
  expect((await stat(project)).size).toBeGreaterThan(0);
  await core.call("session.open", { path: project });
  const restored = (await core.call("session.get")) as Session;
  expect(Object.keys(restored.artifacts)).toEqual(
    Object.keys(initial.artifacts),
  );
});

test("failed saves stay visible and preserve the document until an explicit discard", async ({
  page,
  core,
}) => {
  await connect(page, core);
  const initial = (await core.call("session.get")) as Session;
  const dialog = await newSession(page, "After discard");
  // A directory is an invalid destination on every supported platform.
  const directory = path.join(core.folder, "directory.badshop");
  await mkdir(directory);
  page.once("dialog", (picker) => picker.accept(directory));
  await dialog
    .getByRole("button", { name: "Save & continue", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(((await core.call("session.get")) as Session).id).toBe(initial.id);
  await dialog
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(page.locator(".session-label")).toHaveText("After discard");
});

test("a stale discard decision cannot erase a newer edit", async ({
  page,
  core,
}) => {
  await connect(page, core);
  const initial = (await core.call("session.get")) as Session;
  const dialog = await newSession(page, "Replacement");
  await core.call("session.set_approval_mode", { mode: "ask_all" });
  await dialog
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  const current = (await core.call("session.get")) as Session;
  expect(current.id).toBe(initial.id);
  expect(current.approval_mode).toBe("ask_all");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByLabel("Approval mode", { exact: true })).toHaveValue(
    "ask_all",
  );
});

test("all desktop panes fit after resizing, preserve preferences, and support the keyboard", async ({
  page,
  core,
}) => {
  await connect(page, core);
  const separator = page.getByRole("separator", { name: "Resize chat pane" });
  await separator.focus();
  const before = Number(await separator.getAttribute("aria-valuenow"));
  await page.keyboard.press("ArrowRight");
  await expect(separator).toHaveAttribute("aria-valuenow", String(before + 16));
  const saved = await page.evaluate(() =>
    localStorage.getItem("badshop.panes"),
  );
  await page.setViewportSize({ width: 900, height: 600 });
  await expect
    .poll(async () =>
      page.locator(".pane").evaluateAll((nodes) =>
        nodes.every((node) => {
          const bounds = node.getBoundingClientRect();
          return (
            bounds.left >= 0 &&
            bounds.right <= innerWidth &&
            bounds.bottom <= innerHeight
          );
        }),
      ),
    )
    .toBe(true);
  expect(await page.evaluate(() => localStorage.getItem("badshop.panes"))).toBe(
    saved,
  );
  await page.setViewportSize({ width: 1440, height: 960 });
  await expect(separator).toHaveAttribute("aria-valuenow", String(before + 16));
  await page.reload();
  await expect(separator).toHaveAttribute("aria-valuenow", String(before + 16));
  await separator.dblclick();
  await expect(separator).toHaveAttribute("aria-valuenow", "318");
});

test("reopening an earlier save of the same session clears discarded image selections and attachments", async ({
  page,
  core,
}) => {
  await connect(page, core);
  const initial = (await core.call("session.get")) as Session;
  const project = path.join(core.folder, "same-session.badshop");
  await page.locator(".session-name").click();
  page.once("dialog", (picker) => picker.accept(project));
  await page.getByRole("button", { name: "Save session", exact: true }).click();
  await expect
    .poll(
      async () => ((await core.call("session.get")) as Session).unsaved_changes,
    )
    .toBe(false);
  await page
    .getByLabel("Import image files", { exact: true })
    .setInputFiles(path.join(root, "core/tests/fixtures/trump.png"));
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await expect(page.locator(".canvas-image")).toHaveAttribute("alt", /trump/);
  await page
    .getByLabel("Message your agent")
    .fill("Keep this draft until I discard.");
  await page.locator(".session-name").click();
  page.once("dialog", (picker) => picker.dismiss());
  await page.getByRole("button", { name: /^Open session/ }).click();
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await expect(page.getByLabel("Message your agent")).toHaveValue(
    "Keep this draft until I discard.",
  );
  await page.locator(".session-name").click();
  page.once("dialog", (picker) => picker.accept(project));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await page
    .getByRole("dialog", { name: /Save changes to/ })
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await expect(page.locator(".canvas-image")).toHaveAttribute("alt", /trump/);
  await page.locator(".session-name").click();
  page.once("dialog", (picker) => picker.accept(project));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await page
    .getByRole("dialog", { name: /Save changes to/ })
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect
    .poll(async () =>
      Object.keys(((await core.call("session.get")) as Session).artifacts),
    )
    .toEqual(Object.keys(initial.artifacts));
  await expect(page.locator(".attachments img")).toHaveCount(0);
  await expect(page.getByLabel("Message your agent")).toHaveValue("");
  await expect(page.locator(".canvas-image")).toHaveAttribute("alt", /lincoln/);
});
