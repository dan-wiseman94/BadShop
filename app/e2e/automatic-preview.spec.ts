import { writeFile } from "node:fs/promises";
import { test, expect, expectImageBytes } from "./fixtures";
import type { Session, Step } from "../src/types";

test("automatic preview keeps only the latest draft while an earlier render is in flight", async ({ page, core }, info) => {
  const initial = await core.call("session.get") as Session;
  const image = Object.values(initial.artifacts).find(artifact => artifact.label.includes("work"))!.id;
  const step = await core.call("tools.run", { tool: "deepfry", params: { image, level: 2, seed: 1 } }) as Step;
  const before = await core.call("session.get") as Session;
  const requests: number[] = [];
  const started = new Map<number, number>();
  const durations: number[] = [];
  let holdSeed = 17;
  let heldId: number;
  let releaseHeld: (() => void) | undefined;
  await page.routeWebSocket(`ws://127.0.0.1:${core.port}/`, client => {
    const server = client.connectToServer();
    client.onMessage(frame => {
      const message = JSON.parse(String(frame));
      if (message.method === "steps.preview") {
        requests.push(message.params.params.seed);
        started.set(message.id, performance.now());
        if (message.params.params.seed === holdSeed) heldId = message.id;
      }
      server.send(frame);
    });
    server.onMessage(frame => {
      const id = typeof frame === "string" ? JSON.parse(frame).id as number : undefined;
      const submittedAt = id === undefined ? undefined : started.get(id);
      if (submittedAt !== undefined) durations.push(performance.now() - submittedAt);
      if (id !== undefined && id === heldId && !releaseHeld) releaseHeld = () => client.send(frame);
      else client.send(frame);
    });
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await page.locator(".step").first().click();
  const inspector = page.locator(".step-detail");
  const seed = inspector.getByLabel("Seed", { exact: false });
  const preview = inspector.getByAltText("Uncommitted preview 1");
  await inspector.getByText("Advanced controls", { exact: true }).click();
  await expect(inspector.getByLabel("Automatic preview")).toBeChecked();
  await seed.fill("17");
  await expect.poll(() => releaseHeld !== undefined).toBe(true);
  await expect(inspector.getByRole("button", { name: "Apply & replay" })).toBeDisabled();
  await seed.fill("18");
  await seed.fill("19");
  expect(requests).toEqual([17]);
  releaseHeld!();
  await expect.poll(() => requests).toEqual([17, 19]);
  const [expected] = await core.call("steps.preview", {
    step_id: step.id, params: { ...step.params, seed: 19 }, final_result: true, expected_revision: before.document_revision,
  }) as string[];
  await expectImageBytes(preview, expected);
  const after = await core.call("session.get") as Session;
  expect(after.document_revision).toBe(before.document_revision);
  expect(after.steps).toEqual(before.steps);
  expect(after.artifacts).toEqual(before.artifacts);

  await seed.fill("20");
  await expect(preview).toHaveCount(0);
  await seed.fill("19");
  await expectImageBytes(preview, expected);
  await inspector.getByRole("button", { name: "Cancel changes" }).click();
  await expect(preview).toHaveCount(0);
  await expect(seed).toHaveValue("1");

  holdSeed = 21;
  releaseHeld = undefined;
  await seed.fill("21");
  await expect.poll(() => releaseHeld !== undefined).toBe(true);
  await inspector.getByRole("button", { name: "Cancel changes" }).click();
  releaseHeld!();
  await expect(inspector.getByRole("button", { name: "Apply & replay" })).toBeEnabled();
  await expect(preview).toHaveCount(0);
  await expect(seed).toHaveValue("1");
  expect(requests).toEqual([17, 19, 19, 21]);

  const timings = info.outputPath("local-preview-timings.json");
  await writeFile(timings, JSON.stringify({ first_preview_ms: durations[0], warm_preview_ms: durations[1] }));
  await info.attach("local-preview-timings", { path: timings, contentType: "application/json" });
});
