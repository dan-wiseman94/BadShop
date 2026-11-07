import { test, expect } from "./fixtures";
import type { Session, Step } from "../src/types";

test("invalid approval edits keep the original proposal available to approve", async ({ page, core }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Message your agent" }).fill("Deep fry Lincoln.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Your call", { exact: true })).toBeVisible();

  const waiting = await core.call("session.get") as Session;
  const proposal = waiting.steps[0];
  const later = await core.call("tools.run", {
    tool: "filter", params: { image: proposal.params.image, names: ["sepia"] },
  }) as Step;
  const timeline = page.getByRole("region", { name: "Steps timeline" });
  await timeline.getByRole("button").filter({ hasText: "deepfry" }).click();
  await timeline.getByRole("combobox", { name: /^Image/ }).selectOption(later.outputs[0]);
  await timeline.getByRole("button", { name: "Approve with changes" }).click();
  await expect(page.getByRole("alert")).toContainText("makes it later");
  const unchanged = await core.call("session.get") as Session;
  expect(unchanged.pending_approvals).toEqual([proposal.id]);
  expect(unchanged.steps[0].params).toEqual(proposal.params);

  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("The pixels are thoroughly questionable.")).toBeVisible();
  const finished = await core.call("session.get") as Session;
  expect(finished.pending_approvals).toEqual([]);
  expect(finished.steps.map(step => step.status)).toEqual(["done", "done"]);
  expect(finished.steps[0].params).toEqual(proposal.params);
});
