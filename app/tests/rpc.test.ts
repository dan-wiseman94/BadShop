import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RpcClient, RpcError } from "../src/rpc";
const welcome = { type: "welcome", protocol: 1, core_instance_id: "core", build_id: "build", event_seq: 0 };
const context = { core_instance_id: "core", document_id: "document", document_incarnation: "open-1",
  branch_id: null, revision: 1, event_seq: 1 };
const step = { id: "s1", index: 0, tool: "filter", params: {}, actor: "user", status: "done",
  outputs: [], result_text: "", data: null, error: null, reason: null, edited: false,
  started_at: null, finished_at: null, cache_key: null, previous_outputs: [], locked_fields: [],
  bypassed: false, lock_review: false, lock_approved: false };
class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  onerror?: () => void;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(value: string) {
    this.sent.push(value);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}
let rpc: RpcClient;
beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  rpc = new RpcClient();
});
afterEach(() => {
  rpc.disconnect();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
async function connect() {
  const ready = rpc.connect({ port: 1234, token: "secret" });
  const socket = FakeSocket.instances.at(-1)!;
  socket.open();
  expect(JSON.parse(socket.sent[0])).toEqual({
    type: "hello",
    actor: "user",
    token: "secret",
    protocol: 1,
  });
  socket.receive(welcome);
  await ready;
  return socket;
}
describe("authenticated RPC", () => {
  it("rejects a mistyped result without retrying or resolving it", async () => {
    const socket = await connect();
    const response = rpc.request("export", { artifact_id: "image" });
    const rejected = expect(response).rejects.toThrow("Malformed core result");
    socket.receive({ jsonrpc: "2.0", id: JSON.parse(socket.sent[1]).id, result: { path: 123 } });
    await rejected;
    expect(socket.sent).toHaveLength(2);
  });
  it("closes on a malformed nested event before updating client state", async () => {
    const socket = await connect();
    const listener = vi.fn();
    rpc.onEvent(listener);
    socket.receive({ jsonrpc: "2.0", method: "step.finished", params: { step: { ...step, outputs: [123] } },
      core_instance_id: "core", event_seq: 1, context });
    expect(listener).not.toHaveBeenCalled();
    expect(socket.readyState).toBe(3);
  });
  it("resynchronizes on a delivery gap without repeating a mutation", async () => {
    const socket = await connect();
    const listener = vi.fn();
    rpc.onEvent(listener);
    const pending = rpc.request("session.new");
    const rejected = expect(pending).rejects.toThrow("disconnected");
    socket.receive({ jsonrpc: "2.0", method: "step.finished", params: {},
      core_instance_id: "core", event_seq: 2, context: { ...context, event_seq: 2 } });
    expect(listener).toHaveBeenCalledExactlyOnceWith({ method: "core.resync", params: {} });
    socket.close();
    await rejected;
    const fresh = await connect();
    expect(fresh.sent).toHaveLength(1); // hello only; no automatic retry of session.new
  });
  it("rejects incompatible protocols before accepting commands", async () => {
    const ready = rpc.connect({ port: 1234, token: "secret" });
    const rejected = expect(ready).rejects.toThrow("Incompatible core protocol");
    const socket = FakeSocket.instances.at(-1)!;
    socket.open();
    socket.receive({ ...welcome, protocol: 99 });
    await rejected;
    expect(socket.readyState).toBe(3);
  });
  it("rejects malformed reply envelopes and events from another core", async () => {
    const socket = await connect();
    const pending = rpc.request("session.get");
    const rejected = expect(pending).rejects.toThrow("Malformed core result");
    socket.receive({ jsonrpc: "2.0", id: JSON.parse(socket.sent[1]).id });
    await rejected;
    const listener = vi.fn();
    rpc.onEvent(listener);
    socket.receive({ jsonrpc: "2.0", method: "message.delta", params: { text: "obsolete" },
      core_instance_id: "other", event_seq: 1, context });
    expect(listener).not.toHaveBeenCalled();
    expect(socket.readyState).toBe(3);
  });
  it("waits for welcome and correlates concurrent responses", async () => {
    const socket = await connect();
    const one = rpc.request("cache.status");
    const two = rpc.request("tools.list");
    const id1 = JSON.parse(socket.sent[1]).id;
    const id2 = JSON.parse(socket.sent[2]).id;
    socket.receive({ jsonrpc: "2.0", id: id2, result: [] });
    socket.receive({ jsonrpc: "2.0", id: id1, result: { bytes: 123, files: 1, budget_mb: 512 } });
    expect(await two).toEqual([]);
    expect(await one).toEqual({ bytes: 123, files: 1, budget_mb: 512 });
  });
  it("rejects pending requests on disconnect and authenticates a fresh connection", async () => {
    const socket = await connect();
    const pending = rpc.request("session.get");
    const rejected = expect(pending).rejects.toThrow("disconnected");
    socket.close();
    await rejected;
    const fresh = await connect();
    const response = rpc.request("tools.list");
    const id = JSON.parse(fresh.sent.at(-1)!).id;
    fresh.receive({ jsonrpc: "2.0", id, result: [] });
    expect(await response).toEqual([]);
  });
  it("cancels a pending call without processing its eventual reply", async () => {
    const socket = await connect();
    const abort = new AbortController();
    const pending = rpc.request("session.get", undefined, abort.signal);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    abort.abort();
    await assertion;
    socket.receive({ jsonrpc: "2.0", id: JSON.parse(socket.sent[1]).id, result: "late" });
    expect(socket.readyState).toBe(1);
  });
  it("surfaces server errors and hint, and dispatches notifications", async () => {
    const socket = await connect();
    const listener = vi.fn();
    rpc.onEvent(listener);
    socket.receive({ jsonrpc: "2.0", method: "step.finished", params: { step },
      core_instance_id: "core", event_seq: 1, context });
    expect(listener).toHaveBeenCalledWith({
      method: "step.finished",
      params: { step },
      core_instance_id: "core", event_seq: 1, context,
    });
    const response = rpc.request("chat.retry");
    const assertion = expect(response).rejects.toEqual(
      new RpcError("No turn", "Send a message", -32000),
    );
    socket.receive({
      jsonrpc: "2.0",
      id: JSON.parse(socket.sent.at(-1)!).id,
      error: {
        code: -32000,
        message: "No turn",
        data: { hint: "Send a message" },
      },
    });
    await assertion;
  });
  it("rejects pending calls when explicitly replaced", async () => {
    await connect();
    const pending = rpc.request("session.get");
    const assertion = expect(pending).rejects.toThrow("disconnected");
    await connect();
    await assertion;
  });
});
it("rejects an in-progress handshake when a new connection replaces it", async () => {
  const opening = rpc.connect({ port: 1234, token: "old" });
  const assertion = expect(opening).rejects.toThrow("replaced");
  await connect();
  await assertion;
});

it("does not send an action before authentication completes", async () => {
  const ready = rpc.connect({ port: 1234, token: "secret" });
  void ready.catch(() => {}); // cleanup may replace it when this regression fails
  const socket = FakeSocket.instances.at(-1)!;
  socket.open();
  const requested = rpc.request("session.new");
  void requested.catch(() => {});
  expect(socket.sent).toHaveLength(1); // hello only
  await expect(requested).rejects.toThrow("disconnected");
  socket.receive(welcome);
  await ready;
});

it("a timed-out handshake ignores buffered messages while the socket is closing", async () => {
  vi.useFakeTimers();
  const ready = rpc.connect({ port: 1234, token: "secret" });
  const assertion = expect(ready).rejects.toThrow("did not answer");
  const socket = FakeSocket.instances.at(-1)!;
  socket.open();
  // Browser close is asynchronous; buffered messages may arrive before the close event.
  socket.close = () => { socket.readyState = 2; };
  const status = vi.fn();
  const event = vi.fn();
  rpc.onStatus(status);
  rpc.onEvent(event);
  await vi.advanceTimersByTimeAsync(10000);
  await assertion;
  socket.receive(welcome);
  socket.receive({ method: "step.finished", params: { step: { id: "s1" } } });
  expect(status.mock.calls).toEqual([["disconnected"]]);
  expect(event).not.toHaveBeenCalled();
});

it("an error retires the socket immediately and a fresh connection works", async () => {
  const ready = rpc.connect({ port: 1234, token: "secret" });
  const assertion = expect(ready).rejects.toThrow("Could not connect");
  const socket = FakeSocket.instances.at(-1)!;
  const status = vi.fn();
  rpc.onStatus(status);
  socket.onerror?.();
  await assertion;
  expect(status.mock.calls).toEqual([["disconnected"]]);
  expect(socket.readyState).toBe(3);
  expect(socket.sent).toHaveLength(0);
  await connect();
});
