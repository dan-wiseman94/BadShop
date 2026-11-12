import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProfileEditor } from "../src/components/Settings";
import { queries } from "../src/data";
import { rpc } from "../src/rpc";
import { useUI } from "../src/store";

afterEach(() => { vi.restoreAllMocks(); queries.clear(); });

it("keeps provider fields stable while CLI detection is pending", async () => {
  useUI.getState().set({ status: "ready" });
  let finish!: (value: unknown) => void;
  vi.spyOn(rpc, "request").mockImplementation(() => new Promise(resolve => { finish = resolve; }) as never);
  render(<QueryClientProvider client={queries}><ProfileEditor kind="cli" onSaved={() => {}} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Profile name"), { target: { value: "My subscription" } });
  fireEvent.click(screen.getByRole("button", { name: "Detect installed CLI" }));
  await waitFor(() => expect(screen.getByLabelText("Command line tool")).toBeDisabled());
  expect(screen.getByLabelText("Profile name")).toBeDisabled();
  await act(async () => finish([{ cli: "claude", available: true, supported: true, executable: "/tmp/test-claude", version: "Test version", experimental: false }]));
  await waitFor(() => expect(screen.getByLabelText("Command line tool")).toBeEnabled());
  expect(screen.getByLabelText("Profile name")).toHaveValue("My subscription");
  expect(screen.getByLabelText("Executable path (optional)")).toHaveValue("/tmp/test-claude");
});
