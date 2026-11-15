import path from "node:path";
import { test, expect, expectImageBytes, root } from "./fixtures";
import type { Session, Step } from "../src/types";

test("edits an overlapping recorded picture without leaving the final canvas", async ({ page, emptyCore: core }) => {
  const subject = await core.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/trump.png") }) as { working: { id: string } };
  const layout = await core.call("tools.run", { tool: "layout", params: {
    template: "comic", title: "Recorded selection", captions: ["First words", "Second words"],
  } }) as Step;
  const paste = await core.call("tools.run", { tool: "paste", params: {
    base: layout.outputs[0], piece: subject.working.id, at: [50, 140], width: 260.49,
  } }) as Step;
  const caption = await core.call("tools.run", { tool: "text", params: {
    image: paste.outputs[0], text: "On top", font: "bundled", at: [180, 210], size: 36,
  } }) as Step;
  const original = await core.call("artifacts.get", { id: caption.outputs[0] }) as { data: string };
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  const canvas = page.locator(".canvas-image");
  await expectImageBytes(canvas, original.data);

  await expect(page.getByRole("button", { name: "Select elements" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Edit Caption: On top", exact: true }).dblclick();
  await expect(page.getByRole("textbox", { name: "Exact caption" })).toBeFocused();
  await expectImageBytes(canvas, original.data);

  const elements = page.getByLabel("Elements in this image");
  await elements.focus();
  await elements.press("Home");
  await elements.press("ArrowDown");
  await elements.press("ArrowDown");
  await elements.press("ArrowDown");
  await expect(elements.locator("option:checked")).toHaveText("Picture: step 2");
  const details = page.locator(".step-detail");
  const placement = details.getByRole("group", { name: "Placement controls" });
  await placement.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await page.setViewportSize({ width: 820, height: 980 });
  const panes = page.getByRole("navigation", { name: "Workspace panels" });
  await panes.getByRole("button", { name: "Canvas", exact: true }).click();
  await expect(placement).toBeHidden();
  const piece = page.getByRole("button", { name: "Edit Picture: step 2", exact: true });
  await piece.scrollIntoViewIfNeeded();
  const pieceBounds = (await piece.boundingBox())!;
  const scale = (await canvas.boundingBox())!.width / 1000;
  const start = { x: pieceBounds.x + 12 * scale, y: pieceBounds.y + 24 * scale };
  const guide = page.locator(".canvas-placement-guide");
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 30 * scale, start.y + 20 * scale, { steps: 3 });
  await expect(guide).toBeVisible();
  await expectImageBytes(canvas, original.data);
  expect(((await core.call("session.get")) as Session).steps[1].params.at).toEqual([50, 140]);
  await page.mouse.up();
  await expect(guide).toHaveCount(0);

  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 45 * scale, start.y + 30 * scale, { steps: 3 });
  await expect(guide).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(guide).toHaveCount(0);
  await page.mouse.up();
  await panes.getByRole("button", { name: "Inspector", exact: true }).click();
  await expect(placement).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 960 });

  const previewFinal = details.getByLabel("Preview final result, including later steps", { exact: false });
  if (await previewFinal.isVisible()) await previewFinal.check();
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = details.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  const expected = (await preview.getAttribute("src"))!.split(",")[1];
  expect(expected).not.toBe(original.data);
  await expectImageBytes(canvas, original.data);
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => ((await core.call("session.get")) as Session).steps[1].params.at).toEqual([90, 160]);
  await expectImageBytes(canvas, expected);

  await elements.selectOption({ label: "Layout: Image 1" });
  const layoutEditor = page.getByRole("form", { name: "Edit this joke", exact: true });
  await expect(layoutEditor.getByRole("textbox", { name: "Caption Image 1", exact: true })).toHaveValue("First words");
  await expect(layoutEditor.getByRole("textbox", { name: "Headline", exact: true })).toHaveValue("Recorded selection");
  await elements.selectOption({ label: "Layout: Image 2" });
  await expect(layoutEditor.getByRole("textbox", { name: "Caption Image 2", exact: true })).toHaveValue("Second words");
  await page.getByRole("button", { name: "Edit Caption for Layout: Image 2", exact: true }).dblclick();
  await expect(layoutEditor.getByRole("textbox", { name: "Caption Image 2", exact: true })).toBeFocused();
  await page.locator(".image-surface").click({ position: { x: 6, y: 6 } });
  await expect(elements.locator("option:checked")).toHaveText("Choose an element");
  await expectImageBytes(canvas, expected);

  const project = path.join(core.folder, "selected-elements.badshop");
  await core.call("session.save_as", { path: project });
  await core.call("session.open", { path: project });
  const reopened = await core.call("session.get") as Session;
  expect(reopened.steps[1].params.at).toEqual([90, 160]);
  expect(reopened.steps[1].params).toMatchObject({ ...paste.params, at: [90, 160] });
  expect(reopened.steps[1].data!.element_bounds).toEqual(
    (paste.data!.element_bounds as number[]).map((edge, i) => edge + (i % 2 ? 20 : 40)),
  );
  expect((await core.call("artifacts.get", { id: reopened.steps[2].outputs[0] }) as { data: string }).data).toBe(expected);

  const crop = await core.call("tools.run", { tool: "transform", params: {
    image: reopened.steps[2].outputs[0], crop: [0, 0, 500, 400],
  } }) as Step;
  await page.reload();
  const cropBytes = await core.call("artifacts.get", { id: crop.outputs[0] }) as { data: string };
  await expectImageBytes(canvas, cropBytes.data);
  await expect(page.getByText("This image has no selectable recorded elements.", { exact: false })).toBeVisible();
  await expect(elements).toHaveCount(0);
});
