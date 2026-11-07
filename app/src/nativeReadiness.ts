import { invoke } from "@tauri-apps/api/core";
import { rpc } from "./rpc";

/** Only the isolated harness enables this probe. No project mutation or provider call. */
export async function reportNativeReadiness(sessionId: string): Promise<void> {
  if (!(await invoke<boolean>("smoke_probe_enabled"))) return;
  const tools = await rpc.request("tools.list");
  if (!sessionId || !tools.length) throw new Error("Native smoke: session/catalog is not ready");
  // Report after the React commit has had a chance to paint.
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  await invoke("renderer_ready", { sessionId, toolCount: tools.length });
}
