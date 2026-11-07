import { beforeEach, expect, it } from "vitest";
import { applyCoreEvent, queries } from "../src/data";
import { useUI } from "../src/store";
beforeEach(() => {
  useUI.getState().set({ status: "starting", error: null, errorAction: null });
  queries.setQueryData(["session.get"], {
    messages: [],
    steps: [],
    artifacts: {},
    pending_approvals: [],
  });
});
it("clears a stale provider retry action when a generic core warning arrives", () => {
  useUI.getState().set({ error: "Rate limit", errorAction: "retry-turn" });
  applyCoreEvent({
    method: "core.log",
    params: { level: "warning", message: "Asset download failed" },
  });
  expect(useUI.getState()).toMatchObject({
    error: "Asset download failed",
    errorAction: null,
  });
});
