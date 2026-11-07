import { defineConfig } from "@playwright/test";
const port = Number(process.env.BADSHOP_E2E_PORT ?? 1421);
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/server.ts",
  outputDir: "../artifacts/verification/playwright",
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
