import path from "node:path";
import { readFile } from "node:fs/promises";
import { test, expect, root, startCore } from "./fixtures";
import type { LibraryEntry, Session } from "../src/types";

test("edited cast collections transfer to a fresh profile and removal keeps project pixels", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await page.getByText("Your cast of characters", { exact: true }).click();
  const cast = page.getByRole("region", { name: "Your cast", exact: true });
  await cast.getByLabel("Character name", { exact: true }).fill("Abe");
  await cast.getByLabel("Cast collection", { exact: true }).fill("Office");
  await cast.getByRole("button", { name: "Keep this picture in my cast" }).click();
  await expect(cast.getByRole("button", { name: "Use Abe", exact: true })).toBeVisible();
  const source = (await emptyCore.call("library.list") as LibraryEntry[])[0];
  await cast.getByLabel("Show cast collection").selectOption("Office");
  await cast.getByRole("button", { name: "Edit character", exact: true }).click();
  await cast.getByLabel("Character name", { exact: true }).fill("Captain Abe");
  await cast.getByLabel("Expression or role").fill("Triumphant");
  await cast.getByLabel("Cast collection", { exact: true }).fill("Heroes");
  await cast.getByRole("button", { name: "Update character" }).click();
  await expect(cast.getByRole("button", { name: "Use Captain Abe", exact: true })).toBeVisible();
  await cast.getByLabel("Character name", { exact: true }).fill("Office guest");
  await cast.getByLabel("Cast collection", { exact: true }).fill("Office");
  await cast.getByRole("button", { name: "Keep this picture in my cast" }).click();
  await expect(cast.getByRole("button", { name: "Use Office guest", exact: true })).toBeVisible();
  await expect(cast.getByLabel("Show cast collection")).toHaveValue("");
  await expect(cast.getByRole("button", { name: "Use Captain Abe", exact: true })).toBeVisible();
  await page.reload();
  await page.getByText("Your cast of characters", { exact: true }).click();
  await cast.getByLabel("Show cast collection").selectOption("Heroes");
  const pack = path.join(emptyCore.folder, "heroes.badpack");
  page.once("dialog", dialog => dialog.dismiss());
  await cast.getByRole("button", { name: "Export this cast collection" }).click();
  await expect(cast.getByRole("button", { name: "Export this cast collection" })).toBeEnabled();
  await expect(readFile(pack)).rejects.toThrow();
  page.once("dialog", dialog => dialog.accept(pack));
  await cast.getByRole("button", { name: "Export this cast collection" }).click();
  await expect(page.getByRole("status")).toContainText("Cast pack saved to");
  expect((await readFile(pack)).subarray(0, 2).toString()).toBe("PK");

  const recipient = await startCore(path.join(emptyCore.folder, "recipient"));
  try {
    await page.goto(`/?core_port=${recipient.port}&core_token=${recipient.token}`);
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    await page.getByText("Your cast of characters", { exact: true }).click();
    expect(await recipient.call("library.list")).toEqual([]);
    page.once("dialog", dialog => dialog.accept(pack));
    await cast.getByRole("button", { name: "Import a cast pack" }).click();
    await expect(cast.getByRole("button", { name: "Use Captain Abe", exact: true })).toBeVisible();
    const received = (await recipient.call("library.list") as LibraryEntry[])[0];
    expect(received.name).toBe("Captain Abe");
    expect(received.tags).toEqual(expect.arrayContaining(["cast", "expression:Triumphant", "collection:Heroes"]));
    await cast.getByRole("button", { name: "Use Captain Abe", exact: true }).click();
    await expect.poll(async () => Object.keys((await recipient.call("session.get") as Session).artifacts).length).toBeGreaterThan(0);
    const imported = await recipient.call("session.get") as Session;
    const original = await emptyCore.call("session.get") as Session;
    for (const id of Object.keys(imported.artifacts)) {
      expect(original.artifacts[id]).toBeDefined();
      expect(await recipient.call("artifacts.get", { id })).toEqual(await emptyCore.call("artifacts.get", { id }));
    }
    await cast.getByLabel("Show cast collection").selectOption("Heroes");
    await cast.getByRole("button", { name: "Remove character", exact: true }).click();
    await cast.getByRole("button", { name: "Keep character", exact: true }).click();
    expect(await recipient.call("library.list")).toHaveLength(1);
    await cast.getByRole("button", { name: "Remove character", exact: true }).click();
    await cast.getByRole("button", { name: "Confirm remove character" }).click();
    await expect.poll(() => recipient.call("library.list")).toEqual([]);
    expect((await recipient.call("session.get") as Session).artifacts).toEqual(imported.artifacts);
    const project = path.join(recipient.folder, "kept-pictures.badshop");
    page.once("dialog", dialog => dialog.accept(project));
    await page.getByRole("button", { name: "Save session", exact: true }).click();
    await expect.poll(async () => (await recipient.call("session.get") as Session).unsaved_changes).toBe(false);
    await recipient.call("session.open", { path: project });
    for (const id of Object.keys(imported.artifacts)) {
      expect(await recipient.call("artifacts.get", { id })).toEqual(await emptyCore.call("artifacts.get", { id }));
    }
    await page.reload();
    await page.getByText("Your cast of characters", { exact: true }).click();
    await expect(cast.getByRole("button", { name: "Export this cast collection" })).toBeDisabled();
    expect((await emptyCore.call("library.list") as LibraryEntry[]).map(entry => entry.id)).toContain(source.id);
  } finally {
    try { await page.goto("about:blank"); }
    finally { await recipient.close(); }
  }
});
