import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { WebSocket } from "ws";

export const root = path.resolve(import.meta.dirname, "../..");
export const python = process.env.BADSHOP_PYTHON ?? path.join(
  root, "core/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
export type Core = {
  port: number;
  token: string;
  folder: string;
  call: (method: string, params?: unknown) => Promise<unknown>;
};

async function deadline<T>(operation: Promise<T>, milliseconds: number, message: () => string) {
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(message())), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer!);
  }
}

/** One owned process and authenticated socket. Failed startup takes the same cleanup path. */
export async function startCore(folder: string, script = "") {
  await mkdir(folder, { recursive: true });
  let logs = "";
  const child = spawn(python, ["-m", "badshop.server", "serve"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: path.join(root, "core/src"),
      BADSHOP_CONFIG_DIR: path.join(folder, "config"),
      BADSHOP_FAKE_PROVIDER: script,
      BADSHOP_DATA_DIR: path.join(folder, "data"),
      BADSHOP_LOG_DIR: path.join(folder, "logs"),
      BADSHOP_OUT: path.join(folder, "exports"),
      XDG_CACHE_HOME: path.join(folder, "cache"),
      REMBG_HOME: path.join(folder, "models"),
      U2NET_HOME: path.join(folder, "models"),
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stderr.on("data", chunk => { logs = (logs + String(chunk)).slice(-1_000_000); });
  const exited = new Promise<void>(resolve => {
    child.once("exit", () => resolve());
    child.once("error", () => resolve());
  });
  let ws: WebSocket | undefined;
  const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  let next = 0;
  let closed = false;
  const close = async () => {
    if (closed) return;
    closed = true;
    for (const request of pending.values()) request.reject(new Error("Test core closed"));
    pending.clear();
    ws?.terminate();
    if (child.exitCode !== null || child.signalCode !== null || child.pid === undefined) return;
    child.stdin.end();
    try {
      // The server allows up to ten seconds for WebSocket close handshakes,
      // then joins the owned worker. Report a forced cleanup as a failure.
      await deadline(exited, 15000, () => `Core did not stop after EOF:\n${logs}`);
    } catch (error) {
      child.kill("SIGKILL");
      await deadline(exited, 5000, () => `Owned core ${child.pid} could not be stopped`);
      throw error;
    }
    if (child.exitCode !== 0) throw new Error(`Core exited ${child.exitCode}:\n${logs}`);
  };
  try {
    const reader = createInterface({ input: child.stdout });
    let connection: { port: number; token: string };
    try {
      const line = await deadline(new Promise<string>((resolve, reject) => {
        reader.once("line", resolve);
        child.once("error", reject);
        exited.then(() => reject(new Error(`Core exited during startup:\n${logs}`)));
      }), 20000, () => `Core startup timed out:\n${logs}`);
      connection = JSON.parse(line);
      if (!Number.isInteger(connection.port) || !connection.token) throw new Error("Invalid core startup record");
    } finally {
      reader.close();
    }
    ws = new WebSocket(`ws://127.0.0.1:${connection.port}`);
    const socket = ws;
    await deadline(new Promise<void>((resolve, reject) => {
      socket.once("open", () => socket.send(JSON.stringify({ type: "hello", token: connection.token, actor: "user" })));
      socket.once("message", data => {
        try {
          const message = JSON.parse(String(data));
          if (message.type !== "welcome" || message.actor !== "user") throw new Error("Core refused test authentication");
          resolve();
        } catch (error) { reject(error); }
      });
      socket.once("error", reject);
      socket.once("close", () => reject(new Error("Core closed during authentication")));
    }), 10000, () => `Core authentication timed out:\n${logs}`);
    const disconnected = () => {
      for (const request of pending.values()) request.reject(new Error(`Core disconnected:\n${logs}`));
      pending.clear();
    };
    socket.on("close", disconnected);
    socket.on("error", disconnected);
    socket.on("message", data => {
      const reply = JSON.parse(String(data));
      const request = pending.get(reply.id);
      if (!request) return;
      pending.delete(reply.id);
      if (reply.error) request.reject(new Error(JSON.stringify(reply.error)));
      else request.resolve(reply.result);
    });
    const call = async (method: string, params: unknown = {}) => {
      if (socket.readyState !== WebSocket.OPEN) throw new Error(`Core unavailable for ${method}`);
      const id = ++next;
      try {
        return await deadline(new Promise<unknown>((resolve, reject) => {
          pending.set(id, { resolve, reject });
          socket.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }), error => {
            if (error) reject(error);
          });
        }), 15000, () => `Core request ${method} timed out:\n${logs}`);
      } finally { pending.delete(id); }
    };
    return { ...connection, connection, folder, child, call, close, logs: () => logs };
  } catch (error) {
    await close().catch(() => {});
    throw error;
  }
}
