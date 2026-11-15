import { useUI } from "../store";
import { Button } from "./Button";
import type { useEditorPreview } from "../useEditorPreview";

export function EditorPreviewControls({ preview }: { preview: ReturnType<typeof useEditorPreview> }) {
  return <>
    <label>
      <input type="checkbox" checked={preview.automatic}
        onChange={event => preview.setAutomatic(event.target.checked)} />
      Automatic preview
    </label>
    {preview.slow && <p>This preview is slow.</p>}
    <Button type="button" label={preview.slow ? "Update preview" : "Preview changes"}
      disabled={!preview.available || preview.busy} onClick={preview.update} />
    {preview.result?.image && <Button type="button" label="View preview on canvas" onClick={preview.showOnCanvas} />}
    {preview.slow && <Button type="button" label="Resume automatic preview" onClick={preview.resume} />}
    {preview.updating && <p role="status">{preview.longRender ? "Rendering preview…" : "Updating preview…"}</p>}
    {preview.result?.plan?.reason === "missing_asset" &&
      <Button type="button" label="Open asset settings" onClick={() =>
        useUI.getState().set({ settingsOpen: true, settingsAssets: true })} />}
    {preview.result?.error && <p role="status">Preview unavailable. {preview.result.error}</p>}
  </>;
}
