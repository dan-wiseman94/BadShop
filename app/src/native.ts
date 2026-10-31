import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import { readImage, writeText } from "@tauri-apps/plugin-clipboard-manager";
import { openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { Connection } from "./types";
export const native = isTauri();
export const onCloseRequested = (confirm: () => Promise<boolean>) =>
  native
    ? getCurrentWindow().onCloseRequested(async (event) => {
        if (!(await confirm())) event.preventDefault();
      })
    : Promise.resolve(() => {});
export async function getConnection(): Promise<Connection> {
  if (native) return invoke<Connection>("core_connection");
  if (
    import.meta.env.DEV &&
    ["127.0.0.1", "localhost"].includes(location.hostname)
  ) {
    const query = new URLSearchParams(location.search);
    const port = Number(query.get("core_port"));
    const token = query.get("core_token");
    if (port > 0 && port < 65536 && token) return { port, token };
  }
  throw new Error(
    "Open badshop in the desktop app. Browser development requires a local core connection.",
  );
}
export const onCoreStatus = (
  handler: (data: Connection & { state: string; attempt?: number }) => void,
) =>
  native
    ? listen<Connection & { state: string; attempt?: number }>(
        "core-status",
        (event) => handler(event.payload),
      )
    : Promise.resolve(() => {});
export const onFileDrop = (handler: (paths: string[]) => void) =>
  native
    ? getCurrentWebview().onDragDropEvent((event) => {
        if (event.payload.type === "drop") handler(event.payload.paths);
      })
    : Promise.resolve(() => {});
export async function pickImages() {
  if (!native) return null;
  return open({
    multiple: true,
    filters: [
      {
        name: "Images",
        extensions: ["png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"],
      },
    ],
  });
}
export async function projectPath(
  saving: boolean,
  recipe = false,
): Promise<string | null> {
  if (!native)
    return window.prompt(
      saving ? "Save to an absolute file path" : "Open an absolute file path",
    );
  const filters = [
    {
      name: recipe ? "Recipe" : "badshop session",
      extensions: [recipe ? "json" : "badshop"],
    },
  ];
  return saving
    ? save({
        filters,
        defaultPath: recipe ? "recipe.json" : "Untitled.badshop",
      })
    : (open({ filters, multiple: false }) as Promise<string | null>);
}
export async function pickFolder() {
  return native
    ? open({ directory: true, multiple: false })
    : window.prompt("Absolute output folder");
}
export async function copyText(text: string) {
  if (native) await writeText(text);
  else await navigator.clipboard.writeText(text);
}
export async function reveal(path: string) {
  if (native) await revealItemInDir(path);
}
export async function openLink(url: string) {
  if (/^https?:\/\//.test(url)) {
    if (native) await openUrl(url);
    else window.open(url, "_blank", "noopener,noreferrer");
  }
}
export async function restart() {
  if (native) await invoke("core_restart");
  else location.reload();
}
export async function diagnostics() {
  return native
    ? invoke<string>("diagnostics")
    : "Browser development mode. Native core diagnostics are available in the desktop app.";
}
export async function clipboardImage(): Promise<Blob> {
  const image = await readImage();
  try {
    const { width, height } = await image.size();
    const rgba = await image.rgba();
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas
      .getContext("2d")!
      .putImageData(
        new ImageData(new Uint8ClampedArray(rgba), width, height),
        0,
        0,
      );
    return await new Promise((resolve, reject) =>
      canvas.toBlob(
        (blob) =>
          blob
            ? resolve(blob)
            : reject(new Error("Could not read clipboard image.")),
        "image/png",
      ),
    );
  } finally {
    await image.close();
  }
}
