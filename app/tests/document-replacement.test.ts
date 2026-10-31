import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { action, queries } from "../src/data";
import { rpc } from "../src/rpc";
import { useUI } from "../src/store";
import type { Session } from "../src/types";

const session = {
  id: "same-session",
  messages: [],
  artifacts: {},
  steps: [],
  stream_text: "",
} as unknown as Session;

beforeEach(() => {
  queries.clear();
  useUI.setState({
    ...useUI.getInitialState(),
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

it.each(["session.new", "session.open", "session.restore"] as const)(
  "resets transient document state only after successful %s",
  async (method) => {
    vi.spyOn(rpc, "request").mockResolvedValue(session);
    await action(
      method,
      method === "session.open" ? { path: "/saved.badshop" } : undefined,
    );
    expect(useUI.getState()).toMatchObject({
      documentGeneration: 8,
      selectedArtifact: null,
      selectedStep: null,
      paletteOpen: false,
      pick: null,
    });
    expect(
      queries.getQueryData(["artifact", "discarded", false]),
    ).toBeUndefined();
    expect(queries.getQueryData(["session.get"])).toMatchObject({
      id: "same-session",
      stream_text: "",
    });
  },
);

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
  vi.spyOn(rpc, "request").mockResolvedValue(session);
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
