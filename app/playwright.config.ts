import { defineConfig } from "@playwright/test";
import { createHash } from "node:crypto";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const worktreePort = 20000 + createHash("sha256").update(root).digest().readUInt32BE(0) % 30000;
const runId = new Date().toISOString().replace(/[:.]/g, "-") + "-" + process.pid;
const port = Number(process.env.BADSHOP_E2E_PORT ?? worktreePort);
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/server.ts",
  outputDir: process.env.BADSHOP_E2E_OUTPUT ?? path.join(root, "artifacts/verification/playwright", runId),
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 10000 },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 960 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: "list",
});
