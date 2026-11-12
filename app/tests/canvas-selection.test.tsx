import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useCanvasArtifact, useUI } from "../src/store";
import type { Session } from "../src/types";

it("compares the selected step output but never an unrelated selected attachment", () => {
  const session = {
    steps: [{ id: "step", params: { image: "input" }, outputs: ["output"] }],
    artifacts: { input: { id: "input" }, output: { id: "output" }, attachment: { id: "attachment" } },
  } as unknown as Session;
  useUI.getState().set({ selectedStep: "step", selectedArtifact: null, viewerBefore: false });
  const { result } = renderHook(() => useCanvasArtifact(session));
  expect(result.current).toEqual({ id: "output", inputId: "input" });
  act(() => useUI.getState().set({ viewerBefore: true }));
  expect(result.current.id).toBe("input");
  act(() => useUI.getState().set({ selectedArtifact: "attachment" }));
  expect(result.current).toEqual({ id: "attachment", inputId: undefined });
  act(() => useUI.getState().set({ viewerBefore: true }));
  expect(result.current.id).toBe("attachment");
  act(() => useUI.getState().set({ selectedArtifact: { stepId: "step", outputIndex: 0 } }));
  expect(result.current).toEqual({ id: "output", inputId: "input" });
});
