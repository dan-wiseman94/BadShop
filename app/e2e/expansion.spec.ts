import { test, expect, root } from "./fixtures";
import { execFileSync } from "node:child_process";
import path from "node:path";
import type { Session } from "../src/types";

test("the idea mixer uses available formats and adds an unsent brief without losing a draft", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("Keep the red hat.");
  const before = (await core.call("session.get")) as Session;
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await expect(
    page.getByRole("option", { name: "Cleveland Museum of Art", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("option", { name: "Wellcome Collection", exact: true }),
  ).toBeEnabled();
  await page.getByText("Collection availability", { exact: true }).click();
  await expect(page.getByText("No key needed", { exact: true })).toHaveCount(7);
  await page.getByRole("button", { name: "Idea mixer", exact: true }).click();
  await page
    .getByLabel("Idea subject", { exact: true })
    .fill("my extremely tired cat");
  await page
    .getByLabel("Lock format", { exact: true })
    .selectOption("product-box");
  await page.getByLabel("Lock joke", { exact: true }).selectOption("product");
  await page.getByLabel("Lock setting", { exact: true }).selectOption("shop");
  await page.getByLabel("Lock era", { exact: true }).selectOption("midcentury");
  await page
    .getByRole("button", { name: "Mix six ideas", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Add brief to chat" }),
  ).toHaveCount(1);
  await page.screenshot({ path: "/tmp/badshop-idea-mixer.png" });
  await page.getByRole("button", { name: "Add brief to chat" }).click();
  await expect(
    page.getByRole("dialog", { name: "Images & directions" }),
  ).not.toBeVisible();
  const draft = page.getByRole("textbox", { name: "Message your agent" });
  await expect(draft).toHaveValue(
    /Keep the red hat\.[\s\S]*my extremely tired cat[\s\S]*layout template "product-box"/,
  );
  const after = (await core.call("session.get")) as Session;
  expect(after.messages).toEqual(before.messages);
  expect(after.steps).toEqual(before.steps);
  expect(after.turn_running).toBe(false);
});

test("selected sprite cells preserve grid geometry and survive saving a project", async ({
  page,
  core,
}) => {
  const sourcePath = path.join(core.folder, "sprite-grid.png");
  execFileSync(path.join(root, "core/.venv/bin/python"), [
    "-c",
    "from PIL import Image; import sys; im=Image.new('RGBA',(13,11),(0,0,0,0)); im.paste((255,0,0,255),(1,1,3,5)); im.paste((0,0,255,255),(9,6,11,10)); im.save(sys.argv[1])",
    sourcePath,
  ]);
  const imported = (await core.call("artifacts.import", {
    path: sourcePath,
  })) as { working: { id: string } };
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Images & directions", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Sprite sheets", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Sprite sheet image", exact: true })
    .selectOption(imported.working.id);
  await page.getByLabel("Columns", { exact: true }).fill("3");
  await page.getByLabel("Left margin", { exact: true }).fill("1");
  await page.getByLabel("Top margin", { exact: true }).fill("1");
  await page.getByLabel("Right margin", { exact: true }).fill("2");
  await page.getByLabel("Bottom margin", { exact: true }).fill("1");
  await page.getByLabel("Horizontal gap", { exact: true }).fill("2");
  await page.getByLabel("Vertical gap", { exact: true }).fill("1");
  await page
    .getByRole("checkbox", { name: "Cell 0, row 0, column 0", exact: true })
    .click();
  await page
    .getByRole("checkbox", { name: "Cell 5, row 1, column 2", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Extract selected and attach", exact: true })
    .click();
  await expect(
    page.getByText("2 cells extracted and attached to chat.", { exact: true }),
  ).toBeVisible();
  const saved = (await core.call("session.get")) as Session;
  const step = saved.steps.at(-1)!;
  expect(step.tool).toBe("slice_sheet");
  expect(step.params.cells).toEqual([0, 5]);
  expect(step.data?.cells).toEqual([
    { index: 0, row: 0, column: 0, box: [1, 1, 3, 5], width: 2, height: 4 },
    { index: 5, row: 1, column: 2, box: [9, 6, 11, 10], width: 2, height: 4 },
  ]);
  for (const id of step.outputs)
    expect(saved.artifacts[id]).toMatchObject({ width: 2, height: 4 });
  const project = path.join(core.folder, "sprites.badshop");
  await core.call("session.save_as", { path: project });
  await core.call("session.new", { name: "Temporary" });
  await core.call("session.open", { path: project });
  expect(
    ((await core.call("session.get")) as Session).steps.at(-1)?.outputs,
  ).toEqual(step.outputs);
});
