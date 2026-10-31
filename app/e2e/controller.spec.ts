import { test, expect, root } from "./fixtures";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
test("chat, approval, edit, replay, save, open, manual tools and export use the real core", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("badshop.welcome", "1");
    localStorage.setItem("badshop.theme", "dark");
  });
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("Deep fry Lincoln.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Your call", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(
    page.getByText("The pixels are thoroughly questionable."),
  ).toBeVisible();
  const steps = page.getByRole("region", { name: "Steps timeline" });
  await steps.getByRole("button").filter({ hasText: "deepfry" }).click();
  await expect(
    steps.getByRole("button", { name: "Apply & replay" }),
  ).toBeVisible();
  const seed = steps.getByLabel("Seed", { exact: false });
  await seed.fill("11");
  await steps.getByRole("button", { name: "Apply & replay" }).click();
  await expect(steps.getByText("edited", { exact: true })).toBeVisible();
  await steps.getByRole("button", { name: "Replay from here" }).click();
  await page
    .getByRole("button", { name: "Coordinate grid", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Coordinate grid" }),
  ).toHaveAttribute("aria-pressed", "true");
  const project = path.join(core.folder, "test.badshop");
  page.once("dialog", (dialog) => dialog.accept(project));
  await page.getByRole("button", { name: "Save session", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Saved to");
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByRole("textbox", { name: "Search tools" }).fill("info");
  await page.getByRole("button", { name: /info print an image/ }).click();
  await page
    .getByRole("button", { name: "Run tool", exact: true })
    .last()
    .click();
  await expect(
    steps.getByRole("button").filter({ hasText: "info" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Exported to");
  await page.getByRole("button", { name: "Untitled" }).click();
  page.once("dialog", (dialog) => dialog.accept(project));
  await page
    .getByRole("button", { name: "Open session", exact: false })
    .click();
  await page
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(
    steps.getByRole("button").filter({ hasText: "info" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("The pixels are thoroughly questionable."),
  ).toBeVisible();
  await page.locator(".step").first().click();
  const toast = page.getByRole("button", { name: "Dismiss notification" });
  if (await toast.isVisible()) await toast.click();
  await mkdir(path.join(root, "docs/screenshots"), { recursive: true });
  await page.screenshot({
    path: path.join(root, "docs/screenshots/badshop.png"),
  });
  const errors = await page.evaluate(
    () => document.querySelectorAll(".error-banner").length,
  );
  expect(errors).toBe(0);
});
test("imports files, opens settings, saves a local profile, and selects it", async ({
  page,
  core,
}) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByLabel("Import image files")
    .setInputFiles(path.join(root, "core/tests/fixtures/trump.png"));
  await expect(page.locator(".attachments .artifact-thumb")).toHaveCount(1);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Add provider" }).click();
  await page.getByLabel("Provider type").selectOption("local");
  await page.getByLabel("Profile name").fill("My local vision");
  await page.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await page.getByRole("button", { name: "Save provider" }).click();
  await expect(
    page.getByText("My local vision", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Active", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(page.getByLabel("Active provider")).toContainText(
    "My local vision",
  );
});

test("first run reaches manual tools and Stop settles a waiting approval", async ({
  page,
  core,
}) => {
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(
    page.getByRole("dialog", { name: "Welcome to badshop" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Set up later/ }).click();
  await page.getByLabel("Message your agent").fill("Deep fry this.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Your call", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.getByText("Your call", { exact: true })).toHaveCount(0);
  await expect(page.getByText("rejected", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send message" }),
  ).toBeVisible();
});

test("rejects an agent proposal with a note and exposes provider failures for retry", async ({
  page,
  core,
}) => {
  // Let a real session snapshot overtake the final notification, as in the CI race.
  let completionHeld = false;
  const withheld: (string | Buffer)[] = [];
  let releaseCompletion = () => {};
  await page.routeWebSocket(`ws://127.0.0.1:${core.port}/`, (client) => {
    const server = client.connectToServer();
    releaseCompletion = () => {
      completionHeld = false;
      for (const frame of withheld.splice(0)) client.send(frame);
    };
    server.onMessage((frame) => {
      const message = JSON.parse(String(frame));
      if (
        message.method === "message.done" &&
        message.params?.message?.role === "assistant" &&
        message.params.message.content.some(
          (part: { text?: string }) => part.text === "Ready after retry.",
        )
      )
        completionHeld = true;
      if (completionHeld && message.method) {
        withheld.push(frame);
        return;
      }
      client.send(frame);
    });
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByLabel("Message your agent").fill("Try this.");
  await page.getByRole("button", { name: "Send message" }).click();
  await page
    .getByLabel("Rejection note for s1")
    .fill("Keep the original colors");
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(
    page.getByText("The pixels are thoroughly questionable."),
  ).toBeVisible();
  await expect(page.getByText("rejected", { exact: true })).toBeVisible();
  const script = path.join(core.folder, "failure.json");
  await writeFile(
    script,
    JSON.stringify([
      { error: "Provider rate limit reached" },
      { text: "Ready after retry." },
    ]),
  );
  await core.call("settings.set", { values: { fake_provider_script: script } });
  await page.getByLabel("Message your agent").fill("Try again.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Provider rate limit reached",
  );
  await page
    .getByRole("alert")
    .getByRole("button", { name: "Retry turn" })
    .click();
  await expect.poll(() => completionHeld).toBe(true);
  await page.getByLabel("Approval mode").selectOption("auto");
  await expect(
    page
      .locator(".message.assistant:not(.streaming)")
      .filter({ hasText: "Ready after retry." }),
  ).toHaveCount(1);
  await expect(page.getByText("Ready after retry.")).toBeVisible();
  releaseCompletion();
  await expect(page.getByText("Ready after retry.")).toHaveCount(1);
});

test("manual coordinate picking reaches the viewer and restores the form", async ({
  page,
  context,
  core,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("cutout");
  await page.getByRole("button", { name: /^cutout crop/ }).click();
  const dialog = page.getByRole("dialog", { name: "Run a tool" });
  await dialog
    .getByRole("button", { name: "Pick on image", exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  const image = page.locator(".image-surface");
  const box = (await image.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.7);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.up();
  await expect(dialog).toBeVisible();
  const x1 = Number(
    await dialog.getByLabel("Box X1", { exact: true }).inputValue(),
  );
  const x2 = Number(
    await dialog.getByLabel("Box X2", { exact: true }).inputValue(),
  );
  expect(x1).toBeLessThan(x2);
  await dialog.getByLabel("No Ai", { exact: false }).check();
  await dialog.getByRole("button", { name: "Run tool", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Steps timeline" })
      .getByRole("button")
      .filter({ hasText: "cutout" })
      .first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Copy CLI command" }).click();
  await expect(page.getByRole("status")).toContainText("CLI command copied");
  const command = await page.evaluate(() => navigator.clipboard.readText());
  const { execFileSync } = await import("node:child_process");
  const parsed = JSON.parse(
    execFileSync(
      process.env.BADSHOP_PYTHON ?? path.join(root, "core/.venv/bin/python"),
      [
        "-c",
        "import sys,shlex,json; from badshop.cli.main import build_parser; print(json.dumps(vars(build_parser().parse_args(shlex.split(sys.argv[1])[1:])),default=str))",
        command,
      ],
      { env: { ...process.env, PYTHONPATH: path.join(root, "core/src") } },
    ).toString(),
  ) as { box: number[] };
  expect(parsed.box[0]).toBe(x1);
  expect(parsed.box[2]).toBe(x2);
});

test("exports the output of an older selected step", async ({ page, core }) => {
  const snapshot = (await core.call("session.get")) as {
    artifacts: Record<string, unknown>;
  };
  const image = Object.keys(snapshot.artifacts)[0];
  const first = (await core.call("tools.run", {
    tool: "deepfry",
    params: { image, level: 1, seed: 1 },
  })) as { outputs: string[] };
  await core.call("tools.run", {
    tool: "deepfry",
    params: { image, level: 4, seed: 2 },
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.locator(".step").first().click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Exported to");
  const file = await page.getByRole("status").innerText();
  const exportedPath = file.replace("Exported to ", "").trim();
  const { readFile } = await import("node:fs/promises");
  const expected = (await core.call("artifacts.get", {
    id: first.outputs[0],
  })) as { data: string };
  expect((await readFile(exportedPath)).toString("base64")).toBe(expected.data);
});

test("changes a profile from CLI to local and back without incompatible fields", async ({
  page,
  core,
}) => {
  await core.call("providers.save", {
    profile: {
      id: "switchable",
      kind: "cli",
      cli: "claude",
      label: "Switchable",
      model: "",
    },
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Provider type").selectOption("local");
  await page.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await page.getByLabel("Credential storage").selectOption("environment");
  await page.getByLabel("Environment variable name").fill("TEST_MODEL_KEY");
  await page.getByRole("button", { name: "Save provider" }).click();
  await expect(page.getByText("Switchable", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Provider type").selectOption("cli");
  await page.getByRole("button", { name: "Save provider" }).click();
  await expect(page.getByText("Switchable", { exact: true })).toBeVisible();
  const profiles = (await core.call("providers.list")) as {
    kind: string;
    cli: string;
    api_key_env: unknown;
    api_base: unknown;
  }[];
  expect(profiles[0]).toMatchObject({
    kind: "cli",
    cli: "claude",
    api_key_env: null,
    api_base: null,
  });
});

test("production assets and generated forms run under the packaged content security policy", async ({
  page,
  context,
  core,
}) => {
  await context.grantPermissions(["local-network-access"], {
    origin: "http://127.0.0.1:1420",
  });
  const { readFile } = await import("node:fs/promises");
  const config = JSON.parse(
    await readFile(path.join(root, "app/src-tauri/tauri.conf.json"), "utf8"),
  ) as { app: { security: { csp: string } } };
  await page.route("**/production/**", async (route) => {
    const relative = new URL(route.request().url()).pathname.replace(
      "/production/",
      "",
    );
    const file = relative || "index.html";
    let body = await readFile(path.join(root, "app/dist", file));
    if (file === "index.html")
      body = Buffer.from(
        body.toString().replaceAll("/assets/", "/production/assets/"),
      );
    await route.fulfill({
      body,
      headers: {
        "Content-Security-Policy": config.app.security.csp,
        "Content-Type": file.endsWith(".js")
          ? "text/javascript"
          : file.endsWith(".css")
            ? "text/css"
            : "text/html",
      },
    });
  });
  await page.addInitScript(
    (connection) => {
      localStorage.setItem("badshop.welcome", "1");
      Object.assign(window, {
        isTauri: true,
        __TAURI_INTERNALS__: {
          invoke: async (command: string) =>
            command === "core_connection" ? connection : 1,
          transformCallback: () => 1,
          unregisterCallback: () => {},
          metadata: {
            currentWindow: { label: "main" },
            currentWebview: { label: "main" },
          },
        },
        __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} },
      });
    },
    { port: core.port, token: core.token },
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/production/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("info");
  await page.getByRole("button", { name: /^info print/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Run tool", exact: true })
    .click();
  await expect(page.locator(".step").filter({ hasText: "info" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("image parameter pickers offer working copies and exclude provenance originals", async ({
  page,
  core,
}) => {
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1600;
    canvas.height = 1200;
    canvas.getContext("2d")!.fillRect(0, 0, 1600, 1200);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  await core.call("artifacts.import", { data, name: "large.png" });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run tool", exact: true }).click();
  await page.getByLabel("Search tools").fill("info");
  await page.getByRole("button", { name: /^info print/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("option", { name: /large_work \(1000 × 750\)/ }),
  ).toHaveCount(1);
  await expect(dialog.getByRole("option", { name: /1600 × 1200/ })).toHaveCount(
    0,
  );
});

test("provider capability tests show the JSON tool fallback warning", async ({
  page,
  core,
}) => {
  await core.call("providers.save", {
    profile: {
      kind: "local",
      label: "JSON fallback",
      model: "ollama_chat/llava",
      capability_overrides: { vision: true, tool_calls: false },
    },
  });
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${core.port}&core_token=${core.token}`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Check setup", exact: true }).click();
  await expect(
    page.getByText(/JSON-mode tool fallback is active/),
  ).toBeVisible();
});
