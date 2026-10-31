import type { Connection, CoreEvent, MethodMap } from "./types";
export class RpcError extends Error {
  constructor(
    message: string,
    public hint?: string,
    public code?: number,
  ) {
    super(message);
    this.name = "RpcError";
  }
}
type Pending = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  cleanup: () => void;
};
export class RpcClient {
  private ws?: WebSocket;
  private pending = new Map<number, Pending>();
  private next = 0;
  private generation = 0;
  private cancelConnect?: () => void;
  private events = new Set<(event: CoreEvent) => void>();
  private statuses = new Set<
    (status: "connecting" | "ready" | "disconnected") => void
  >();
  onEvent(fn: (event: CoreEvent) => void) {
    this.events.add(fn);
    return () => {
      this.events.delete(fn);
    };
  }
  onStatus(fn: (status: "connecting" | "ready" | "disconnected") => void) {
    this.statuses.add(fn);
    return () => {
      this.statuses.delete(fn);
    };
  }
  private status(status: "connecting" | "ready" | "disconnected") {
    this.statuses.forEach((fn) => fn(status));
  }
  connect(connection: Connection): Promise<void> {
    this.disconnect();
    const generation = ++this.generation;
    this.status("connecting");
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${connection.port}`);
      this.ws = ws;
      let welcomed = false;
      const timer = setTimeout(() => {
        ws.close();
        reject(
          new RpcError(
            "The core did not answer.",
            "Restart the core and try again.",
          ),
        );
      }, 10000);
      this.cancelConnect = () => {
        clearTimeout(timer);
        reject(new RpcError("Core connection was replaced."));
      };
      ws.onopen = () =>
        ws.send(
          JSON.stringify({
            type: "hello",
            token: connection.token,
            actor: "user",
          }),
        );
      ws.onmessage = (event) => {
        if (generation !== this.generation) return;
        let msg;
        try {
          msg = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (msg.type === "welcome") {
          welcomed = true;
          clearTimeout(timer);
          this.cancelConnect = undefined;
          this.status("ready");
          resolve();
          return;
        }
        if (typeof msg.id === "number") {
          const pending = this.pending.get(msg.id);
          if (!pending) return;
          this.pending.delete(msg.id);
          pending.cleanup();
          if (msg.error)
            pending.reject(
              new RpcError(
                msg.error.message,
                msg.error.data?.hint,
                msg.error.code,
              ),
            );
          else pending.resolve(msg.result);
        } else if (typeof msg.method === "string")
          this.events.forEach((fn) =>
            fn({ method: msg.method, params: msg.params ?? {} }),
          );
      };
      ws.onerror = () => {
        if (!welcomed) {
          clearTimeout(timer);
          reject(new RpcError("Could not connect to the core."));
        }
      };
      ws.onclose = () => {
        clearTimeout(timer);
        if (generation !== this.generation) return;
        this.cancelConnect = undefined;
        this.rejectPending();
        this.status("disconnected");
        if (!welcomed)
          reject(new RpcError("Core connection closed before authentication."));
      };
    });
  }
  request<K extends keyof MethodMap>(
    method: K,
    params?: MethodMap[K][0],
    signal?: AbortSignal,
  ): Promise<MethodMap[K][1]> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException("Request cancelled", "AbortError"));
        return;
      }
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(
          new RpcError(
            "The core is disconnected.",
            "Wait for it to reconnect, or restart it.",
          ),
        );
        return;
      }
      const id = ++this.next;
      const abort = () => {
        this.pending.delete(id);
        reject(new DOMException("Request cancelled", "AbortError"));
      };
      signal?.addEventListener("abort", abort, { once: true });
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        cleanup: () => signal?.removeEventListener("abort", abort),
      });
      try {
        this.ws.send(
          JSON.stringify({ jsonrpc: "2.0", id, method, params: params ?? {} }),
        );
      } catch (error) {
        this.pending.delete(id);
        signal?.removeEventListener("abort", abort);
        reject(error);
      }
    });
  }
  private rejectPending() {
    for (const p of this.pending.values()) {
      p.cleanup();
      p.reject(
        new RpcError(
          "The core disconnected while this action was running.",
          "Check the session before running the action again.",
        ),
      );
    }
    this.pending.clear();
  }
  disconnect() {
    ++this.generation;
    this.cancelConnect?.();
    this.cancelConnect = undefined;
    this.ws?.close();
    this.ws = undefined;
    this.rejectPending();
  }
}
export const rpc = new RpcClient();
