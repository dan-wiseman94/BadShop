import path from "node:path";
import { test, expect, expectImageBytes, root } from "./fixtures";
import type { Session, Step } from "../src/types";

test("edits an overlapping recorded picture without leaving the final canvas", async ({ page, emptyCore: core }) => {
  const subject = await core.call("artifacts.import", { path: path.join(root, "core/tests/fixtures/trump.png") }) as { working: { id: string } };
  const layout = await core.call("tools.run", { tool: "layout", params: {
    template: "comic", title: "Recorded selection", captions: ["First words", "Second words"],
  } }) as Step;
  const paste = await core.call("tools.run", { tool: "paste", params: {
    base: layout.outputs[0], piece: subject.working.id, at: [50, 140], width: 260,
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
  const placementBox = (await placement.boundingBox())!;
  await page.mouse.move(placementBox.x + 35, placementBox.y + 40);
  await page.mouse.down();
  await page.mouse.move(placementBox.x + 60, placementBox.y + 60);
  await page.keyboard.press("Escape");
  await page.mouse.up();

  const previewFinal = details.getByLabel("Preview final result, including later steps", { exact: false });
  if (await previewFinal.isVisible()) await previewFinal.check();
  await details.getByRole("button", { name: "Preview changes", exact: true }).click();
  const preview = details.getByAltText("Uncommitted preview 1");
  await expect(preview).toBeVisible();
  const expected = (await preview.getAttribute("src"))!.split(",")[1];
  expect(expected).not.toBe(original.data);
  await expectImageBytes(canvas, original.data);
  await details.getByRole("button", { name: "Apply & replay" }).click();
  await expect.poll(async () => ((await core.call("session.get")) as Session).steps[1].params.at).toEqual([60, 140]);
  await expectImageBytes(canvas, expected);

  await elements.selectOption({ label: "Layout: Image 1" });
  await expect(details.getByRole("textbox", { name: "Caption", exact: true })).toHaveValue("First words");
  await expect(details.getByRole("textbox", { name: "Headline", exact: true })).toHaveValue("Recorded selection");
  await elements.selectOption({ label: "Layout: Image 2" });
  await expect(details.getByRole("textbox", { name: "Caption", exact: true })).toHaveValue("Second words");
  await page.getByRole("button", { name: "Edit Caption for Layout: Image 2", exact: true }).dblclick();
  await expect(details.getByRole("textbox", { name: "Caption", exact: true })).toBeFocused();
  await page.locator(".image-surface").click({ position: { x: 6, y: 6 } });
  await expect(elements.locator("option:checked")).toHaveText("Choose an element");
  await expectImageBytes(canvas, expected);

  const project = path.join(core.folder, "selected-elements.badshop");
  await core.call("session.save_as", { path: project });
  await core.call("session.open", { path: project });
  const reopened = await core.call("session.get") as Session;
  expect(reopened.steps[1].params.at).toEqual([60, 140]);
  expect((reopened.steps[1].data!.element_bounds as number[]).slice(0, 2)).toEqual([60, 140]);
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
