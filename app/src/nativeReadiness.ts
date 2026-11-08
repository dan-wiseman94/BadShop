import { invoke } from "@tauri-apps/api/core";
import { rpc } from "./rpc";
import { verifyImageClipboard } from "./native";

let clipboardProbe: Promise<boolean> | undefined;

/** Only the isolated harness enables this probe. No project mutation or provider call. */
export async function reportNativeReadiness(state: {
  ready: boolean; sessionId: string; revision: number; unsaved: boolean; welcome: boolean; closePending: boolean;
}, current: () => boolean = () => true): Promise<void> {
  if (!(await invoke<boolean>("smoke_probe_enabled")) || !current()) return;
  if (!state.ready) {
    await invoke("renderer_ready", { ...state, toolCount: 0, clipboardPixels: false });
    return;
  }
  const tools = await rpc.request("tools.list");
  if (!state.sessionId || !tools.length) throw new Error("Native smoke: session/catalog is not ready");
  if (!current()) return;
  const clipboardPixels = await (clipboardProbe ??= verifyImageClipboard());
  // Report after the React commit has had a chance to paint.
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  if (current()) await invoke("renderer_ready", { ...state, toolCount: tools.length, clipboardPixels });
}
