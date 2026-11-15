import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickStart } from "../src/components/QuickStart";
import { action } from "../src/data";
import { useUI } from "../src/store";

const state = vi.hoisted(() => ({
  step: {
    id: "s1", invocation_id: "layout", tool: "layout", status: "done",
    outputs: ["output"], params: { template: "desktop-error", title: "Original", captions: ["old joke"], images: [] },
  },
  revision: 1,
}));
const session = () => ({ steps: [state.step], artifacts: {}, document_revision: state.revision, turn_running: false });
vi.mock("../src/data", () => ({
  action: vi.fn(), importBlob: vi.fn(), useArtifact: () => ({}), imageUrl: () => undefined,
  useSession: () => ({ data: session() }),
  queries: { getQueryData: () => session() },
  useCoreQuery: (method: string) => ({ data: method === "branches.list" ? { branches: [] }
    : method === "layouts.list" ? [{ id: "desktop-error", slots: [{ name: "Message" }] }] : [] }),
}));
function editor() {
  return <QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} onHistory={vi.fn()} />;
}
beforeEach(() => {
  state.step = { ...state.step, id: "s1", invocation_id: "layout", status: "done",
    params: { ...state.step.params, title: "Original", captions: ["old joke"] } };
  state.revision = 1;
  vi.mocked(action).mockReset();
  useUI.getState().set({ status: "ready", selectedStep: null, selectedArtifact: null });
});

it("retains typed text across updates and prevents a stale draft from applying", () => {
  const view = render(editor());
  fireEvent.change(screen.getByLabelText("Caption Message"), { target: { value: "my next joke" } });
  state.step = { ...state.step, status: "running" };
  view.rerender(editor());
  expect(screen.getByLabelText("Caption Message")).toHaveValue("my next joke");
  state.revision += 1;
  state.step = { ...state.step, status: "done", params: { ...state.step.params, captions: ["saved elsewhere"] } };
  view.rerender(editor());
  expect(screen.getByLabelText("Caption Message")).toHaveValue("my next joke");
  expect(screen.getByRole("button", { name: "Apply changes" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reload saved controls" }));
  expect(screen.getByLabelText("Caption Message")).toHaveValue("saved elsewhere");
});

it("reports a terminal replay failure and offers undo and inspection", async () => {
  vi.mocked(action).mockResolvedValue({
    stale: ["s1", "s2"],
    replay: { status: "failed", revision: 1, completed_invocations: ["layout"],
      failed_step: { step_id: "s2", invocation_id: "effect", message: "storage limit" } },
  } as never);
  const view = render(editor());
  fireEvent.change(screen.getByLabelText("Caption Message"), { target: { value: "retry this joke" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));
  expect(await screen.findByText(/Changes were saved, but replay failed.*storage limit/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Undo edit" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Inspect failed step" })).toBeEnabled();
  expect(action).toHaveBeenCalledWith("steps.edit", {
    step_id: "s1", params: { ...state.step.params, captions: ["retry this joke"] }, replay: "local",
  });
  state.revision += 1;
  view.rerender(editor());
  expect(screen.queryByRole("button", { name: "Undo edit" })).toBeNull();
});
