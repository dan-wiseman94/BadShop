import { invoke } from "@tauri-apps/api/core";
import { rpc } from "./rpc";

/** Only the isolated harness enables this probe. No project mutation or provider call. */
export async function reportNativeReadiness(state: {
  ready: boolean; sessionId: string; revision: number; unsaved: boolean; welcome: boolean; closePending: boolean;
}, current: () => boolean = () => true): Promise<void> {
  if (!(await invoke<boolean>("smoke_probe_enabled")) || !current()) return;
  if (!state.ready) {
    await invoke("renderer_ready", { ...state, toolCount: 0 });
    return;
  }
  const tools = await rpc.request("tools.list");
  if (!state.sessionId || !tools.length) throw new Error("Native smoke: session/catalog is not ready");
  // Report after the React commit has had a chance to paint.
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  if (current()) await invoke("renderer_ready", { ...state, toolCount: tools.length });
}
