import type { Connection, CoreEvent, MethodMap } from "./types";
import { GLOBAL_EVENTS, PROTOCOL_VERSION, WIRE_SCHEMAS } from "./wire.generated";
import type { DocumentContext } from "./wire.generated";
import { counter, documentContext, object, parseFrame, validPayload } from "./protocol";
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
  method: keyof MethodMap;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  cleanup: () => void;
};
export class RpcClient {
  private ws?: WebSocket;
  private authenticated = false;
  private pending = new Map<number, Pending>();
  private next = 0;
  private generation = 0;
  coreInstanceId?: string;
  private eventSequence = 0;
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
      const current = () => generation === this.generation && this.ws === ws;
      const end = (error: RpcError) => {
        if (!current()) return;
        console.warn(`Core connection ended: ${error.message}`);
        clearTimeout(timer);
        ++this.generation; // buffered callbacks from a closing socket are obsolete
        this.ws = undefined;
        this.authenticated = false;
        this.cancelConnect = undefined;
        this.rejectPending();
        reject(error);
        ws.close();
        this.status("disconnected");
      };
      const timer = setTimeout(() => {
        end(
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
      ws.onopen = () => {
        if (!current()) return;
        ws.send(
          JSON.stringify({
            type: "hello",
            token: connection.token,
            actor: "user",
            protocol: PROTOCOL_VERSION,
          }),
        );
      };
      ws.onmessage = (event) => {
        if (!current()) return;
        let msg;
        try {
          msg = parseFrame(event.data);
        } catch {
          end(new RpcError("Invalid core response.", "Restart the core; check the session before repeating an action."));
          return;
        }
        if (msg.type === "welcome" && !welcomed) {
          if (msg.protocol !== PROTOCOL_VERSION || typeof msg.core_instance_id !== "string" ||
              typeof msg.build_id !== "string" || !counter(msg.event_seq)) {
            end(new RpcError("Incompatible core protocol.", "Update the app and core together."));
            return;
          }
          this.coreInstanceId = msg.core_instance_id;
          this.eventSequence = msg.event_seq;
          welcomed = true;
          this.authenticated = true;
          clearTimeout(timer);
          this.cancelConnect = undefined;
          this.status("ready");
          resolve();
          return;
        }
        if (!welcomed) return;
        if (msg.jsonrpc !== "2.0") {
          end(new RpcError("Invalid JSON-RPC response."));
          return;
        }
        if (typeof msg.id === "number") {
          const pending = this.pending.get(msg.id);
          if (!pending) return;
          this.pending.delete(msg.id);
          pending.cleanup();
          if (msg.error && object(msg.error) && typeof msg.error.message === "string" &&
              typeof msg.error.code === "number")
            pending.reject(
              new RpcError(
                msg.error.message,
                object(msg.error.data) && typeof msg.error.data.hint === "string" ? msg.error.data.hint : undefined,
                msg.error.code,
              ),
            );
          else if (!msg.error && "result" in msg) {
            if (!validPayload("result", pending.method, msg.result))
              pending.reject(new RpcError("Malformed core result.", "Check the session before repeating this action."));
            else if (object(msg.result) && "context" in msg.result &&
                (!documentContext(msg.result.context) || msg.result.context.core_instance_id !== this.coreInstanceId))
              pending.reject(new RpcError("The response belongs to an invalid core or document."));
            else pending.resolve(msg.result);
          } else pending.reject(new RpcError("Malformed core result.", "Check the session before repeating this action."));
        } else if (typeof msg.method === "string") {
          if (!object(msg.params) || msg.core_instance_id !== this.coreInstanceId || !counter(msg.event_seq) ||
              (!GLOBAL_EVENTS.includes(msg.method) && (!documentContext(msg.context) ||
                msg.context.core_instance_id !== this.coreInstanceId || msg.context.event_seq !== msg.event_seq))) {
            end(new RpcError("Invalid core event ownership."));
            return;
          }
          if (msg.event_seq <= this.eventSequence) return;
          const gap = msg.event_seq !== this.eventSequence + 1;
          this.eventSequence = msg.event_seq;
          if (gap) {
            this.events.forEach(fn => fn({ method: "core.resync", params: {} }));
            return;
          }
          if (!validPayload("event", msg.method, msg.params)) {
            end(new RpcError("Malformed core event.", "Reconnect to refresh the current session."));
            return;
          }
          const notification: CoreEvent = { method: msg.method, params: msg.params,
            core_instance_id: msg.core_instance_id as string, event_seq: msg.event_seq,
            ...(documentContext(msg.context) ? { context: msg.context } : {}) };
          this.events.forEach(fn => fn(notification));
        }
      };
      ws.onerror = () => {
        end(new RpcError("Could not connect to the core."));
      };
      ws.onclose = () => {
        end(new RpcError("Core connection closed before authentication."));
      };
    });
  }
  request<K extends keyof MethodMap>(
    method: K,
    params?: MethodMap[K][0],
    signal?: AbortSignal,
    context?: DocumentContext,
  ): Promise<MethodMap[K][1]> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException("Request cancelled", "AbortError"));
        return;
      }
      if (!this.authenticated || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
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
        method,
        resolve: resolve as (value: unknown) => void,
        reject,
        cleanup: () => signal?.removeEventListener("abort", abort),
      });
      try {
        this.ws.send(
          JSON.stringify({ jsonrpc: "2.0", id, method, params: params ?? {},
            ...(context && WIRE_SCHEMAS.methods[method].scope === "document" ? { context } : {}) }),
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
    this.authenticated = false;
    this.coreInstanceId = undefined;
    this.cancelConnect?.();
    this.cancelConnect = undefined;
    this.ws?.close();
    this.ws = undefined;
    this.rejectPending();
  }
}
export const rpc = new RpcClient();
