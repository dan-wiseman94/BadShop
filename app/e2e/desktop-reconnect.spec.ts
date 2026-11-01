import { test, expect, root } from "./fixtures";
import type { WebSocketRoute } from "@playwright/test";
import type { Session } from "../src/types";
import path from "node:path";

test("temporary socket loss preserves unsent messages, attachments, selected images and parameter drafts", async ({
  page,
  core,
}) => {
  const session = (await core.call("session.get")) as Session;
  const image = Object.keys(session.artifacts)[0];
  await core.call("tools.run", {
    tool: "deepfry",
    params: { image, seed: 7, level: 1 },
  });
  let first: WebSocketRoute | undefined;
  let connections = 0;
  await page.routeWebSocket(`ws://127.0.0.1:${core.port}/`, (client) => {
    connections += 1;
    client.connectToServer();
    first ??= client;
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.locator(".step").click();
  await page
    .locator(".step-detail")
    .getByLabel("Seed", { exact: false })
    .fill("99");
  await page
    .getByLabel("Import image files")
    .setInputFiles(path.join(root, "core/tests/fixtures/trump.png"));
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await page
    .getByLabel("Message your agent")
    .fill("Unsent draft after reconnect");
  await first!.close({ code: 1012, reason: "isolated reconnect regression" });
  await expect(page.getByText("The core connection was lost.")).toBeVisible();
  await expect(page.locator(".workbench")).toBeHidden();
  await expect.poll(() => connections).toBeGreaterThan(1);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Message your agent")).toHaveValue(
    "Unsent draft after reconnect",
  );
  await expect(
    page.locator(".step-detail").getByLabel("Seed", { exact: false }),
  ).toHaveValue("99");
  await expect(page.locator(".attachments img")).toHaveCount(1);
  await expect(page.locator(".canvas-image")).toHaveAttribute(
    "alt",
    /trump_work/,
  );
  expect(
    ((await core.call("session.get")) as Session).steps[0].params.seed,
  ).toBe(7);
});

async function startRecoveryCore(folder: string) {
  const { spawn } = await import("node:child_process");
  const { createInterface } = await import("node:readline");
  const child = spawn(
    path.join(root, "core/.venv/bin/python"),
    ["-m", "badshop.server", "serve"],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: path.join(root, "core/src"),
        BADSHOP_CONFIG_DIR: path.join(folder, "config"),
        BADSHOP_DATA_DIR: path.join(folder, "data"),
        BADSHOP_LOG_DIR: path.join(folder, "logs"),
        XDG_CACHE_HOME: path.join(folder, "cache"),
        BADSHOP_FAKE_PROVIDER: "",
        BADSHOP_OUT: folder,
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  const logs: string[] = [];
  child.stderr.on("data", (chunk) => logs.push(String(chunk)));
  const connection = await new Promise<{ port: number; token: string }>(
    (resolve, reject) => {
      const timer = setTimeout(
        () =>
          reject(
            new Error(`Recovery core startup timed out: ${logs.join("")}`),
          ),
        20000,
      );
      createInterface({ input: child.stdout }).once("line", (line) => {
        clearTimeout(timer);
        resolve(JSON.parse(line));
      });
      child.once("exit", (code) =>
        reject(new Error(`Recovery core exited ${code}: ${logs.join("")}`)),
      );
    },
  );
  return {
    connection,
    child,
    async close() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      child.stdin.end();
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          resolve();
        }, 3000);
        child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    },
  };
}

for (const outcome of ["restored", "damaged", "older"] as const) {
  test(`real core restart ${outcome} recovery preserves drafts until its outcome and only prunes missing references`, async ({
    page,
    core,
  }) => {
    const { readFile, writeFile } = await import("node:fs/promises");
    const folder = path.join(core.folder, "restarting-core");
    const autosave = path.join(folder, "data/autosave/session.badshop");
    const owned: Awaited<ReturnType<typeof startRecoveryCore>>[] = [];
    let restoreReply: string | Buffer | undefined;
    let releaseReply = () => {};
    let hold = false;
    await page.routeWebSocket(/ws:\/\/127\.0\.0\.1:\d+\//, (client) => {
      const server = client.connectToServer();
      let restoreId: number | undefined;
      client.onMessage((frame) => {
        const message = JSON.parse(String(frame));
        if (message.method === "session.restore") restoreId = message.id;
        server.send(frame);
      });
      server.onMessage((frame) => {
        const message = JSON.parse(String(frame));
        if (hold && restoreId !== undefined && message.id === restoreId) {
          restoreReply = frame;
          releaseReply = () => {
            hold = false;
            client.send(frame);
          };
        } else client.send(frame);
      });
    });
    try {
      const first = await startRecoveryCore(folder);
      owned.push(first);
      await page.addInitScript(() =>
        localStorage.setItem("badshop.welcome", "1"),
      );
      await page.goto(
        `/?core_port=${first.connection.port}&core_token=${first.connection.token}`,
      );
      await expect(page.getByText("Connected", { exact: true })).toBeVisible();
      await page
        .getByLabel("Import image files")
        .setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
      await expect(page.locator(".attachments img")).toHaveCount(1);
      const olderSave = await readFile(autosave);
      await page.getByRole("button", { name: "Run tool", exact: true }).click();
      await page.getByLabel("Search tools").fill("deepfry");
      await page.getByRole("button", { name: /^deepfry / }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Run tool", exact: true })
        .click();
      await expect(page.locator(".step-detail")).toBeVisible();
      await page
        .locator(".step-detail")
        .getByLabel("Seed", { exact: false })
        .fill("99");
      await page
        .getByLabel("Import image files")
        .setInputFiles(path.join(root, "core/tests/fixtures/trump.png"));
      await expect(page.locator(".attachments img")).toHaveCount(2);
      await page
        .getByLabel("Message your agent")
        .fill("Draft survives real core recovery");
      first.child.kill("SIGKILL");
      await expect(
        page.getByText("The core connection was lost."),
      ).toBeVisible();
      if (outcome === "damaged")
        await writeFile(autosave, "damaged recovery fixture");
      if (outcome === "older") await writeFile(autosave, olderSave);
      hold = true;
      const second = await startRecoveryCore(folder);
      owned.push(second);
      await page.evaluate(
        (connection) =>
          history.replaceState(
            null,
            "",
            `/?core_port=${connection.port}&core_token=${connection.token}`,
          ),
        second.connection,
      );
      await expect.poll(() => restoreReply !== undefined).toBe(true);
      await expect(page.getByLabel("Message your agent")).toHaveValue(
        "Draft survives real core recovery",
      );
      await expect(page.locator(".attachments img")).toHaveCount(2);
      await expect(
        page.locator(".step-detail").getByLabel("Seed", { exact: false }),
      ).toHaveValue("99");
      // Even an authenticated socket cannot save a pristine startup snapshot during recovery.
      await page.keyboard.press("Control+S");
      await expect(page.getByRole("alert")).toContainText(
        "Wait for the core to reconnect",
      );
      releaseReply();
      if (outcome === "damaged") {
        await expect(page.getByRole("alert")).toContainText(
          /damaged|isn't a badshop project/,
          { timeout: 15000 },
        );
        await expect(
          page.getByText("The core connection was lost."),
        ).toBeVisible();
        await expect(page.locator(".workbench")).toBeHidden();
        await expect(page.locator(".attachments img")).toHaveCount(2);
        await expect(
          page.locator(".step-detail").getByLabel("Seed", { exact: false }),
        ).toHaveValue("99");
      } else {
        await expect(
          page.getByText("Connected", { exact: true }),
        ).toBeVisible();
        await expect(page.locator(".attachments img")).toHaveCount(
          outcome === "older" ? 1 : 2,
        );
        if (outcome === "older") {
          await expect(page.locator(".step-detail")).toHaveCount(0);
          await expect(page.locator(".canvas-image")).toHaveAttribute(
            "alt",
            /lincoln_work/,
          );
        } else {
          await expect(
            page.locator(".step-detail").getByLabel("Seed", { exact: false }),
          ).toHaveValue("99");
          await expect(page.locator(".canvas-image")).toHaveAttribute(
            "alt",
            /trump_work/,
          );
        }
      }
      await expect(page.getByLabel("Message your agent")).toHaveValue(
        "Draft survives real core recovery",
      );
    } finally {
      for (const child of owned) await child.close();
    }
  });
}

for (const persisted of [false, true]) {
  test(`real core restart with no autosave ${persisted ? "reports missing persisted content without discarding it" : "retains a pristine document's typed-only draft"}`, async ({
    page,
    core,
  }) => {
    const { rm } = await import("node:fs/promises");
    const folder = path.join(core.folder, "no-autosave-core");
    const owned: Awaited<ReturnType<typeof startRecoveryCore>>[] = [];
    try {
      const first = await startRecoveryCore(folder);
      owned.push(first);
      await page.addInitScript(() =>
        localStorage.setItem("badshop.welcome", "1"),
      );
      await page.goto(
        `/?core_port=${first.connection.port}&core_token=${first.connection.token}`,
      );
      await expect(page.getByText("Connected", { exact: true })).toBeVisible();
      if (persisted) {
        await page
          .getByLabel("Import image files")
          .setInputFiles(path.join(root, "core/tests/fixtures/lincoln.png"));
        await expect(page.locator(".attachments img")).toHaveCount(1);
      }
      await page
        .getByLabel("Message your agent")
        .fill("Typed draft without a recovery file");
      first.child.kill("SIGKILL");
      await expect(
        page.getByText("The core connection was lost."),
      ).toBeVisible();
      await rm(path.join(folder, "data/autosave/session.badshop"), {
        force: true,
      });
      const second = await startRecoveryCore(folder);
      owned.push(second);
      await page.evaluate(
        (connection) =>
          history.replaceState(
            null,
            "",
            `/?core_port=${connection.port}&core_token=${connection.token}`,
          ),
        second.connection,
      );
      if (persisted) {
        await expect(page.getByRole("alert")).toContainText(
          /no autosaved session/i,
          { timeout: 15000 },
        );
        await expect(page.locator(".workbench")).toBeHidden();
        await expect(page.locator(".attachments img")).toHaveCount(1);
      } else {
        await expect(
          page.getByText("Connected", { exact: true }),
        ).toBeVisible();
        await expect(page.locator(".attachments img")).toHaveCount(0);
      }
      await expect(page.getByLabel("Message your agent")).toHaveValue(
        "Typed draft without a recovery file",
      );
    } finally {
      for (const child of owned) await child.close();
    }
  });
}
