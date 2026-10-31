import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Session } from "../src/types";
import { useUI } from "../src/store";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  action: vi.fn(),
  projectPath: vi.fn(),
  cached: vi.fn(),
  onCloseRequested: vi.fn(),
  setQueryData: vi.fn(),
}));
vi.mock("../src/rpc", () => ({ rpc: { request: mocks.request } }));
vi.mock("../src/data", () => ({
  action: mocks.action,
  queries: { getQueryData: mocks.cached, setQueryData: mocks.setQueryData },
  reconcileSessionSnapshot: (value: Session) => value,
}));
vi.mock("../src/native", () => ({
  projectPath: mocks.projectPath,
  onCloseRequested: mocks.onCloseRequested,
}));
vi.mock("../src/components/ErrorNotice", () => ({ ErrorNotice: () => null }));
import { useSessionActions } from "../src/sessionActions";

let session: Session;
let cachedSession: Session;
let close: () => Promise<boolean>;
beforeEach(() => {
  vi.resetAllMocks();
  session = {
    id: "one",
    name: "One",
    document_revision: 1,
    unsaved_changes: true,
    path: null,
    turn_running: false,
  } as Session;
  cachedSession = { ...session };
  mocks.request.mockImplementation(async () => ({ ...session }));
  mocks.cached.mockImplementation(() => cachedSession);
  mocks.setQueryData.mockImplementation((_key, update) => {
    cachedSession = update(cachedSession);
  });
  mocks.projectPath.mockResolvedValue("/projects/one.badshop");
  mocks.onCloseRequested.mockImplementation(async (handler) => {
    close = handler;
    return vi.fn();
  });
  mocks.action.mockImplementation(async (method, params) => {
    if (method === "session.save" || method === "session.save_as")
      session = { ...session, unsaved_changes: false };
    if (method === "chat.stop")
      session = {
        ...session,
        turn_running: false,
        document_revision: session.document_revision + 1,
      };
    if (["session.new", "session.open", "session.restore"].includes(method)) {
      if (params.expected_revision !== session.document_revision)
        throw new Error("the session changed before it could be replaced");
      if (session.unsaved_changes && !params.discard_unsaved)
        throw new Error("the session has unsaved changes");
    }
  });
  useUI
    .getState()
    .set({ status: "ready", error: null, errorAction: null, notice: null });
});

async function pendingRequest(
  result: ReturnType<
    typeof renderHook<ReturnType<typeof useSessionActions>, unknown>
  >["result"],
  destination: Parameters<
    ReturnType<typeof useSessionActions>["request"]
  >[0] = { kind: "new", name: "Two" },
) {
  let request!: Promise<boolean>;
  act(() => {
    request = result.current.request(destination);
  });
  await waitFor(() => expect(result.current.pending).not.toBeNull());
  return { request };
}

it("keeps the original document and decision open when Save As is canceled", async () => {
  mocks.projectPath.mockResolvedValue(null);
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  await act(() => result.current.decide("save"));
  expect(result.current.pending).not.toBeNull();
  expect(mocks.action).not.toHaveBeenCalled();
  act(() => result.current.cancel());
  await expect(request).resolves.toBe(false);
});

it("replaces only after a successful Save with its fresh revision", async () => {
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  await act(() => result.current.decide("save"));
  await expect(request).resolves.toBe(true);
  expect(mocks.action.mock.calls).toEqual([
    [
      "session.save_as",
      { path: "/projects/one.badshop", expected_revision: 1 },
    ],
    [
      "session.new",
      { name: "Two", expected_revision: 1, discard_unsaved: false },
    ],
  ]);
});

it("requires a fresh decision when Discard refers to an old revision", async () => {
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  session = { ...session, document_revision: 2 };
  await act(() => result.current.decide("discard"));
  expect(result.current.pending?.session.document_revision).toBe(2);
  expect(cachedSession.document_revision).toBe(2); // Cancel must leave the workbench on the refreshed state.
  expect(useUI.getState().error).toContain("changed before");
  await act(() => result.current.decide("discard"));
  await expect(request).resolves.toBe(true);
});

it("does not close when new unsaved changes arrive immediately after Save", async () => {
  const { result } = renderHook(useSessionActions);
  let closed!: Promise<boolean>;
  act(() => {
    closed = close();
  });
  await waitFor(() => expect(result.current.pending).not.toBeNull());
  mocks.action.mockImplementation(async () => {
    session = { ...session, document_revision: 2, unsaved_changes: true };
  });
  await act(() => result.current.decide("save"));
  expect(result.current.pending).not.toBeNull();
  expect(useUI.getState().error).toMatch(/changed|unsaved/i);
  act(() => result.current.cancel());
  await expect(closed).resolves.toBe(false);
});

it("does not save a different document from the one in the pending decision", async () => {
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  session = { ...session, id: "other", name: "Other", document_revision: 2 };
  await act(() => result.current.decide("save"));
  expect(mocks.action).not.toHaveBeenCalled();
  expect(result.current.pending?.session.id).toBe("other");
  act(() => result.current.cancel());
  await expect(request).resolves.toBe(false);
});

it("does not save a changed revision after an asynchronous file picker", async () => {
  mocks.projectPath.mockImplementation(async () => {
    session = { ...session, document_revision: 2 };
    return "/projects/one.badshop";
  });
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  await act(() => result.current.decide("save"));
  expect(mocks.action).not.toHaveBeenCalled();
  expect(result.current.pending?.session.document_revision).toBe(2);
  act(() => result.current.cancel());
  await expect(request).resolves.toBe(false);
});

it("requires an explicit close decision when only a stale clean cache is available", async () => {
  session = { ...session, unsaved_changes: false };
  cachedSession = { ...session };
  mocks.request.mockRejectedValue(new Error("core disconnected"));
  useUI.getState().set({ status: "disconnected" });
  const { result } = renderHook(useSessionActions);
  let closed!: Promise<boolean>;
  act(() => {
    closed = close();
  });
  await waitFor(() => expect(result.current.pending).not.toBeNull());
  await act(() => result.current.decide("discard"));
  await expect(closed).resolves.toBe(true);
});

it("stops a running turn before Save and close", async () => {
  session = { ...session, turn_running: true, path: "/projects/one.badshop" };
  const { result } = renderHook(useSessionActions);
  let closed!: Promise<boolean>;
  act(() => {
    closed = close();
  });
  await waitFor(() => expect(result.current.pending).not.toBeNull());
  await act(() => result.current.decide("save"));
  await expect(closed).resolves.toBe(true);
  expect(mocks.action.mock.calls.map(([method]) => method)).toEqual([
    "chat.stop",
    "session.save",
  ]);
  expect(mocks.action).toHaveBeenLastCalledWith("session.save", {
    expected_revision: 2,
  });
});

it("keeps the decision open after a failed Save without trying to replace", async () => {
  mocks.action.mockRejectedValue(new Error("disk full"));
  const { result } = renderHook(useSessionActions);
  const { request } = await pendingRequest(result);
  await act(() => result.current.decide("save"));
  expect(result.current.pending).not.toBeNull();
  expect(useUI.getState().error).toContain("disk full");
  expect(mocks.action.mock.calls.map(([method]) => method)).toEqual([
    "session.save_as",
  ]);
  act(() => result.current.cancel());
  await expect(request).resolves.toBe(false);
});

it("requires a fresh explicit Discard when the document changes during a close decision", async () => {
  const { result } = renderHook(useSessionActions);
  let closed!: Promise<boolean>;
  act(() => {
    closed = close();
  });
  await waitFor(() => expect(result.current.pending).not.toBeNull());
  session = { ...session, document_revision: 2 };
  await act(() => result.current.decide("discard"));
  expect(result.current.pending?.session.document_revision).toBe(2);
  expect(useUI.getState().error).toContain("changed while");
  await act(() => result.current.decide("discard"));
  await expect(closed).resolves.toBe(true);
});

it("refuses switching during a running turn before any replacement action", async () => {
  session = { ...session, turn_running: true };
  const { result } = renderHook(useSessionActions);
  await expect(result.current.request({ kind: "restore" })).rejects.toThrow(
    "Stop the agent",
  );
  expect(mocks.action).not.toHaveBeenCalled();
});
