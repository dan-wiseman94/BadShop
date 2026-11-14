import { invoke } from "@tauri-apps/api/core";
import { rpc } from "./rpc";
import { captureScreen, verifyImageClipboard } from "./native";

let clipboardProbe: Promise<boolean> | undefined;
let captureProbe: Promise<boolean> | undefined;

async function verifyCapture() {
  const preview = await captureScreen();
  if (!preview) throw new Error("Native capture smoke was cancelled");
  try {
    const image = new Image();
    image.src = preview.candidates[0].thumbnail_data_url;
    await image.decode();
    return image.naturalWidth === preview.width && image.naturalHeight === preview.height;
  } finally { await rpc.request("media.discard", { preview_id: preview.id }); }
}

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
  const capturePixels = await invoke<boolean>("smoke_capture_enabled")
    ? await (captureProbe ??= verifyCapture()) : undefined;
  // Report after the React commit has had a chance to paint.
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  if (current()) await invoke("renderer_ready", { ...state, toolCount: tools.length, clipboardPixels,
    ...(capturePixels !== undefined ? { capturePixels } : {}) });
}
