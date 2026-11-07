import { beforeEach, expect, test, vi } from "vitest";
const calls = vi.hoisted(() => ({ invoke: vi.fn(), request: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: calls.invoke }));
vi.mock("../src/rpc", () => ({ rpc: { request: calls.request } }));
import { reportNativeReadiness } from "../src/nativeReadiness";

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("requestAnimationFrame", (callback: () => void) => callback());
});

test("receipt follows a successful catalog response, never a failed RPC", async () => {
  calls.invoke.mockResolvedValue(true);
  calls.request.mockRejectedValueOnce(new Error("unauthenticated"));
  await expect(reportNativeReadiness("session")).rejects.toThrow("unauthenticated");
  expect(calls.invoke).not.toHaveBeenCalledWith("renderer_ready", expect.anything());
  calls.request.mockResolvedValueOnce([{ name: "view" }]);
  await reportNativeReadiness("session");
  expect(calls.invoke).toHaveBeenLastCalledWith("renderer_ready", { sessionId: "session", toolCount: 1 });
});

test("normal launches do not run the probe", async () => {
  calls.invoke.mockResolvedValue(false);
  await reportNativeReadiness("session");
  expect(calls.request).not.toHaveBeenCalled();
});
