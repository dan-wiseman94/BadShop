import { readFile } from "node:fs/promises";
import path from "node:path";
import { test, expect, startCore } from "./fixtures";
import type { Asset, Profile, Session } from "../src/types";

for (const [label, kind, model] of [
  ["Cloud API", "api", "openai/gpt-4.1-mini"],
  ["Local model", "local", "ollama_chat/llava"],
  ["Custom endpoint", "openai_compatible", "openai/local-vision"],
  ["CLI subscription", "cli", ""],
] as const) {
  test(`${label} onboarding saves the choice and opens the AI workspace`, async ({ page, emptyCore }, info) => {
    await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
    const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
    await welcome.getByRole("button", { name: new RegExp(`^${label}`) }).click();
    await welcome.getByRole("button", { name: `Continue with ${label}` }).click();
    await expect(welcome.getByLabel("Provider type")).toHaveValue(kind);
    await welcome.getByLabel("Profile name").fill(`Onboarding ${label}`);
    if (kind === "cli") {
      await welcome.getByLabel("Command line tool").selectOption("codex");
    } else {
      await welcome.getByLabel("Model", { exact: true }).fill(model);
      if (kind === "api") {
        await welcome.getByLabel("Credential storage").selectOption("environment");
        await welcome.getByLabel("Environment variable name").fill("BADSHOP_ONBOARDING_TEST_KEY");
      } else {
        await welcome.getByLabel("API base URL", { exact: true }).fill("http://127.0.0.1:1234/v1");
      }
    }
    await welcome.getByRole("button", { name: "Save provider" }).click();
    await expect(welcome.getByRole("button", { name: "Start making badshops" })).toBeVisible();
    const profiles = JSON.parse(await readFile(path.join(emptyCore.folder, "config/providers.json"), "utf8")) as Profile[];
    expect(profiles).toEqual([expect.objectContaining({ kind, label: `Onboarding ${label}`, model,
      ...(kind === "cli" ? { cli: "codex" } : kind === "api" ? { api_key_env: "BADSHOP_ONBOARDING_TEST_KEY" } : { api_base: "http://127.0.0.1:1234/v1" }),
    })]);
    expect((await emptyCore.call("session.get") as Session).provider_profile_id).toBe(profiles[0].id);
    await welcome.getByRole("button", { name: "Start making badshops" }).click();
    await page.screenshot({ path: info.outputPath("destination.png") });
    await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeVisible();
    await expect(page.getByLabel("Active provider")).toHaveValue(profiles[0].id);
    await emptyCore.close();
    const restarted = await startCore(emptyCore.folder);
    try {
      await page.goto(`/?core_port=${restarted.port}&core_token=${restarted.token}`);
      await expect(page.getByText("Connected", { exact: true })).toBeVisible();
      await expect(welcome).toHaveCount(0);
      expect(await restarted.call("providers.list")).toEqual(profiles);
      // Provider selection belongs to the project; a fresh process offers its autosave.
      await page.getByRole("button", { name: "Restore session", exact: true }).click();
      await expect(page.getByLabel("Active provider")).toHaveValue(profiles[0].id);
    } finally { await restarted.close(); }
  });
}

test("quick start stays in Quick ideas after reload", async ({ page, emptyCore }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem("badshop.welcome")) localStorage.setItem("badshop.workspace", "advanced");
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Start with a quick idea" }).click();
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Welcome to badshop" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  expect(await emptyCore.call("providers.list")).toEqual([]);
});

test("provider setup can go back to quick ideas without saving a provider", async ({ page, emptyCore }, info) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.addInitScript(() => localStorage.setItem("badshop.textScale", "200"));
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  await expect(welcome).toBeVisible();
  expect(await welcome.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("welcome-200-percent.png") });
  await welcome.getByRole("button", { name: "Continue with Cloud API" }).click();
  await welcome.getByLabel("Profile name").fill("Unfinished setup");
  await page.screenshot({ path: info.outputPath("provider-setup.png") });
  await welcome.getByRole("button", { name: "Back", exact: true }).click({ timeout: 3000 });
  await welcome.getByRole("button", { name: "Start with a quick idea" }).click();
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  expect(await emptyCore.call("providers.list")).toEqual([]);
});

test("manual editing remains available from the provider form", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  await welcome.getByRole("button", { name: "Continue with Cloud API" }).click();
  await welcome.getByRole("button", { name: "Edit a photo without AI" }).click();
  await expect(page.getByRole("button", { name: "Run tool", exact: true })).toBeEnabled();
  await page.reload();
  await expect(welcome).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run tool", exact: true })).toBeEnabled();
  expect(await emptyCore.call("providers.list")).toEqual([]);
});

test("invalid provider setup retains input and can be corrected", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  await welcome.getByRole("button", { name: /^Custom endpoint/ }).click();
  await welcome.getByRole("button", { name: "Continue with Custom endpoint" }).click();
  await welcome.getByLabel("Profile name").fill("Correctable endpoint");
  await welcome.getByLabel("Model", { exact: true }).fill("openai/local-vision");
  await welcome.getByLabel("API base URL", { exact: true }).fill("https://example.test/v1?invalid=true");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect(welcome.getByRole("alert")).toContainText("invalid provider profile");
  expect(await emptyCore.call("providers.list")).toEqual([]);
  await expect(welcome.getByLabel("Profile name")).toHaveValue("Correctable endpoint");
  await welcome.getByLabel("API base URL", { exact: true }).fill("http://127.0.0.1:1234/v1");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect(welcome.getByRole("button", { name: "Start making badshops" })).toBeVisible();
  await expect(welcome.getByRole("alert")).toHaveCount(0);
  expect(await emptyCore.call("providers.list")).toEqual([expect.objectContaining({ label: "Correctable endpoint", api_base: "http://127.0.0.1:1234/v1" })]);
});

test("on-device download can cancel, retry after failure, and open chat after activation", async ({ page, emptyCore }, info) => {
  // Simulate the large external downloads and runtime activation only. No model is downloaded or run.
  const assets: Asset[] = [
    { name: "local-vision/test-model.gguf", label: "Test vision model", approx_mb: 2000, present: false },
    { name: "local-vision/test-runtime.zip", label: "Test runtime", approx_mb: 20, present: false },
    { name: "face_detection_yunet_2023mar.onnx", label: "Face detector", approx_mb: 1, present: false },
  ];
  let pending: { id: number; name: string } | undefined;
  let attempt = 0;
  let selected = false;
  const profile = { id: "badshop-on-device", kind: "local", label: "On-device AI", model: "badshop", capability_overrides: {},
    cli: null, executable: null, api_base: null, allow_insecure_http: false, api_key_ref: null, api_key_env: null };
  await page.routeWebSocket(`ws://127.0.0.1:${emptyCore.port}/`, client => {
    const server = client.connectToServer();
    const sessionRequests = new Set<number>();
    let instance = "";
    let sequence = 0;
    server.onMessage(frame => {
      const reply = JSON.parse(String(frame));
      if (reply.type === "welcome") { instance = reply.core_instance_id; sequence = reply.event_seq; }
      if (reply.method) {
        reply.event_seq = ++sequence;
        if (reply.context) reply.context.event_seq = sequence;
      }
      if (reply.result?.context) reply.result.context.event_seq = sequence;
      if (sessionRequests.delete(reply.id) && selected) reply.result.provider_profile_id = profile.id;
      client.send(JSON.stringify(reply));
    });
    client.onMessage(frame => {
      const request = JSON.parse(String(frame));
      const respond = (result: unknown) => client.send(JSON.stringify({ jsonrpc: "2.0", id: request.id, result }));
      if (request.method === "assets.status") return respond(assets);
      if (request.method === "providers.list") return respond(selected ? [profile] : []);
      if (request.method === "assets.download") {
        attempt++;
        if (attempt === 1) {
          pending = { id: request.id, name: request.params.name };
          client.send(JSON.stringify({ jsonrpc: "2.0", method: "asset.progress", core_instance_id: instance,
            event_seq: ++sequence, params: { name: pending.name, done: 50, total: 100 } }));
          return;
        }
        if (attempt === 2) return client.send(JSON.stringify({ jsonrpc: "2.0", id: request.id, error: { code: -32000, message: "Download interrupted. Try again." } }));
        const asset = assets.find(asset => asset.name === request.params.name)!;
        asset.present = true;
        return respond({ path: `/isolated-test/${asset.name}` });
      }
      if (request.method === "assets.cancel") {
        expect(request.params.name).toBe(pending!.name);
        client.send(JSON.stringify({ jsonrpc: "2.0", id: pending!.id, error: { code: -32000, message: "download cancelled" } }));
        pending = undefined;
        return respond({ cancelled: true });
      }
      if (request.method === "providers.on_device") {
        expect(assets.every(asset => asset.present)).toBe(true);
        selected = true;
        void emptyCore.call("session.get").then(session => respond({ ...session as Session, provider_profile_id: profile.id }));
        return;
      }
      if (request.method === "session.get") sessionRequests.add(request.id);
      server.send(frame);
    });
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  const download = welcome.getByRole("button", { name: /Download and use on-device AI/ });
  await download.click();
  await expect(welcome.getByRole("progressbar")).toBeVisible();
  await expect(welcome.getByRole("button", { name: "Download later" })).toBeDisabled();
  await welcome.getByRole("button", { name: "Cancel download" }).click();
  await expect(download).toBeEnabled();
  await expect(welcome.getByRole("button", { name: "Cancel download" })).toHaveCount(0);
  await download.click();
  await expect(welcome.getByText("Download interrupted. Try again.", { exact: true })).toBeVisible();
  await expect(download).toBeEnabled();
  await download.click();
  await expect(welcome).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("on-device-destination.png") });
  await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeVisible();
  await expect(page.getByLabel("Active provider")).toHaveValue("badshop-on-device");
});

test("every optional editing asset can be downloaded from onboarding", async ({ page, emptyCore }) => {
  const profile = await emptyCore.call("providers.save", { profile: { kind: "local", label: "Saved provider", model: "ollama_chat/llava" } }) as Profile;
  const assets = await emptyCore.call("assets.status") as Asset[];
  await page.routeWebSocket(`ws://127.0.0.1:${emptyCore.port}/`, client => {
    const server = client.connectToServer();
    client.onMessage(frame => {
      const request = JSON.parse(String(frame));
      const respond = (result: unknown) => client.send(JSON.stringify({ jsonrpc: "2.0", id: request.id, result }));
      if (request.method === "assets.status") return respond(assets);
      if (request.method === "assets.download") {
        // Download UI contract only; the transfer is simulated to avoid model/font downloads.
        const asset = assets.find(asset => asset.name === request.params.name)!;
        asset.present = true;
        return respond({ path: `/isolated-test/${asset.name}` });
      }
      server.send(frame);
    });
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  await welcome.getByRole("button", { name: "Use Saved provider" }).click();
  const rows = welcome.locator(".asset-row");
  await expect(rows).toHaveCount(4);
  for (const row of await rows.all()) {
    await row.getByRole("button", { name: "Download", exact: true }).click();
    await expect(row.getByText("Downloaded", { exact: true })).toBeVisible();
    await expect(row.getByRole("button")).toHaveCount(0);
  }
  await welcome.getByRole("button", { name: "Start making badshops" }).click();
  await expect(page.getByLabel("Active provider")).toHaveValue(profile.id);
});

test("unsupported on-device AI offers a working download-later exit", async ({ page, emptyCore }) => {
  await page.routeWebSocket(`ws://127.0.0.1:${emptyCore.port}/`, client => {
    const server = client.connectToServer();
    client.onMessage(frame => {
      const request = JSON.parse(String(frame));
      if (request.method === "assets.status") client.send(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: [] }));
      else server.send(frame);
    });
  });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI (optional)", { exact: true }).click();
  await expect(welcome.getByText("On-device AI is unavailable on this computer.")).toBeVisible();
  await expect(welcome.getByRole("button", { name: /Download and use on-device AI/ })).toHaveCount(0);
  await welcome.getByRole("button", { name: "Download later" }).click();
  await page.reload();
  await expect(welcome).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
  expect(await emptyCore.call("providers.list")).toEqual([]);
});
