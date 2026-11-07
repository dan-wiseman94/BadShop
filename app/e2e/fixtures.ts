import { test as base, expect, type TestInfo } from "@playwright/test";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { startCore, root, type Core } from "./core";
export { root, python, startCore, type Core } from "./core";

type RunningCore = Awaited<ReturnType<typeof startCore>>;

async function withCore(use: (core: RunningCore) => Promise<void>, info: TestInfo, seed: boolean) {
  const folder = await mkdtemp(path.join(tmpdir(), "badshop-e2e-"));
  let core: RunningCore | undefined;
  try {
    const script = path.join(folder, "script.json");
    await writeFile(script, "[]");
    core = await startCore(folder, script);
    if (seed) {
      const imported = await core.call("artifacts.import", {
        path: path.join(root, "core/tests/fixtures/lincoln.png"),
      }) as { working: { id: string } };
      await writeFile(script, JSON.stringify([
        { text: "A little controlled destruction.", tool_calls: [
          { name: "deepfry", arguments: { image: imported.working.id, seed: 7, level: 2 } },
        ] },
        { text: "The pixels are thoroughly questionable." },
      ]));
    }
    await core.call("settings.set", { values: { output_dir: folder } });
    await use(core);
  } finally {
    try {
      await core?.close();
    } finally {
      if (core) await info.attach("core.log", { body: core.logs(), contentType: "text/plain" });
      await rm(folder, { recursive: true, force: true });
    }
  }
}

export const test = base.extend<{ core: Core; emptyCore: RunningCore; browserErrors: void }>({
  core: async ({}, use, info) => withCore(use, info, true),
  emptyCore: async ({}, use, info) => withCore(use, info, false),
  browserErrors: [async ({ context }, use) => {
    const errors: string[] = [];
    context.on("page", page => page.on("pageerror", error => errors.push(error.message)));
    await use();
    expect(errors, "Unhandled browser exceptions").toEqual([]);
  }, { auto: true }],
});
export { expect };
