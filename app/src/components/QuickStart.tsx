import { useEffect, useState } from "react";
import { action, imageUrl, importBlob, useArtifact, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { useOperation } from "../useOperation";
import { InputField } from "./Fields";
import starters from "../starters.json";
import { IdeaPreview } from "./IdeaPreview";
import { Cast } from "./Cast";
import { RecipeStudio } from "./RecipeStudio";
import { CreativeCollections } from "./CreativeCollections";
import { CreationReplay } from "./CreationReplay";
import { RemixChallenge } from "./RemixChallenge";
import { directionLabel } from "../directions";

function TakePreview({ id }: { id: string }) {
  const { data } = useArtifact(id, true);
  return <img src={imageUrl(data)} alt="" style={{ width: 110, height: 75, objectFit: "contain" }} />;
}

export function QuickStart({ onImport, onAdvanced, importedImage, importing = false }: {
  onImport: () => void;
  onAdvanced: () => void;
  importedImage?: { id: string } | null;
  importing?: boolean;
}) {
  const { data: session } = useSession();
  const { data: layouts = [] } = useCoreQuery("layouts.list");
  const { data: branches } = useCoreQuery("branches.list");
  const { busy, error, perform } = useOperation();
  const [chosen, setChosen] = useState<(typeof starters)[number] | null>(null);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [second, setSecond] = useState("");
  const [image, setImage] = useState(() => {
    const layout = session?.steps.find(s => s.tool === "layout" && s.status === "done");
    return (layout?.params.images as string[] | undefined)?.[0] ?? "";
  });
  useEffect(() => { if (importedImage) setImage(importedImage.id); }, [importedImage]);
  const selected = useUI(s => s.selectedStep);
  const ready = useUI(s => s.status === "ready");
  const step = session?.steps.find(s => s.id === selected && s.tool === "layout")
    ?? (selected === null ? session?.steps.slice().reverse().find(s => s.tool === "layout") : undefined);
  const [revision, setRevision] = useState("");
  const savedCaption = String((step?.params.captions as string[] | undefined)?.[0] ?? "");
  useEffect(() => { setRevision(savedCaption); }, [step?.id, savedCaption]);
  const disabled = !ready || busy || importing || !!session?.turn_running || !!session?.batch_running;
  const definitions = layouts.find(l => l.id === chosen?.template);
  const selectOutput = (stepId: string) => useUI.getState().set({ selectedArtifact: { stepId, outputIndex: 0 }, selectedStep: stepId });
  return <section className="quick-start pane" aria-label="Quick ideas">
    <div className="pane-heading"><span>Make something terrible</span><button onClick={onAdvanced}>All tools</button></div>
    <div className="quick-content">
      <p>Pick a joke. Use your own picture or our public-domain pigeon. No AI setup or downloads.</p>
      <button disabled={disabled} onClick={onImport}>Try my picture in every idea</button>
      {importing && <p role="status">Opening your picture…</p>}
      <label>Picture for previews<select value={image} disabled={disabled} onChange={e => setImage(e.target.value)}>
        <option value="">Use the CC0 pigeon sample</option>
        {Object.values(session?.artifacts ?? {}).filter(a => !Object.values(session?.artifacts ?? {}).some(b => b.original_id === a.id))
          .map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
      </select></label>
      <details><summary>Your cast of characters</summary><Cast image={image} disabled={disabled} onUse={setImage} /></details>
      <div className="quick-cards">
        {starters.map(starter => <button key={starter.template} aria-pressed={chosen?.template === starter.template}
          onClick={() => { setChosen(starter); setTitle(starter.title); setCaption(starter.caption); setSecond(starter.secondCaption ?? "Probably fine."); }}>
          <IdeaPreview image={image} template={starter.template} title={starter.title}
            captions={[starter.caption, starter.secondCaption ?? ""]} slots={layouts.find(l => l.id === starter.template)?.slots.length ?? 0}
            revision={session?.document_revision ?? 0} enabled={!disabled} />
          <strong>{starter.name}</strong><span>{starter.description}</span>
        </button>)}
      </div>
      {chosen && <form className="quick-form" onSubmit={e => {
        e.preventDefault();
        if (disabled || !definitions) return;
        const generation = useUI.getState().documentGeneration;
        void perform(async () => {
          let source = image;
          if (!source) {
            const response = await fetch("/samples/pigeon.png");
            if (!response.ok) throw new Error("The sample could not be loaded. Add your own image and try again.");
            const blob = await response.blob();
            if (generation !== useUI.getState().documentGeneration) throw new Error("The project changed. Choose this idea again in the current project.");
            source = (await importBlob(blob, "CC0-pigeon.png", { kind: "bundled-sample", title: "Geometric pigeon", creator: "BadShop contributors", license: "CC0-1.0", page: "https://creativecommons.org/publicdomain/zero/1.0/" })).working.id;
          }
          if (generation !== useUI.getState().documentGeneration) throw new Error("The project changed. Choose this idea again in the current project.");
          const result = await action("tools.run", { tool: "layout", params: {
            template: chosen.template, title, images: definitions.slots.map(() => source),
            captions: definitions.slots.map((_, i) => i === 0 ? caption : i === 1 ? second : ""),
          } });
          if (result.status !== "done" || !result.outputs[0]) throw new Error(result.error?.message ?? "The idea could not be created. Your images are still here.");
          if (generation !== useUI.getState().documentGeneration) return;
          selectOutput(result.id);
          setImage(source);
          setChosen(null);
          useUI.getState().set({ notice: "Ready to share. Change the punchline below, copy the image, or export it." });
        });
      }}>
        <h3>{chosen.name}</h3>
        <InputField label="Headline" maxLength={300} bind={[title, setTitle]} />
        <InputField label="Punchline" maxLength={1000} bind={[caption, setCaption]} />
        {(definitions?.slots.length ?? 0) > 1 && <InputField label="Second caption" maxLength={1000} bind={[second, setSecond]} />}
        <label>Picture<select value={image} onChange={e => setImage(e.target.value)}>
          <option value="">Use the CC0 pigeon sample</option>
          {Object.values(session?.artifacts ?? {}).filter(a => !Object.values(session?.artifacts ?? {}).some(b => b.original_id === a.id))
            .map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select></label>
        <button type="button" disabled={disabled} onClick={onImport}>Add my own image</button>
        <button className="primary" disabled={disabled || !definitions}>{busy ? "Making it…" : "Make this shitpost"}</button>
      </form>}
      {step && <form className="quick-form" onSubmit={e => { e.preventDefault(); if (disabled) return; void perform(async () => {
        const captions = [...(step.params.captions as string[] ?? [])]; captions[0] = revision;
        await action("steps.edit", { step_id: step.id, params: { ...step.params, captions }, auto_replay: false });
        const replayed = await action("steps.replay_from", { step_id: step.id });
        const failed = replayed.find(item => item.status === "error");
        if (failed) throw new Error(failed.error?.message ?? "The caption could not be changed. Try again or open History for details.");
        useUI.getState().set({ selectedArtifact: null, selectedStep: step.id });
      }); }}>
        <h3>Keep the picture. Fix the joke.</h3>
        {step.status === "error" && <p role="alert" className="error-text">{step.error?.message} {step.error?.hint} Edit the caption and retry, or open All tools for History.</p>}
        <InputField label="Revised punchline" disabled={disabled} maxLength={1000} bind={[revision, setRevision]} />
        <button disabled={disabled}>Change caption only</button>
        <button type="button" disabled={disabled} onClick={() => void perform(async () => {
          const copy = await action("branches.create", { name: `Another take ${new Date().toLocaleTimeString()}`, expected_revision: session!.document_revision });
          const layout = copy.steps.find(s => s.id === step.id);
          useUI.getState().set({ selectedStep: layout?.id ?? null, notice: "Original take kept. Change the caption to revise this copy." });
        })}>Keep this take &amp; make a variant</button>
      </form>}
      {!!branches?.branches.length && <details><summary>Saved takes</summary>{branches.branches.map(branch => <button key={branch.id}
        disabled={disabled || branch.id === branches.active_id} onClick={() => void perform(async () => {
          await action("branches.switch", { id: branch.id, expected_revision: session!.document_revision });
        })}>{branch.preview_id && <TakePreview id={branch.preview_id} />}{directionLabel(branch.name)}</button>)}</details>}
      <details><summary>Save a reusable recipe</summary><RecipeStudio /></details>
      <CreativeCollections image={image} title={String(step?.params.title ?? title)} caption={step ? revision : caption} disabled={disabled} />
      <details><summary>Show how it happened</summary><CreationReplay /></details>
      <details><summary>Play a remix challenge</summary><RemixChallenge /></details>
      {error && <p role="alert" className="error-text">{error}</p>}
    </div>
  </section>;
}
