import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../src/App";
import { queries } from "../src/data";
import { rpc } from "../src/rpc";
import { useUI } from "../src/store";
import type { Session } from "../src/types";

const native = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", async importOriginal => ({
  ...await importOriginal<typeof import("@tauri-apps/api/core")>(), invoke: native.invoke,
}));
vi.mock("@tauri-apps/api/event", async importOriginal => ({
  ...await importOriginal<typeof import("@tauri-apps/api/event")>(), listen: async () => () => {},
}));
vi.mock("../src/native", async importOriginal => ({
  ...await importOriginal<typeof import("../src/native")>(),
  native: true,
  getConnection: async () => ({ port: 1234, token: "isolated-update-test" }),
  onCloseRequested: async () => () => {},
  onCoreStatus: async () => () => {},
  onFileDrop: async () => () => {},
}));

const session: Session = {
  id: "update-focus", name: "Untitled", path: null, provider_profile_id: null,
  approval_mode: "auto", messages: [], steps: [], artifacts: {}, turn_running: false,
  pending_approvals: [], restorable: null, unsaved_changes: false, document_revision: 0,
};

beforeEach(() => {
  queries.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  const preferences = new Map<string, string>([["badshop.welcome", "1"], ["badshop.automaticUpdates", "false"]]);
  vi.stubGlobal("localStorage", { getItem: (key: string) => preferences.get(key) ?? null,
    setItem: (key: string, value: string) => preferences.set(key, value) });
  // JSDOM has no layout; this is the browser geometry boundary used to find tabbable controls.
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{ width: 100, height: 30 }] as unknown as DOMRectList);
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() {} });
  vi.spyOn(rpc, "connect").mockResolvedValue();
  vi.spyOn(rpc, "disconnect").mockImplementation(() => {});
  vi.spyOn(rpc, "request").mockImplementation(method => Promise.resolve(
    method === "session.get" ? session
      : method === "settings.get" ? { no_remote: false, approval_mode: "auto" }
        : method === "branches.list" ? { active_id: "original", branches: [] } : [],
  ) as never);
  useUI.getState().set({ status: "starting", settingsOpen: false, paletteOpen: false,
    pick: null, error: null, errorAction: null, notice: null });
});
afterEach(() => {
  queries.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
});

it("keeps keyboard focus on update cancellation and restores Settings when cancelled", async () => {
  let cancelDownload!: (error: Error) => void;
  native.invoke.mockImplementation(command => {
    if (command === "update_check") return Promise.resolve({ currentVersion: "0.4.1", version: "0.4.2", notes: "Fixes", unavailable: null });
    if (command === "update_download") return new Promise((_, reject) => { cancelDownload = reject; });
    if (command === "update_cancel") cancelDownload(new Error("Update cancelled"));
    return Promise.resolve(false);
  });
  render(<QueryClientProvider client={queries}><App /></QueryClientProvider>);
  await screen.findByText("Connected", { exact: true });
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Updates" }));
  fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
  const install = await screen.findByRole("button", { name: "Download & install update" });
  install.focus();
  fireEvent.click(install);
  const updating = await screen.findByRole("dialog", { name: "Updating badshop" });
  const cancel = within(updating).getByRole("button", { name: "Cancel download" });
  await waitFor(() => expect(cancel).toHaveFocus());
  fireEvent.keyDown(cancel, { key: "Tab" });
  expect(cancel).toHaveFocus();
  fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true });
  expect(cancel).toHaveFocus();
  await act(async () => { fireEvent.click(cancel); });
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Updating badshop" })).not.toBeInTheDocument());
  const settings = screen.getByRole("dialog", { name: "Settings" });
  expect(settings).toContainElement(document.activeElement as HTMLElement);
  expect(within(settings).getByRole("button", { name: "Download & install update" })).toBeEnabled();
});
