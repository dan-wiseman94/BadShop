import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { QuickStart } from "../src/components/QuickStart";
import { action } from "../src/data";
import { useUI } from "../src/store";
const state = vi.hoisted(() => ({ step: { id: "s1", tool: "layout", status: "done", params: { captions: ["old joke"] }, error: null as null | { message: string } } }));
vi.mock("../src/data", () => ({
  action: vi.fn(), importBlob: vi.fn(),
  useSession: () => ({ data: { steps: [state.step], artifacts: {}, turn_running: false } }),
  useCoreQuery: (method: string) => ({ data: method === "layouts.list" ? [] : { branches: [] } }),
}));
it("retains a failed caption and offers retry when replay resolves with an error step", async () => {
  useUI.getState().set({ status: "ready", selectedStep: "s1" });
  vi.mocked(action).mockImplementation(async method => {
    if (method === "steps.edit") state.step = { ...state.step, params: { captions: ["retry this joke"] } };
    if (method === "steps.replay_from") {
      state.step = { ...state.step, status: "error", error: { message: "storage limit" } };
      return [state.step] as never;
    }
    return state.step as never;
  });
  const view = render(<QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Revised punchline"), { target: { value: "retry this joke" } });
  fireEvent.click(screen.getByRole("button", { name: "Change caption only" }));
  expect(await screen.findByText("storage limit", { exact: true })).toBeVisible();
  view.rerender(<QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} />);
  expect(screen.getByLabelText("Revised punchline")).toHaveValue("retry this joke");
  expect(screen.getByRole("button", { name: "Change caption only" })).toBeEnabled();
});
