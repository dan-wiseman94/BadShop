import { beforeEach, expect, test, vi } from "vitest";
const calls = vi.hoisted(() => ({ invoke: vi.fn(), request: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: calls.invoke }));
vi.mock("../src/rpc", () => ({ rpc: { request: calls.request } }));
vi.mock("../src/native", () => ({ verifyImageClipboard: async () => true }));
import { reportNativeReadiness } from "../src/nativeReadiness";
const state = { ready: true, sessionId: "session", revision: 1, unsaved: true, welcome: false, closePending: false };

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("requestAnimationFrame", (callback: () => void) => callback());
});

test("receipt follows a successful catalog response, never a failed RPC", async () => {
  calls.invoke.mockImplementation(async (command) => command !== "smoke_capture_enabled");
  calls.request.mockRejectedValueOnce(new Error("unauthenticated"));
  await expect(reportNativeReadiness(state)).rejects.toThrow("unauthenticated");
  expect(calls.invoke).not.toHaveBeenCalledWith("renderer_ready", expect.anything());
  calls.request.mockResolvedValueOnce([{ name: "view" }]);
  await reportNativeReadiness(state);
  expect(calls.invoke).toHaveBeenLastCalledWith("renderer_ready", { ...state, toolCount: 1, clipboardPixels: true });
});

test("normal launches do not run the probe", async () => {
  calls.invoke.mockResolvedValue(false);
  await reportNativeReadiness(state);
  expect(calls.request).not.toHaveBeenCalled();
});

test("obsolete catalog completion cannot overwrite the replacement state", async () => {
  calls.invoke.mockImplementation(async (command) => command !== "smoke_capture_enabled");
  let finish!: (tools: unknown[]) => void;
  calls.request.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  let current = true;
  const report = reportNativeReadiness(state, () => current);
  await Promise.resolve();
  current = false;
  finish([{ name: "view" }]);
  await report;
  expect(calls.invoke).not.toHaveBeenCalledWith("renderer_ready", expect.anything());
  await reportNativeReadiness({ ...state, ready: false });
  expect(calls.invoke).toHaveBeenLastCalledWith("renderer_ready", { ...state, ready: false, toolCount: 0, clipboardPixels: false });
});
