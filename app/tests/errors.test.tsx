import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it } from "vitest";
import { ErrorNotice } from "../src/components/ErrorNotice";
import { useUI, showError } from "../src/store";
import { applyCoreEvent, queries } from "../src/data";
beforeEach(() => {
  useUI.getState().set({ status: "starting", error: null, errorAction: null });
  queries.setQueryData(["session.get"], {
    messages: [],
    steps: [],
    artifacts: {},
    pending_approvals: [],
  });
});
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}
it("does not offer chat retry for an unrelated file or provider setup error", () => {
  showError(new Error("The OS keychain is locked"));
  render(<ErrorNotice />, { wrapper });
  expect(screen.getByRole("alert")).toHaveTextContent("keychain is locked");
  expect(
    screen.queryByRole("button", { name: "Retry turn" }),
  ).not.toBeInTheDocument();
});
it("offers retry specifically for a failed provider turn", () => {
  applyCoreEvent({
    method: "turn.finished",
    params: { reason: "provider_error", error: "Rate limit" },
  });
  render(<ErrorNotice />, { wrapper });
  expect(screen.getByRole("button", { name: "Retry turn" })).toBeVisible();
});
it("explains a budget stop without suggesting an invalid provider retry", () => {
  applyCoreEvent({ method: "turn.finished", params: { reason: "budget" } });
  expect(useUI.getState()).toMatchObject({ errorAction: null });
  expect(useUI.getState().error).toContain("step limit");
});
it("explains repeated invalid tool calls", () => {
  applyCoreEvent({
    method: "turn.finished",
    params: { reason: "invalid_calls" },
  });
  expect(useUI.getState().error).toContain("repeated invalid tool calls");
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
