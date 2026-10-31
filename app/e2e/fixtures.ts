import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { WebSocket } from "ws";
export type Core = {
  port: number;
  token: string;
  folder: string;
  call: (method: string, params?: unknown) => Promise<unknown>;
};
export const root = path.resolve(import.meta.dirname, "../..");
export const test = base.extend<{ core: Core }>({
  core: async ({}, use) => {
    const folder = await mkdtemp(path.join(tmpdir(), "badshop-e2e-"));
    const script = path.join(folder, "script.json");
    const logs: string[] = [];
    const child = spawn(
      process.env.BADSHOP_PYTHON ?? path.join(root, "core/.venv/bin/python"),
      ["-m", "badshop.server", "serve"],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: path.join(root, "core/src"),
          BADSHOP_CONFIG_DIR: path.join(folder, "config"),
          BADSHOP_FAKE_PROVIDER: script,
          XDG_DATA_HOME: path.join(folder, "data"),
          XDG_CACHE_HOME: path.join(folder, "cache"),
        },
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    const line = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`Core failed to start: ${logs.join("")}`)),
        20000,
      );
      createInterface({ input: child.stdout }).once("line", (line) => {
        clearTimeout(timer);
        resolve(line);
      });
      child.once("exit", (code) =>
        reject(new Error(`Core exited ${code}: ${logs.join("")}`)),
      );
    });
    const connection = JSON.parse(line) as { port: number; token: string };
    const ws = new WebSocket(`ws://127.0.0.1:${connection.port}`);
    await new Promise<void>((resolve, reject) => {
      ws.on("open", () =>
        ws.send(
          JSON.stringify({
            type: "hello",
            token: connection.token,
            actor: "user",
          }),
        ),
      );
      ws.once("message", () => resolve());
      ws.once("error", reject);
    });
    let next = 0;
    const call = (method: string, params: unknown = {}) =>
      new Promise<unknown>((resolve, reject) => {
        const id = ++next;
        const handler = (data: WebSocket.RawData) => {
          const reply = JSON.parse(String(data));
          if (reply.id !== id) return;
          ws.off("message", handler);
          if (reply.error) reject(new Error(JSON.stringify(reply.error)));
          else resolve(reply.result);
        };
        ws.on("message", handler);
        ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
      });
    const imported = (await call("artifacts.import", {
      path: path.join(root, "core/tests/fixtures/lincoln.png"),
    })) as { working: { id: string } };
    await writeFile(
      script,
      JSON.stringify([
        {
          text: "A little controlled destruction.",
          tool_calls: [
            {
              name: "deepfry",
              arguments: { image: imported.working.id, seed: 7, level: 2 },
            },
          ],
        },
        { text: "The pixels are thoroughly questionable." },
      ]),
    );
    await call("settings.set", { values: { output_dir: folder } });
    try {
      await use({ ...connection, folder, call });
    } finally {
      ws.close();
      child.stdin.end();
      await new Promise<void>((resolve) => {
        child.once("exit", () => resolve());
        setTimeout(() => {
          child.kill("SIGKILL");
          resolve();
        }, 3000);
      });
      await rm(folder, { recursive: true, force: true });
    }
  },
});

export { expect };
