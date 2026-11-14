import { useState } from "react";
import { action } from "../data";
import { useOperation } from "../useOperation";
import { captureScreen } from "../native";
import type { MediaPreview } from "../types";

export function ImportSources({ onFiles, onClipboard, onAttach, onCapture, onClose }: {
  onFiles: () => void;
  onClipboard: () => void;
  onAttach: (id: string) => void;
  onCapture: (preview: MediaPreview) => void;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const { busy, error, perform } = useOperation();
  return <div className="modal-backdrop">
    <section className="modal" role="dialog" aria-modal="true" aria-label="Add material"
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); if (!busy) onClose(); } }}>
      <div className="modal-heading">
        <h2>Add material</h2>
        <button disabled={busy} onClick={onClose} aria-label="Close add material">Close</button>
      </div>
      <p>Bring pictures, phone photos, GIFs, clips and PDF pages into this project.</p>
      <div className="manual-turn-controls">
        <button disabled={busy} onClick={onFiles}>Choose files</button>
        <button disabled={busy} onClick={onClipboard}>Paste clipboard image</button>
        <button disabled={busy} onClick={() => void perform(async () => {
          const preview = await captureScreen();
          if (preview) onCapture(preview);
        })}>Capture screen region</button>
      </div>
      <form className="studio-form" onSubmit={event => {
        event.preventDefault();
        void perform(async () => {
          const step = await action("tools.run", { tool: "acquire", params: { url: url.trim() } });
          if (step.status !== "done" || !step.outputs[0])
            throw new Error(step.error?.message ?? "The image link could not be imported.");
          onAttach(step.outputs[0]);
        });
      }}>
        <label className="wide">Image link
          <input type="url" required value={url} disabled={busy} placeholder="https://…"
            onChange={event => setUrl(event.target.value)} />
        </label>
        <p className="muted">Use a direct image URL. BadShop downloads it only when you press Import link.</p>
        <button disabled={busy || !url.trim()}>{busy ? "Importing…" : "Import link"}</button>
      </form>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <p className="muted">You can also drop files into the workspace. Clips and pages open a preview before importing.</p>
      <p className="muted">Capture hides BadShop, then lets you crop before importing. Your OS may ask for screenshot permission. Add text, arrows or boxes with Manual tools afterward.</p>
    </section>
  </div>;
}
