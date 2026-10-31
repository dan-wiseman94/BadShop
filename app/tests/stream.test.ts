import { expect, it } from "vitest";
import { reconcileSessionSnapshot } from "../src/data";
import type { Message, Session } from "../src/types";
const reply = (id: string, text: string): Message => ({
  id,
  role: "assistant",
  content: [{ type: "text", text }],
  step_ids: [],
});
const session = (messages: Message[], stream_text = ""): Session => ({
  id: "session",
  name: "test",
  path: null,
  provider_profile_id: null,
  approval_mode: "auto",
  messages,
  steps: [],
  artifacts: {},
  turn_running: true,
  pending_approvals: [],
  restorable: null,
  stream_text,
});
it("replaces a streamed reply atomically when a snapshot already contains its persisted message", () => {
  const old = session([reply("m1", "Earlier")], "Ready after retry.");
  const snapshot = session([
    ...old.messages,
    reply("m2", "Ready after retry."),
  ]);
  const merged = reconcileSessionSnapshot(snapshot, old);
  expect(merged.messages).toHaveLength(2);
  expect(merged.stream_text).toBe("");
});
it("keeps partial text across a snapshot that has no newly persisted assistant reply", () => {
  const old = session([reply("m1", "Earlier")], "Ready after ");
  expect(reconcileSessionSnapshot(session(old.messages), old).stream_text).toBe(
    "Ready after ",
  );
});
it("uses message identity, preserving genuinely repeated assistant text", () => {
  const old = session([reply("m1", "Done.")], "Done.");
  const merged = reconcileSessionSnapshot(
    session([...old.messages, reply("m2", "Done.")]),
    old,
  );
  expect(merged.messages.map((message) => message.id)).toEqual(["m1", "m2"]);
  expect(merged.stream_text).toBe("");
});
it("does not carry transient text into another session", () => {
  expect(
    reconcileSessionSnapshot(
      { ...session([]), id: "new" },
      session([], "old text"),
    ).stream_text,
  ).toBe("");
});
