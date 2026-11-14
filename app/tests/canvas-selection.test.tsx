import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useCanvasArtifact, useUI } from "../src/store";
import type { Session } from "../src/types";
import { recordedElements } from "../src/recordedElements";

it("keeps composition order and stops element selection across unknown geometry", () => {
  const session = { steps: [
    { id: "layout", tool: "layout", status: "done", outputs: ["panels"], params: {},
      data: { layout: { slots: [{ name: "Portrait", box: [5, 10, 50, 80] }] } } },
    { id: "paste", index: 2, tool: "paste", status: "done", outputs: ["picture"], params: { base: "panels" },
      data: { element_bounds: [-5, 20, 30, 70] } },
    { id: "text", tool: "text", status: "done", outputs: ["caption"], params: { image: "picture", text: "Hello" },
      data: { element_bounds: [0, 5, 80, 20] } },
    { id: "crop", tool: "transform", status: "done", outputs: ["cropped"], params: { image: "caption" } },
  ] } as unknown as Session;
  expect(recordedElements(session, "caption").map(element => element.step.id)).toEqual(["layout", "paste", "text"]);
  expect(recordedElements(session, "cropped")).toEqual([]);
  expect(recordedElements(session, "unrelated")).toEqual([]);
  session.steps[2].data = { element_bounds: [0, 0, Infinity, 20] };
  expect(recordedElements(session, "caption").map(element => element.step.id)).toEqual(["layout", "paste"]);
});

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
