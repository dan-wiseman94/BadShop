import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, python, root } from "./fixtures";
import type { Session } from "../src/types";

test("saved materials page and search without dropping stored entries", async ({ page, emptyCore }) => {
  execFileSync(python, ["-c", `
import io, sys
from pathlib import Path
from PIL import Image
from badshop.session.session import Session
from badshop.session.library import AssetLibrary, AssetDetails
s = Session.new()
b = io.BytesIO()
Image.new('RGB', (8, 8), 'red').save(b, 'PNG')
image = s.import_image(b.getvalue(), 'shared bytes')
library = AssetLibrary(Path(sys.argv[1]) / 'data' / 'library')
for i in range(55):
    library.save(s, image.id, f'Character {i:03}', ['cast'], AssetDetails())
s.artifacts.close()
`, emptyCore.folder], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "core/src") } });
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    localStorage.setItem("badshop.workspace", "advanced");
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByText('Saved characters & materials', { exact: true }).click();
  const library = page.locator('details.material-library');
  await expect(library.locator('.artifact-list > button')).toHaveCount(50);
  await library.getByRole('button', { name: 'Next materials' }).click();
  await expect(library.locator('.artifact-list > button')).toHaveCount(5);
  await page.getByLabel('Find material', { exact: true }).fill('Character 000');
  await expect(library.locator('.artifact-list > button')).toHaveCount(1);
  await library.getByRole('button', { name: 'Character 000', exact: true }).click();
  const saved = await emptyCore.call('library.list') as unknown[];
  expect(saved).toHaveLength(55);
  const session = await emptyCore.call('session.get') as Session;
  expect(Object.values(session.artifacts)).toHaveLength(1);
  expect(session.messages.some(message => message.content.some(part => part.text?.includes('Character 000')))).toBe(true);
});

test("long conversation and materials remain accessible and survive portable save", async ({ page, emptyCore }) => {
  const filename = path.join(emptyCore.folder, "long.badshop");
  execFileSync(python, ["-c", `
import io, sys
from PIL import Image
from badshop.session.session import Session
from badshop.session.models import Part
from badshop.session.project import save
s = Session.new()
b = io.BytesIO()
Image.new('RGB', (8, 8), 'red').save(b, 'PNG')
for i in range(250):
    s.import_image(b.getvalue(), f'material-{i}')
    s.add_message('assistant', [Part(type='text', text=f'Message {i}: **retained content**')])
save(s, sys.argv[1])
`, filename], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "core/src") } });
  await emptyCore.call("session.open", { path: filename });
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    localStorage.setItem("badshop.workspace", "advanced");
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const history = page.getByLabel("Conversation history");
  await expect(history.getByText("Message 249:", { exact: false })).toBeVisible();
  expect(await history.locator("article").count()).toBeLessThan(40);
  await history.evaluate(node => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); });
  await expect(history.getByText("Message 0:", { exact: false })).toBeVisible();
  const materials = page.getByLabel("Project materials");
  const thumbs = materials.locator("button");
  await expect(thumbs.first()).toBeVisible();
  expect(await thumbs.count()).toBeLessThan(40);
  await thumbs.first().focus();
  await page.keyboard.press("End");
  await expect(materials.locator('[data-material-index="249"] button')).toBeFocused();
  await expect(materials.locator('[data-material-index="249"] button')).toBeInViewport();
  await page.keyboard.press("Home");
  await expect(materials.locator('[data-material-index="0"] button')).toBeFocused();
  const before = await emptyCore.call("session.get") as Session;
  await emptyCore.call("session.save_as", { path: filename });
  const after = await emptyCore.call("session.open", { path: filename }) as Session;
  expect(after.messages).toEqual(before.messages);
  expect(after.artifacts).toEqual(before.artifacts);
  expect(after.messages).toHaveLength(250);
  expect(Object.keys(after.artifacts)).toHaveLength(250);
  expect(new Set(Object.values(after.artifacts).map(meta => meta.blob_id)).size).toBe(1);
});

test("long history keeps bounded rows and keyboard access to every step", async ({ page, core }) => {
  test.setTimeout(120_000);
  const session = await core.call("session.get") as { artifacts: Record<string, unknown> };
  const image = Object.keys(session.artifacts)[0];
  for (let index = 0; index < 250; index++) {
    await core.call("tools.run", { tool: "info", params: { image } });
  }
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    localStorage.setItem("badshop.workspace", "advanced");
  });
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const rows = page.locator(".step-list .step");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeLessThan(40);
  // Scrolling without selecting must not remove the list from the Tab order.
  await page.getByRole("button", { name: "Replay all steps", exact: true }).focus();
  await page.locator(".step-list").evaluate(node => { node.scrollTop = node.scrollHeight; });
  await expect(page.getByRole("button", { name: "Step 250 of 250: info, done", exact: true })).toBeInViewport();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Step 1 of 250: info, done", exact: true })).toBeFocused();
  await page.keyboard.press("End");
  const last = page.getByRole("button", { name: "Step 250 of 250: info, done", exact: true });
  await expect(last).toBeFocused();
  await expect(last).toBeInViewport();
  await expect(last).toHaveAttribute("aria-pressed", "true");
  expect(await rows.count()).toBeLessThan(40);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByRole("button", { name: "Step 249 of 250: info, done", exact: true })).toBeFocused();
  await page.keyboard.press("Home");
  const first = page.getByRole("button", { name: "Step 1 of 250: info, done", exact: true });
  await expect(first).toBeFocused();
  await expect(first).toBeInViewport();
  expect(await rows.count()).toBeLessThan(40);
  const after = await core.call("session.get") as { steps: unknown[] };
  expect(after.steps).toHaveLength(250);
});
