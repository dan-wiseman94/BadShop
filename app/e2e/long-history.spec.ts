import { test, expect } from "./fixtures";

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
  await rows.first().focus();
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
