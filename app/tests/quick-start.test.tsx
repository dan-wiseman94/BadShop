import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { fireEvent, render as renderView, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickStart } from "../src/components/QuickStart";
import { action } from "../src/data";
import { useUI } from "../src/store";
const state = vi.hoisted(() => ({ step: { id: "s1", tool: "layout", status: "done", outputs: [] as string[], params: { captions: ["old joke"] }, error: null as null | { message: string } } }));
vi.mock("../src/data", () => ({
  action: vi.fn(), importBlob: vi.fn(),
  useSession: () => ({ data: { steps: [state.step], artifacts: {}, turn_running: false } }),
  useCoreQuery: (method: string) => ({ data: method === "branches.list" ? { branches: [] } : [] }),
}));
function render(view: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderView(view, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}
beforeEach(() => {
  state.step = { id: "s1", tool: "layout", status: "done", outputs: [] as string[], params: { captions: ["old joke"] }, error: null };
  vi.mocked(action).mockReset();
  useUI.getState().set({ status: "ready", selectedStep: null });
});
it("preserves a typed punchline when its running step finishes, and loads another step's caption", () => {
  state.step = { ...state.step, status: "running" };
  const view = render(<QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Revised punchline"), { target: { value: "my next joke" } });
  state.step = { ...state.step, status: "done" };
  view.rerender(<QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} />);
  expect(screen.getByLabelText("Revised punchline")).toHaveValue("my next joke");
  state.step = { ...state.step, id: "s2", params: { captions: ["another step's joke"] } };
  view.rerender(<QuickStart onImport={vi.fn()} onAdvanced={vi.fn()} />);
  expect(screen.getByLabelText("Revised punchline")).toHaveValue("another step's joke");
});
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
