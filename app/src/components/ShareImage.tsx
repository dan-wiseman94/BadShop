import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { action, imageUrl, useArtifact } from "../data";
import { rpc } from "../rpc";
import { copyImage, reveal } from "../native";
import { useUI } from "../store";
import { useOperation } from "../useOperation";
import { InputField, SelectField } from "./Fields";
import { RemixShare } from "./RemixShare";

export function CopyImage({ id, frame = 0, animated = false }: { id: string; frame?: number; animated?: boolean }) {
  const { busy, error, perform } = useOperation();
  return <><button disabled={busy} onClick={() => void perform(async () => {
    await copyImage(rpc.request("artifacts.frame", { id, frame }).then(result => result.data));
    useUI.getState().set({ notice: animated ? `Copied frame ${frame + 1} as a still PNG. Export the file to keep animation.` : "Image copied. Paste it into your chat." });
  })}>{busy ? "Copying…" : animated ? "Copy still frame" : "Copy image"}</button>
    {error && <span role="alert" className="error-text">{error} You can export the file instead.</span>}</>;
}

/** Shared by the canvas and retro workbench: one place to inspect and export pixels. */
export function ShareImage({ id }: { id: string }) {
  const { data } = useArtifact(id);
  const { data: credits, error: creditError } = useQuery({ queryKey: ["credits.get", id], queryFn: () => rpc.request("credits.get", { artifact_id: id }) });
  const [includeCredits, setIncludeCredits] = useState(true);
  const [profile, setProfile] = useState("original");
  const [format, setFormat] = useState("PNG");
  const [maxBytes, setMaxBytes] = useState("");
  const { busy, error, perform } = useOperation();
  const meta = data?.meta;
  return <section className="share-image" aria-label="Share selected image">
    <h2>Ready for the group chat?</h2>
    <p>{meta ? `${meta.width} × ${meta.height} · ${meta.format} · ${Math.ceil(data.data.length * 3 / 4 / 1024)} KB` : "Loading image…"}</p>
    <img className="share-preview" src={imageUrl(data)} alt="Selected image at chat preview size" />
    <p className="muted">Preview at 320 px. Make sure the joke is readable at this size.</p>
    <CopyImage id={id} animated={(meta?.frames ?? 1) > 1} />
    <RemixShare key={id} id={id} />
    {(meta?.frames ?? 1) > 1 && <p>This file is animated. Copy uses the first frame; exporting the original file keeps every frame.</p>}
    <label><input type="checkbox" checked={includeCredits} onChange={e => setIncludeCredits(e.target.checked)} /> Save source credits alongside the image</label>
    {creditError && <p role="alert">Credits could not be loaded: {creditError.message}</p>}
    {credits && <details><summary>Source credits ({credits.sources.length})</summary>
      {credits.sources.map((source, index) => <p key={index}>{[source.title, source.creator, source.license, source.page ?? source.url].filter(Boolean).map(String).join(" · ")}</p>)}
      {!credits.sources.length && <p>No source credits recorded. Check the rights to your imported images before publishing.</p>}
    </details>}
    <button className="primary" disabled={busy || !meta} onClick={() => void perform(async () => {
      const result = includeCredits ? await action("credits.export", { artifact_id: id }) : await action("export", { artifact_id: id });
      useUI.getState().set({ notice: `Exported to ${result.path}` });
      await reveal(result.path);
    })}>{busy ? "Saving…" : "Save image file"}</button>
    <details><summary>Resize or change format</summary>
      <p>Creates a separate image in History. PNG keeps transparency. JPEG flattens transparency. Conversion exports a still image.</p>
      <SelectField label="Output preset" bind={[profile, setProfile]} options={["original", "web-button", "blinkie", "forum-signature", "avatar", "wallpaper"]} />
      <SelectField label="Format" bind={[format, setFormat]} options={["PNG", "JPEG", "GIF"]} />
      <InputField label="Maximum file size in bytes (optional)" type="number" min={100} max={50000000}
        bind={[maxBytes, setMaxBytes]} />
      <button disabled={busy || !meta} onClick={() => void perform(async () => {
        const step = await action("tools.run", { tool: "export_profile", params: { image: id, profile, format,
          ...(maxBytes ? { max_bytes: Number(maxBytes) } : {}) } });
        if (step.status !== "done" || !step.outputs[0]) throw new Error(step.error?.message ?? "Could not prepare the output");
        useUI.getState().set({ selectedArtifact: step.outputs[0], selectedStep: step.id });
      })}>Prepare output</button>
    </details>
    {error && <p role="alert" className="error-text">{error}</p>}
  </section>;
}
