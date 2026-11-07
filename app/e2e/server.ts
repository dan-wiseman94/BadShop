import path from "node:path";
import type { FullConfig } from "@playwright/test";
import { createServer } from "vite";

/** Own Vite directly so Windows teardown does not depend on shell/taskkill trees. */
export default async function setup(config: FullConfig) {
  const url = new URL(config.projects[0].use.baseURL!);
  const server = await createServer({
    root: path.resolve(import.meta.dirname, ".."),
    server: {
      host: url.hostname,
      port: Number(url.port),
      strictPort: true,
      // Editing a test must not reload the app and erase its in-memory document.
      watch: { ignored: ["**/tests/**", "**/e2e/**"] },
    },
  });
  try {
    await server.listen();
  } catch (error) {
    await server.close();
    throw error;
  }
  return () => server.close();
}
