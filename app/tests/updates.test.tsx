import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UpdateSettings, useUpdates } from "../src/updates";

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), off: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => mocks.off }));
vi.mock("../src/native", () => ({ native: true, openLink: vi.fn() }));
const available = { currentVersion: "0.2.0", version: "0.3.0", notes: "Fixes", unavailable: null };
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks();
  const preferences = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => preferences.get(key) ?? null,
    setItem: (key: string, value: string) => preferences.set(key, value) });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("checks automatically, persists opt-out, and still allows manual checks", async () => {
  mocks.invoke.mockResolvedValue(available);
  const { result, unmount } = renderHook(() => useUpdates(async () => false));
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(result.current.info?.version).toBe("0.3.0");
  expect(mocks.invoke).toHaveBeenCalledTimes(1);
  act(() => result.current.setAutomatic(false));
  await act(() => vi.advanceTimersByTimeAsync(6 * 60 * 60 * 1000));
  expect(mocks.invoke).toHaveBeenCalledTimes(1);
  unmount();
  const next = renderHook(() => useUpdates(async () => false));
  expect(next.result.current.automatic).toBe(false);
  await act(() => next.result.current.check());
  expect(mocks.invoke).toHaveBeenCalledTimes(2);
});

it("downloads before confirming, cancels without installation, then permits retry", async () => {
  mocks.invoke.mockImplementation(async command => command === "update_check" ? available : undefined);
  const confirm = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
  const { result } = renderHook(() => useUpdates(confirm));
  await act(() => result.current.check());
  await act(() => result.current.install());
  expect(mocks.invoke.mock.calls.map(c => c[0])).toEqual(["update_check", "update_download"]);
  expect(mocks.off).toHaveBeenCalledTimes(1);
  await act(() => result.current.install());
  expect(mocks.invoke).toHaveBeenLastCalledWith("update_install");
  expect(mocks.off).toHaveBeenCalledTimes(2);
});

it("never prompts or installs after a failed signature/download and exposes retry", async () => {
  mocks.invoke.mockImplementation(async command => {
    if (command === "update_check") return available;
    throw new Error("Invalid signature");
  });
  const confirm = vi.fn();
  const { result } = renderHook(() => useUpdates(confirm));
  await act(() => result.current.check());
  await act(() => result.current.install());
  expect(confirm).not.toHaveBeenCalled();
  expect(result.current.error).toContain("Invalid signature");
  expect(result.current.phase).toBe("idle");
  expect(mocks.off).toHaveBeenCalled();
});

it("shows check failures without claiming up-to-date, then recovers through the button", async () => {
  mocks.invoke.mockRejectedValueOnce(new Error("Offline"))
    .mockResolvedValue({ ...available, version: null });
  function Panel() { return <UpdateSettings updates={useUpdates(async () => false)} />; }
  render(<Panel />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Check for updates" })));
  expect(screen.getByRole("alert").textContent).toContain("Offline");
  expect(screen.queryByText("You’re up to date.")).toBeNull();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Check for updates" })));
  expect(screen.getByText("You’re up to date.")).toBeTruthy();
});

it("reports installer failure and allows another explicit attempt", async () => {
  let failed = false;
  mocks.invoke.mockImplementation(async command => {
    if (command === "update_check") return available;
    if (command === "update_install" && !failed) {
      failed = true;
      throw new Error("Installer launch failed");
    }
  });
  const { result } = renderHook(() => useUpdates(async () => true));
  await act(() => result.current.check());
  await act(() => result.current.install());
  expect(result.current.error).toContain("Installer launch failed");
  expect(result.current.phase).toBe("idle");
  await act(() => result.current.install());
  expect(result.current.error).toBe("");
  expect(mocks.invoke.mock.calls.filter(c => c[0] === "update_install")).toHaveLength(2);
});
