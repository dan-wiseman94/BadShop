import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { action, imageUrl, useArtifact, useCoreQuery } from "../data";
import type { Params } from "../types";
import { rpc, RpcError } from "../rpc";
import { copyImage, pickFolder, reveal } from "../native";
import { useUI } from "../store";
import { useOperation } from "../useOperation";
import { InputField, SelectField } from "./Fields";
import { RemixShare } from "./RemixShare";
import "../share.css";

export function CopyImage({ id, frame = 0, animated = false, disabled = false }: {
  id: string; frame?: number; animated?: boolean; disabled?: boolean;
}) {
  const { busy, error, perform } = useOperation();
  return <><button disabled={busy || disabled} onClick={() => void perform(async () => {
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
export function ShareImage({ id, label, frame = 0 }: { id: string; label?: string; frame?: number }) {
  const [preparedTarget, setPreparedTarget] = useState<string>();
  const targetId = preparedTarget ?? id;
  const targetFrame = preparedTarget ? 0 : frame;
  const { data } = useArtifact(targetId);
  const { data: original } = useArtifact(id);
  const { data: thumbnail } = useArtifact(targetId, true, true, targetFrame);
  const ready = useUI(state => state.status === "ready");
  const { data: credits, error: creditError } = useQuery({ queryKey: ["credits.get", targetId], queryFn: () => rpc.request("credits.get", { artifact_id: targetId }), enabled: ready });
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
  const [uncertain, setUncertain] = useState<{ folder: string; operationId?: string }>();
  const meta = data?.meta;
  const animated = (meta?.frames ?? 1) > 1;
  const inputAnimated = (original?.meta.frames ?? 1) > 1;
  const folder = settings?.effective_output_dir;
  const writeBlocked = busy || !ready || !folder || !!uncertain;
  const extension = meta?.format === "JPEG" ? "jpg" : meta?.format === "HEIF" ? "heic" : meta?.format.toLowerCase();

  async function reportSaved(path: string) {
    useUI.getState().set({ notice: `Exported to ${path}` });
    try {
      await reveal(path);
    } catch {
      throw new Error(`Image saved to ${path}. BadShop could not open its folder.`);
    }
  }

  function clearExportNotice() {
    const ui = useUI.getState();
    if (ui.notice?.startsWith("Exported to ")) ui.set({ notice: null });
  }

  async function saveImage(artifactId: string) {
    if (!folder || uncertain) return;
    clearExportNotice();
    let written: { path: string };
    try {
      written = includeCredits ? await action("credits.export", { artifact_id: artifactId })
        : await action("export", { artifact_id: artifactId });
    } catch (error) {
      if (error instanceof RpcError && error.code === undefined) {
        setUncertain({ folder, operationId: error.operationId });
        throw new Error("BadShop could not confirm the file was saved. Check the destination before saving again.");
      }
      throw error;
    }
    await reportSaved(written.path);
  }

  async function inspectWrite() {
    if (!uncertain?.operationId) return;
    const receipt = await rpc.request("operations.get", { operation_id: uncertain.operationId });
    if (receipt.status === "committed" && typeof receipt.result === "object" && receipt.result &&
      "path" in receipt.result && typeof receipt.result.path === "string") {
      setUncertain(undefined);
      await reportSaved(receipt.result.path);
      return;
    }
    throw new Error(receipt.status === "pending" ? "The save may still be running. Check again before retrying."
      : "BadShop has no file path for this save. Check the destination before retrying.");
  }
  function exportParams(): Params {
    if (!!width !== !!height) throw new Error("Enter both width and height, or leave both empty.");
    const keepAnimation = preserveAnimation && inputAnimated;
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
    if (save) clearExportNotice();
    const generation = useUI.getState().documentGeneration;
    const step = await action("tools.run", { tool: "export_profile", params: { ...exportParams(), image: id } });
    if (step.status !== "done" || !step.outputs[0]) throw new Error(step.error?.message ?? "Could not prepare the output");
    if (generation !== useUI.getState().documentGeneration) return;
    setPreparedTarget(step.outputs[0]);
    useUI.getState().set({ selectedArtifact: step.outputs[0], selectedStep: step.id });
    if (save) await saveImage(step.outputs[0]);
  }
  return <section className="share-image" aria-label="Share selected image">
    <h2>{label ?? "Share image"}</h2>
    {preparedTarget && <p><strong>Prepared export</strong></p>}
    {imageUrl(thumbnail) && <img className="share-preview" src={imageUrl(thumbnail)} alt="Selected image preview" />}
    <p>{meta ? `${meta.width} × ${meta.height} · ${meta.format} · ${data.byteLength.toLocaleString()} bytes` : "Loading image…"}</p>
    {animated && <p>Copy uses frame {targetFrame + 1} of {meta?.frames}. Save original keeps the animation.</p>}
    <p className="share-destination">Save to: {folder ?? "Loading output folder…"}</p>
    {meta && <p className="share-destination">Filename: {meta.label}.{extension}</p>}
    <p><button disabled={busy || !ready} onClick={() => void perform(async () => {
      const path = await pickFolder();
      if (path) await action("settings.set", { values: { output_dir: path } });
    })}>Change folder</button> <span className="muted">Used for future exports too</span></p>
    {!ready && <p className="muted">Wait for BadShop to reconnect before sharing.</p>}
    {error && <p role="alert" className="error-text">{error}</p>}
    {uncertain && <div>
      <p className="share-destination">Check for the image in {uncertain.folder}.</p>
      {uncertain.operationId && <button disabled={busy || !ready} onClick={() => void perform(inspectWrite)}>Check operation</button>}
      <button disabled={busy || !ready} onClick={() => setUncertain(undefined)}>I checked the folder</button>
    </div>}
    <div className="share-actions">
      <CopyImage id={targetId} frame={targetFrame} animated={animated} disabled={!meta || !ready || busy} />
      <button className="primary" disabled={writeBlocked || !meta} onClick={() => void perform(() => saveImage(targetId))}>
        {animated ? "Save original" : "Save image"}
      </button>
      <RemixShare key={targetId} id={targetId} />
    </div>
    <label><input type="checkbox" checked={includeCredits} onChange={e => setIncludeCredits(e.target.checked)} /> Save source credits alongside the image</label>
    {creditError && <p role="alert">Credits could not be loaded: {creditError.message}</p>}
    {credits && <details><summary>Source credits ({credits.sources.length})</summary>
      {credits.sources.map((source, index) => <p key={index}>{[source.title, source.creator, source.license, source.page ?? source.url].filter(Boolean).map(String).join(" · ")}</p>)}
      {!credits.sources.length && <p>No source credits recorded. Check the rights to your imported images before publishing.</p>}
    </details>}
    <details><summary>Size and format</summary>
      <p>Edits use a working copy up to 1000 px on the longest side. Enlarging export does not restore original detail.</p>
      <SelectField label="Output preset" bind={[profile, setProfile]} options={["original", "web-button", "blinkie", "forum-signature", "avatar", "wallpaper"]} />
      {inputAnimated && <InputField label="Keep animation (GIF output)" type="checkbox" bind={[preserveAnimation, setPreserveAnimation]} />}
      {preserveAnimation && inputAnimated ? <p>Output format: GIF (keeps every frame).</p>
        : <SelectField label="Format" bind={[format, setFormat]} options={["PNG", "JPEG", "GIF"]} />}
      <InputField label="Output width (optional)" type="number" min={1} max={2000} bind={[width, setWidth]} />
      <InputField label="Output height (optional)" type="number" min={1} max={2000} bind={[height, setHeight]} />
      <SelectField label="Picture fitting" bind={[fit, setFit]} options={[["contain", "Fit whole picture"], ["cover", "Fill and crop"], ["stretch", "Stretch"]]} />
      <InputField label="Background for opaque output" type="color" bind={[background, setBackground]} />
      <InputField label="Maximum file size (optional)" type="number" min={0.1} step="any"
        bind={[maxBytes, setMaxBytes]} />
      <SelectField label="File size unit" bind={[sizeUnit, setSizeUnit]} options={["KB", "MB"]} />
      <InputField label="Allow smaller dimensions to meet the file limit" type="checkbox" bind={[shrinkToFit, setShrinkToFit]} />
      <button disabled={busy || !ready || !meta} onClick={() => void perform(() => prepare(false))}>Prepare output</button>
      <button disabled={writeBlocked || !meta} onClick={() => void perform(() => prepare(true))}>Prepare and save</button>
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
                if (params.preserve_animation && inputAnimated) params.format = "GIF";
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
    </details>
    {!!prepared.length && <section aria-label="Prepared export sizes">
      {prepared.map((output, index) => <PreparedExport key={`${output.id}-${index}`} {...output} busy={writeBlocked}
        save={() => void perform(() => saveImage(output.id))} />)}
    </section>}
  </section>;
}
