import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test, expect, python, root } from "./fixtures";
import type { Session } from "../src/types";

test("a nonportable remix explains why sharing is blocked and still exports the finished image", async ({ page, emptyCore }) => {
  const project = path.join(emptyCore.folder, "custom-font.badshop");
  // A project received from another computer can reference an unavailable font.
  // Its existing rendered pixels remain usable; editable remix must explain its refusal.
  execFileSync(python, ["-c", `
import sys
from pathlib import Path
from badshop.session.session import Session
from badshop.session import project
s = Session.new()
source = s.artifacts.add(Path(sys.argv[1]).read_bytes(), "original")
step = s.run_tool("text", {"image": source.id, "text": "A custom-font joke", "size": 20}, "user")
assert step.status == "done"
step.params["font"] = "/another-computer/private-font.ttf"
project.save(s, Path(sys.argv[2]))
`, path.join(root, "core/tests/fixtures/lincoln.png"), project], { env: { ...process.env,
    BADSHOP_DATA_DIR: path.join(emptyCore.folder, "fixture-data"),
    BADSHOP_CONFIG_DIR: path.join(emptyCore.folder, "fixture-config"),
  } });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.locator(".session-name").click();
  page.once("dialog", dialog => dialog.accept(project));
  await page.getByRole("button", { name: /^Open session/ }).click();
  await page.locator(".step").first().click();
  const saved = await emptyCore.call("session.get") as Session;
  const output = saved.steps[0].outputs[0];
  const pixels = await emptyCore.call("artifacts.get", { id: output }) as { data: string };
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByText("Let someone remix this", { exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("custom font");
  await expect(page.getByRole("button", { name: "Save editable remix" })).toBeDisabled();
  await page.getByRole("button", { name: "Save image file", exact: true }).click();
  const status = page.getByRole("status").filter({ hasText: "Exported to " });
  await expect(status).toBeVisible();
  expect(await readFile((await status.innerText()).replace("Exported to ", "").trim())).toEqual(Buffer.from(pixels.data, "base64"));
  expect((await emptyCore.call("session.get") as Session).steps).toEqual(saved.steps);
});
