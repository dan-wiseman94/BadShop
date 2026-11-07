import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RpcClient, RpcError } from "../src/rpc";
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
  });
  socket.receive({ type: "welcome" });
  await ready;
  return socket;
}
describe("authenticated RPC", () => {
  it("waits for welcome and correlates concurrent responses", async () => {
    const socket = await connect();
    const one = rpc.request("session.get");
    const two = rpc.request("tools.list");
    const id1 = JSON.parse(socket.sent[1]).id;
    const id2 = JSON.parse(socket.sent[2]).id;
    socket.receive({ jsonrpc: "2.0", id: id2, result: ["tool"] });
    socket.receive({ jsonrpc: "2.0", id: id1, result: { name: "test" } });
    expect(await two).toEqual(["tool"]);
    expect(await one).toEqual({ name: "test" });
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
    fresh.receive({ id, result: [] });
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
    socket.receive({ id: JSON.parse(socket.sent[1]).id, result: "late" });
    expect(socket.readyState).toBe(1);
  });
  it("surfaces server errors and hint, and dispatches notifications", async () => {
    const socket = await connect();
    const listener = vi.fn();
    rpc.onEvent(listener);
    socket.receive({ method: "step.finished", params: { step: { id: "s1" } } });
    expect(listener).toHaveBeenCalledWith({
      method: "step.finished",
      params: { step: { id: "s1" } },
    });
    const response = rpc.request("chat.retry");
    const assertion = expect(response).rejects.toEqual(
      new RpcError("No turn", "Send a message", -32000),
    );
    socket.receive({
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
  socket.receive({ type: "welcome" });
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
  socket.receive({ type: "welcome" });
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
