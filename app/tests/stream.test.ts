import { expect, it } from "vitest";
import { applyCoreEvent, queries, reconcileSessionSnapshot } from "../src/data";
import type { Message, Session } from "../src/types";
import { useUI } from '../src/store';
import { useStream } from '../src/stream';
const reply = (id: string, text: string): Message => ({
  id,
  role: "assistant",
  content: [{ type: "text", text }],
  step_ids: [],
});
const session = (messages: Message[], stream_text?: string): Session => ({
  id: "session",
  unsaved_changes: false,
  document_revision: 0,
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
const context = { core_instance_id: "core", document_id: "session", document_incarnation: "opened-2",
  branch_id: "branch", revision: 10, event_seq: 20 };

it('streams without replacing document entities and rejects repeated presentation events', () => {
  const current = { ...session([reply('m1', 'earlier')]), context };
  queries.setQueryData(['session.get'], current);
  const cached = queries.getQueryData(['session.get']);
  useStream.setState({ text: '', context });
  const event = { method: 'message.delta', params: { text: 'new text' }, context: { ...context, event_seq: 21 } };
  applyCoreEvent(event);
  applyCoreEvent(event);
  expect(useStream.getState().text).toBe('new text');
  expect(queries.getQueryData(['session.get'])).toBe(cached);
  applyCoreEvent({ method: 'message.done', params: { message: reply('m2', 'new text') }, context: { ...context, event_seq: 22 } });
  expect(useStream.getState().text).toBe('');
  expect(queries.getQueryData<Session>(['session.get'])?.messages).toHaveLength(2);
  queries.clear(); useStream.setState({ text: '', context: undefined });
});

it("rejects delayed events after reopening the same saved document", () => {
  const current = { ...session([], "current reply"), context };
  queries.setQueryData(["session.get"], current);
  applyCoreEvent({ method: "message.delta", params: { text: "stale text" },
    context: { ...context, document_incarnation: "opened-1", revision: 9, event_seq: 19 } });
  expect(queries.getQueryData(["session.get"])).toEqual(current);
  applyCoreEvent({ method: "turn.finished", params: { reason: "done" },
    context: { ...context, branch_id: "previous-branch" } });
  expect(queries.getQueryData(["session.get"])).toEqual(current);
  queries.clear();
});
it("does not replace newer event state with an older snapshot", () => {
  const current = { ...session([], "current reply"), context };
  expect(reconcileSessionSnapshot({ ...session([]), context: { ...context, revision: 9 } }, current)).toBe(current);
  expect(reconcileSessionSnapshot({ ...session([]), context: { ...context, event_seq: 19 } }, current)).toBe(current);
  const reopened = reconcileSessionSnapshot({ ...session([]), context: { ...context, document_incarnation: "opened-3", revision: 11 } }, current);
  expect(reopened.stream_text).toBe("");
});
it("ignores delayed deltas already covered by a snapshot and deltas from a prior retry", () => {
  const current = { ...session([], "current reply"), context, run_id: "new-run" };
  queries.setQueryData(["session.get"], current);
  applyCoreEvent({ method: "message.delta", params: { text: "already reflected", run_id: "new-run" }, context });
  expect(queries.getQueryData(["session.get"])).toEqual(current);
  applyCoreEvent({ method: "message.delta", params: { text: "old retry", run_id: "old-run" },
    context: { ...context, event_seq: 21 } });
  expect(queries.getQueryData(["session.get"])).toEqual(current);
  queries.clear();
});
it("clears late stream text when the core reports the turn is idle", () => {
  const old = session([reply("m1", "Done")], "Done");
  expect(reconcileSessionSnapshot({ ...session(old.messages), turn_running: false }, old).stream_text).toBe("");
});

it("refreshes source availability after a finished source tool", () => {
  queries.setQueryData(["sources.status"], { installed: false });
  applyCoreEvent({ method: "step.finished", params: {} });
  expect(queries.getQueryState(["sources.status"])?.isInvalidated).toBe(true);
  queries.clear();
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
it("clears late text when an idle snapshot already contains the completed reply", () => {
  const old = session([reply("m1", "Ready after retry.")], "Ready after retry.");
  const merged = reconcileSessionSnapshot(
    { ...session(old.messages), turn_running: false },
    old,
  );
  expect(merged.messages).toEqual(old.messages);
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


it('offers continuation only for retryable provider outcomes', () => {
  for (const retryable of [false, true]) {
    useStream.setState({ text: '', context });
    queries.setQueryData(['session.get'], { ...session([]), context });
    applyCoreEvent({ method: 'turn.finished', params: { reason: 'provider_error', error: 'Safe advice',
      error_category: retryable ? 'timeout' : 'authentication', retryable },
      context: { ...context, event_seq: 21 } });
    expect(useUI.getState().error).toBe('Safe advice');
    expect(useUI.getState().errorAction).toBe(retryable ? 'retry-turn' : null);
    queries.clear();
  }
  useUI.getState().set({ error: null, errorAction: null });
});
