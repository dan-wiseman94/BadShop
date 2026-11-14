import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { action, imageUrl, useArtifact, useCoreQuery } from "../data";
import type { Params } from "../types";
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

function PreparedExport({ id, name, busy, save }: { id: string; name: string; busy: boolean; save: () => void }) {
  const { data } = useArtifact(id, true);
  return <figure><img src={imageUrl(data)} alt={`${name} prepared output`} style={{ maxWidth: 160, imageRendering: "pixelated" }} />
    <figcaption>{name} · {data?.meta.width} × {data?.meta.height}</figcaption>
    <button disabled={busy} onClick={save}>Save {name}</button></figure>;
}

/** Shared by the canvas and retro workbench: one place to inspect and export pixels. */
export function ShareImage({ id }: { id: string }) {
  const { data } = useArtifact(id);
  const { data: credits, error: creditError } = useQuery({ queryKey: ["credits.get", id], queryFn: () => rpc.request("credits.get", { artifact_id: id }) });
  const [includeCredits, setIncludeCredits] = useState(true);
  const [profile, setProfile] = useState("original");
  const [format, setFormat] = useState("PNG");
  const [maxBytes, setMaxBytes] = useState("");
  const [sizeUnit, setSizeUnit] = useState("KB");
  const [width, setWidth] = useState("");
  const [height, setHeight] = useState("");
  const [fit, setFit] = useState("contain");
  const [background, setBackground] = useState("#000000");
  const [preserveAnimation, setPreserveAnimation] = useState(true);
  const [shrinkToFit, setShrinkToFit] = useState(false);
  const [presetName, setPresetName] = useState("");
  const { data: settings } = useCoreQuery("settings.get");
  const [selectedPresets, setSelectedPresets] = useState<string[]>([]);
  const [prepared, setPrepared] = useState<{ name: string; id: string }[]>([]);
  const [preparing, setPreparing] = useState(false);
  const stopBatch = useRef(false);
  useEffect(() => () => { stopBatch.current = true; }, []);
  const { busy, error, perform } = useOperation();
  const meta = data?.meta;
  async function saveImage(artifactId: string) {
    const result = includeCredits ? await action("credits.export", { artifact_id: artifactId })
      : await action("export", { artifact_id: artifactId });
    useUI.getState().set({ notice: `Exported to ${result.path}` });
    await reveal(result.path);
  }
  function exportParams(): Params {
    if (!!width !== !!height) throw new Error("Enter both width and height, or leave both empty.");
    const keepAnimation = preserveAnimation && (meta?.frames ?? 1) > 1;
    return { profile,
      format: keepAnimation ? "GIF" : format, fit, background,
      preserve_animation: preserveAnimation, shrink_to_fit: shrinkToFit,
      ...(width && height ? { width: Number(width), height: Number(height) } : {}),
      ...(maxBytes ? { max_bytes: Math.round(Number(maxBytes) * (sizeUnit === "MB" ? 1000000 : 1000)) } : {}) };
  }
  function loadPreset(params: Params) {
    setProfile(String(params.profile)); setFormat(String(params.format));
    setWidth(params.width == null ? "" : String(params.width));
    setHeight(params.height == null ? "" : String(params.height));
    setFit(String(params.fit)); setBackground(String(params.background));
    setPreserveAnimation(Boolean(params.preserve_animation)); setShrinkToFit(Boolean(params.shrink_to_fit));
    setSizeUnit("KB"); setMaxBytes(params.max_bytes == null ? "" : String(Number(params.max_bytes) / 1000));
  }
  async function prepare(save: boolean) {
    const step = await action("tools.run", { tool: "export_profile", params: { ...exportParams(), image: id } });
    if (step.status !== "done" || !step.outputs[0]) throw new Error(step.error?.message ?? "Could not prepare the output");
    useUI.getState().set({ selectedArtifact: step.outputs[0], selectedStep: step.id });
    if (save) await saveImage(step.outputs[0]);
  }
  return <section className="share-image" aria-label="Share selected image">
    <h2>Ready for the group chat?</h2>
    <p>{meta ? `${meta.width} × ${meta.height} · ${meta.format} · ${(data.data.length * 3 / 4 - (data.data.endsWith("==") ? 2 : data.data.endsWith("=") ? 1 : 0)).toLocaleString()} bytes` : "Loading image…"}</p>
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
    <button className="primary" disabled={busy || !meta} onClick={() => void perform(() => saveImage(id))}>{busy ? "Saving…" : "Save image file"}</button>
    <details><summary>Resize or change format</summary>
      <p>Creates a separate image in History. PNG keeps transparency. JPEG uses your chosen background.</p>
      <fieldset><legend>Saved export settings</legend>
        {(settings?.export_presets ?? []).map((preset, index) => <div key={index}>
          <label><input type="checkbox" checked={selectedPresets.includes(preset.name)} disabled={busy}
            onChange={event => setSelectedPresets(previous => event.target.checked ? [...previous, preset.name] : previous.filter(name => name !== preset.name))} />Include {preset.name}</label>
          <button disabled={busy} onClick={() => { loadPreset(preset.params); setPresetName(preset.name); }}>Use {preset.name}</button>
          <button disabled={busy} aria-label={`Delete export preset ${preset.name}`} onClick={() => void perform(async () => {
            const latest = await rpc.request("settings.get");
            await action("settings.set", { values: { export_presets: latest.export_presets?.filter(item => item.name !== preset.name) } });
          })}>Delete</button>
        </div>)}
        <InputField label="Export preset name" maxLength={80} bind={[presetName, setPresetName]} />
        <button disabled={busy || !presetName.trim()} onClick={() => void perform(async () => {
          const latest = await rpc.request("settings.get");
          const presets = (latest.export_presets ?? []).filter(item => item.name !== presetName.trim());
          await action("settings.set", { values: { export_presets: [...presets, { name: presetName.trim(), params: exportParams() }] } });
        })}>Save export settings</button>
        <button disabled={busy || !meta || selectedPresets.length === 0 || selectedPresets.length > 12}
          onClick={() => void perform(async () => {
            stopBatch.current = false; setPreparing(true); setPrepared([]);
            useUI.getState().set({ selectedArtifact: id });
            const generation = useUI.getState().documentGeneration;
            try {
              for (const preset of settings?.export_presets ?? []) {
                if (stopBatch.current || generation !== useUI.getState().documentGeneration) break;
                if (!selectedPresets.includes(preset.name)) continue;
                const params: Params = { ...preset.params, image: id };
                if (params.preserve_animation && (meta?.frames ?? 1) > 1) params.format = "GIF";
                const step = await action("tools.run", { tool: "export_profile", params });
                if (step.status !== "done" || !step.outputs[0]) throw new Error(`${preset.name}: ${step.error?.message ?? "Preparation failed"}`);
                if (generation !== useUI.getState().documentGeneration) break;
                setPrepared(previous => [...previous, { name: preset.name, id: step.outputs[0] }]);
              }
            } finally { setPreparing(false); }
          })}>Prepare selected sizes</button>
        <p>Choose up to 12 saved settings. Completed outputs stay in the project if you stop or a later size fails.</p>
        {preparing && <button onClick={() => { stopBatch.current = true; }}>Stop after current size</button>}
      </fieldset>
      {(meta?.frames ?? 1) > 1 && <InputField label="Keep animation (GIF output)" type="checkbox" bind={[preserveAnimation, setPreserveAnimation]} />}
      <SelectField label="Output preset" bind={[profile, setProfile]} options={["original", "web-button", "blinkie", "forum-signature", "avatar", "wallpaper"]} />
      {preserveAnimation && (meta?.frames ?? 1) > 1 ? <p>Output format: GIF (keeps every frame).</p>
        : <SelectField label="Format" bind={[format, setFormat]} options={["PNG", "JPEG", "GIF"]} />}
      <InputField label="Output width (optional)" type="number" min={1} max={2000} bind={[width, setWidth]} />
      <InputField label="Output height (optional)" type="number" min={1} max={2000} bind={[height, setHeight]} />
      <SelectField label="Picture fitting" bind={[fit, setFit]} options={[["contain", "Fit whole picture"], ["cover", "Fill and crop"], ["stretch", "Stretch"]]} />
      <InputField label="Background for opaque output" type="color" bind={[background, setBackground]} />
      <InputField label="Maximum file size (optional)" type="number" min={0.1} step="any"
        bind={[maxBytes, setMaxBytes]} />
      <SelectField label="File size unit" bind={[sizeUnit, setSizeUnit]} options={["KB", "MB"]} />
      <InputField label="Allow smaller dimensions to meet the file limit" type="checkbox" bind={[shrinkToFit, setShrinkToFit]} />
      <button disabled={busy || !meta} onClick={() => void perform(() => prepare(false))}>Prepare output</button>
      <button disabled={busy || !meta} onClick={() => void perform(() => prepare(true))}>Prepare and save</button>
    </details>
    {!!prepared.length && <section aria-label="Prepared export sizes">
      {prepared.map((output, index) => <PreparedExport key={`${output.id}-${index}`} {...output} busy={busy}
        save={() => void perform(() => saveImage(output.id))} />)}
    </section>}
    {error && <p role="alert" className="error-text">{error}</p>}
  </section>;
}
