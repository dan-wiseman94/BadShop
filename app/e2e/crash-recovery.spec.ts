import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test, expect, root, python, startCore } from "./fixtures";
import type { Session } from "../src/types";

test("a killed core restores unsaved pixels through project home and saves a reusable project", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await page.getByLabel("Import image files").setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
  await page.getByRole("button", { name: /A deeply useless trading card/ }).click();
  await page.getByLabel("Headline", { exact: true }).fill("Unsaved masterpiece");
  await page.getByRole("button", { name: "Make this shitpost" }).click();
  await expect.poll(async () => (await emptyCore.call("session.get") as Session).steps[0]?.status).toBe("done");
  const before = await emptyCore.call("session.get") as Session;
  const output = before.steps[0].outputs[0];
  const pixels = await emptyCore.call("artifacts.get", { id: output }) as { data: string };
  const autosave = path.join(emptyCore.folder, "data/autosave/session.badshop");
  await expect.poll(() => {
    try {
      const saved = JSON.parse(execFileSync(python, ["-c",
        "import json,sys,zipfile; print(zipfile.ZipFile(sys.argv[1]).read('session.json').decode())", autosave], { encoding: "utf8" })) as Session;
      return saved.steps[0]?.outputs[0];
    } catch { return null; } // Atomic autosave may not have completed yet.
  }).toBe(output);
  const workers = JSON.parse(execFileSync(python, ["-c",
    "import json,psutil,sys; print(json.dumps([p.pid for p in psutil.Process(int(sys.argv[1])).children(recursive=True)]))",
    String(emptyCore.child.pid)], { encoding: "utf8" })) as number[];
  const exited = new Promise<void>(resolve => emptyCore.child.once("exit", () => resolve()));
  emptyCore.child.kill("SIGKILL");
  await exited;
  await emptyCore.close();
  await expect.poll(() => JSON.parse(execFileSync(python, ["-c",
    "import json,psutil,sys; ids=json.loads(sys.argv[1]); print(json.dumps([p.pid for p in psutil.process_iter(['status']) if p.pid in ids and p.info['status'] != psutil.STATUS_ZOMBIE]))",
    JSON.stringify(workers)], { encoding: "utf8" }))).toEqual([]);
  const recovered = await startCore(emptyCore.folder);
  try {
    await page.goto(`/?core_port=${recovered.port}&core_token=${recovered.token}`);
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    await page.getByRole("button", { name: "Recover autosaved project", exact: true }).click();
    await expect.poll(async () => (await recovered.call("session.get") as Session).id).toBe(before.id);
    const restored = await recovered.call("session.get") as Session;
    expect(restored.steps).toEqual(before.steps);
    expect(restored.unsaved_changes).toBe(true);
    expect(await recovered.call("artifacts.get", { id: output })).toEqual(pixels);
    await expect(page.getByLabel("Revised punchline")).toBeVisible();
    const project = path.join(emptyCore.folder, "recovered.badshop");
    page.once("dialog", dialog => dialog.accept(project));
    await page.getByRole("button", { name: "Save session", exact: true }).click();
    await expect.poll(async () => (await recovered.call("session.get") as Session).unsaved_changes).toBe(false);
    expect((await readFile(project)).subarray(0, 2).toString()).toBe("PK");
    await page.getByRole("button", { name: "Export image", exact: true }).click();
    await page.getByRole("button", { name: "Save image file", exact: true }).click();
    const status = page.getByRole("status").filter({ hasText: "Exported to " });
    await expect(status).toBeVisible();
    const filename = (await status.innerText()).replace("Exported to ", "").trim();
    expect(await readFile(filename)).toEqual(Buffer.from(pixels.data, "base64"));
    await page.goto("about:blank");
  } finally { await recovered.close(); }
});
