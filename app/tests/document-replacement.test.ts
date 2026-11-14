import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { action, importBlob, queries } from "../src/data";
import { rpc, RpcError } from "../src/rpc";
import { useUI } from "../src/store";
import type { MethodMap } from "../src/types";
import type { ResponseArtifactMeta } from "../src/wire.generated";

const session: MethodMap['session.get'][1] = {
  id: "same-session",
  messages: [],
  artifacts: {},
  steps: [],
  schema: 5, name: "Test", created_at: 0, provider_profile_id: null, approval_mode: "ask_all",
  transcript: [], active_branch_id: null, recipes: [], undo_branch_id: null,
  pause_before_finish: false, context: { core_instance_id: "core", document_id: "same-session",
    document_incarnation: "open", branch_id: null, revision: 1, event_seq: 0 },
  path: null, document_revision: 1, unsaved_changes: false, turn_running: false, batch_running: false,
  pending_approvals: [], restorable: null, bypass_tools: [], run_id: null, last_turn_outcome: null,
  stream_text: '',
  scripted_provider: false,
  manual_history: { undo: null, redo: null },
  creative: { style: "geocities", density: "balanced", era_strictness: "inspired", exact_text: true,
    seed: 1, fit: "contain", takes: 1, remember_history: true, animation_delay: 100,
    export_profile: "original", favorite_styles: [], favorite_briefs: [], saved_searches: [],
    locks: {}, mixer: {}, source_roles: {} },
};

beforeEach(() => {
  queries.clear();
  useUI.setState({
    ...useUI.getInitialState(),
    status: "ready",
    documentGeneration: 7,
    selectedArtifact: "discarded",
    selectedStep: "discarded-step",
    paletteOpen: true,
    pick: { kind: "point", artifactId: "discarded", complete: vi.fn() },
  });
  queries.setQueryData(["session.get"], {
    ...session,
    stream_text: "Old partial reply",
  });
  queries.setQueryData(["artifact", "discarded", false], { data: "old-image" });
});
afterEach(() => vi.restoreAllMocks());

it("does not return an old import result for selection after document replacement", async () => {
  const artifact: ResponseArtifactMeta = {
    id: "old", label: "old", width: 1, height: 1, format: "PNG", mime: "image/png",
    frames: 1, produced_by: null, source: null, original_id: null,
  };
  vi.spyOn(rpc, "request").mockResolvedValue({ working: artifact, original: artifact });
  vi.spyOn(queries, "invalidateQueries").mockImplementationOnce(async () => {
    // The import finished in the old document, then New completed while the
    // import action was refreshing its snapshot, before App selects its result.
    useUI.getState().set({ documentGeneration: 8 });
  });
  await expect(action("artifacts.import", { path: "image.png" })).rejects.toThrow("session changed");
});

it("rejects an image read that finishes after document replacement", async () => {
  let finishRead: () => void = () => {};
  class DelayedReader {
    result = "data:image/png;base64,aW1hZ2U=";
    onload?: () => void;
    readAsDataURL() { finishRead = () => this.onload?.(); }
  }
  vi.stubGlobal("FileReader", DelayedReader);
  const artifact: ResponseArtifactMeta = {
    id: "old", label: "old", width: 1, height: 1, format: "PNG", mime: "image/png",
    frames: 1, produced_by: null, source: null, original_id: null,
  };
  const request = vi.spyOn(rpc, "request").mockResolvedValue({ working: artifact, original: artifact });
  try {
    const imported = importBlob(new Blob(["image"]));
    useUI.getState().set({ documentGeneration: 8 });
    finishRead();
    await expect(imported).rejects.toThrow("session changed");
    expect(request).not.toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
  }
});

it("preserves drafts, selections and image cache when Open fails", async () => {
  vi.spyOn(rpc, "request").mockRejectedValue(new Error("file is unavailable"));
  await expect(
    action("session.open", { path: "/missing.badshop" }),
  ).rejects.toThrow("file is unavailable");
  expect(useUI.getState()).toMatchObject({
    documentGeneration: 7,
    selectedArtifact: "discarded",
    selectedStep: "discarded-step",
    paletteOpen: true,
  });
  expect(useUI.getState().pick).not.toBeNull();
  expect(queries.getQueryData(["artifact", "discarded", false])).toEqual({
    data: "old-image",
  });
});

it("preserves document drafts on ordinary edits and saves", async () => {
  vi.spyOn(rpc, "request").mockResolvedValueOnce(session).mockResolvedValueOnce({ path: "/saved.badshop" });
  await action("session.set_approval_mode", { mode: "ask_all" });
  await action("session.save", { expected_revision: 1 });
  expect(useUI.getState()).toMatchObject({
    documentGeneration: 7,
    selectedArtifact: "discarded",
    paletteOpen: true,
  });
  expect(useUI.getState().pick).not.toBeNull();
  expect(queries.getQueryData(["artifact", "discarded", false])).toEqual({
    data: "old-image",
  });
});

it("rejects user mutations during reconnect before sending any stale parameters", async () => {
  const request = vi.spyOn(rpc, "request");
  useUI.getState().set({ status: "connecting" });
  await expect(
    action("tools.run", { tool: "deepfry", params: { image: "discarded" } }),
  ).rejects.toThrow("Wait for the core to reconnect");
  expect(request).not.toHaveBeenCalled();
  expect(useUI.getState().documentGeneration).toBe(7);
  expect(queries.getQueryData(["session.get"])).toMatchObject({
    id: "same-session",
    stream_text: "Old partial reply",
  });
});

it("refreshes after a revision conflict without replaying the rejected edit", async () => {
  const request = vi.spyOn(rpc, "request").mockRejectedValue(new RpcError("Document changed", undefined, -32002));
  const refresh = vi.spyOn(queries, "invalidateQueries").mockResolvedValue();
  await expect(action("steps.edit", { step_id: "s1", params: {} })).rejects.toThrow("Document changed");
  expect(request).toHaveBeenCalledTimes(1);
  expect(refresh).toHaveBeenCalledWith({ queryKey: ["session.get"] });
  expect(useUI.getState().documentGeneration).toBe(7);
});
