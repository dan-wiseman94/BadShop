import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { action, importBlob, queries, useCoreQuery, useSession } from "../data";
import { outputSelection, useCanvasArtifact, useUI } from "../store";
import { useOperation } from "../useOperation";
import { ThemeIcon } from "./ThemeIcon";
import { InputField } from "./Fields";
import starters from "../starters.json";
import { IdeaPreview } from "./IdeaPreview";
import { Cast } from "./Cast";
import { RecipeStudio } from "./RecipeStudio";
import { CreativeCollections } from "./CreativeCollections";
import { CreationReplay } from "./CreationReplay";
import { RemixChallenge } from "./RemixChallenge";
import type { Session } from "../types";
import { useDocumentProjection } from "../documentProjection";
import type { MaterialTarget } from "./Studio";
import { DraftDecision, useDraftDecision } from "./DraftDecision";
import { layoutForImage, QuickLayoutEditor } from "./QuickLayoutEditor";

export type QuickDraftHandle = {
  leave: () => Promise<boolean>;
  recordedStepId: string | undefined;
  creating: boolean;
};

export function QuickStart({ onImport, onAdvanced, onAllTools, onHistory, onResult, importedImage, importing = false, draftGuard, onBrowse, inspectorStepId }: {
  onImport: () => void;
  onAdvanced: () => void;
  onAllTools?: () => void;
  onHistory: (stepId?: string) => void;
  onResult?: () => void;
  importedImage?: { id: string } | null;
  importing?: boolean;
  draftGuard?: Ref<QuickDraftHandle>;
  inspectorStepId?: string;
  onBrowse?: (target: MaterialTarget) => void;
}) {
  const { data: session } = useSession();
  const { data: layouts = [] } = useCoreQuery("layouts.list");
  const { busy, error, perform } = useOperation();
  const [choosingFormat, setChoosingFormat] = useState(false);
  const [draftTarget, setDraftTarget] = useState<string | null>(null);
  const editorGuard = useRef<() => Promise<boolean>>(null);
  const [chosen, setChosen] = useState<(typeof starters)[number] | null>(null);
  const [startingImage, setStartingImage] = useState("");
  const headline = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!chosen || !headline.current) return;
    headline.current.focus({ preventScroll: true });
    headline.current.scrollIntoView({ block: "start" });
  }, [chosen]);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [second, setSecond] = useState("");
  const [image, setImage] = useState(() => {
    const layout = session?.steps.find(s => s.tool === "layout" && s.status === "done");
    return (layout?.params.images as string[] | undefined)?.[0] ?? "";
  });
  useEffect(() => { if (importedImage) setImage(importedImage.id); }, [importedImage]);
  const { id: canvasId } = useCanvasArtifact(session);
  const canvasLayout = layoutForImage(session, canvasId);
  const inspectorStep = session?.steps.find(item => item.id === inspectorStepId && item.tool === "layout");
  const step = (draftTarget && session?.steps.find(item => item.invocation_id === draftTarget)) || inspectorStep || canvasLayout;
  const layout = step && layouts.find(item => item.id === (step.params.template ?? "trading-card"));
  const { visibleArtifacts } = useDocumentProjection(session);
  const editing = !!step && !!layout && (!!inspectorStep || (!choosingFormat && !chosen));
  const classic = useUI(s => s.theme === "classic");
  const ready = useUI(s => s.status === "ready");
  const disabled = !ready || busy || importing || !!session?.turn_running || !!session?.batch_running;
  const definitions = layouts.find(l => l.id === chosen?.template);
  const creationDirty = !!chosen && (title !== chosen.title || caption !== chosen.caption ||
    second !== (chosen.secondCaption ?? "Probably fine.") || image !== startingImage);
  const creationDecision = useDraftDecision(creationDirty, busy);
  const canLeave = async () => chosen ? creationDecision.request() : await editorGuard.current?.() ?? true;
  useImperativeHandle(draftGuard, () => ({ leave: canLeave, recordedStepId: editing ? step.id : undefined, creating: !!chosen }));
  const navigate = async (work: () => void) => { if (await canLeave()) work(); };

  async function make() {
    if (disabled || !chosen || !definitions) return false;
    const generation = useUI.getState().documentGeneration;
    let created = false;
    await perform(async () => {
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
      useUI.getState().set({ selectedArtifact: outputSelection(result), selectedStep: result.id });
      setImage(source);
      setChosen(null);
      setChoosingFormat(false);
      onResult?.();
      useUI.getState().set({ notice: "Your joke is ready to edit or share." });
      created = true;
    });
    return created;
  }

  return <section className={`quick-start pane window${inspectorStep ? " layout-inspector" : ""}`}
    aria-label={inspectorStep ? "Inspector" : "Quick ideas"}>
    <div className="pane-heading title-bar"><span className={classic ? "pane-title" : undefined}>{classic && <ThemeIcon name="images" size={16} />}{inspectorStep ? "Inspector" : "Make something terrible"}</span>
      {!inspectorStep && <button onClick={onAllTools ?? onAdvanced}>All tools</button>}</div>
    <div className="quick-content">
      {editing && session && <QuickLayoutEditor key={step.invocation_id} session={session} step={step}
        layout={layout} materials={visibleArtifacts} disabled={disabled} onAdvanced={onAdvanced} onDraft={setDraftTarget}
        ref={editorGuard} onBrowse={onBrowse}
        onHistory={onHistory} onFormats={!inspectorStep ? () => setChoosingFormat(true) : undefined} onDuplicate={() => perform(async () => {
          const current = queries.getQueryData<Session>(["session.get"]);
          if (!current) return;
          await action("branches.create", { name: `Another take ${new Date().toLocaleTimeString()}`,
            expected_revision: current.document_revision });
          useUI.getState().set({ notice: "Original take kept. You’re editing a copy." });
        })} />}
      {!inspectorStep && !editing && !chosen && <>
      {step && <button type="button" onClick={() => setChoosingFormat(false)}>Back to current joke</button>}
      {!step && !!session?.steps.length && <button type="button" onClick={onAdvanced}>Edit in workspace</button>}
      <p>Pick a joke. Use your own picture or our public-domain pigeon. No AI setup or downloads.</p>
      <button disabled={disabled} onClick={onImport}>Use my picture</button>
      {importing && <p role="status">Opening your picture…</p>}
      <label>Picture for previews<select value={image} disabled={disabled} onChange={e => setImage(e.target.value)}>
        <option value="">Use the CC0 pigeon sample</option>
        {visibleArtifacts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
      </select></label>
      <details><summary>Your cast of characters</summary><Cast image={image} disabled={disabled} onUse={setImage} /></details>
      <div className={classic ? "quick-cards classic-idea-cards" : "quick-cards"}>
        {starters.map(starter => <button key={starter.template}
          onClick={() => {
            setChosen(starter);
            setStartingImage(image);
            setTitle(starter.title);
            setCaption(starter.caption);
            setSecond(starter.secondCaption ?? "Probably fine.");
          }}>
          <IdeaPreview image={image} template={starter.template} title={starter.title}
            captions={[starter.caption, starter.secondCaption ?? ""]} slots={layouts.find(l => l.id === starter.template)?.slots.length ?? 0}
            revision={session?.document_revision ?? 0} enabled={!disabled} />
          <strong>{starter.name}</strong><span>{starter.description}</span>
        </button>)}
      </div>
      </>}
      {!inspectorStep && chosen && <form className="quick-form" onSubmit={event => { event.preventDefault(); void make(); }}>
        <button type="button" disabled={busy} onClick={() => void navigate(() => { setChoosingFormat(true); setChosen(null); })}>Back to formats</button>
        <h3>{chosen.name}</h3>
        {step && <p>Creates another image in this take.</p>}
        <InputField ref={headline} label="Headline" maxLength={300} bind={[title, setTitle]} />
        <InputField label="Punchline" maxLength={1000} bind={[caption, setCaption]} />
        {(definitions?.slots.length ?? 0) > 1 && <InputField label="Second caption" maxLength={1000} bind={[second, setSecond]} />}
        <label>Picture<select value={image} onChange={e => setImage(e.target.value)}>
          <option value="">Use the CC0 pigeon sample</option>
          {visibleArtifacts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select></label>
        <button type="button" disabled={disabled} onClick={onImport}>Add my own image</button>
        <div className="quick-editor-actions quick-form-footer">
          <button className="primary" disabled={disabled || !definitions}>{busy ? "Making it…" : "Make this shitpost"}</button>
          <button type="button" disabled={busy} onClick={() => setChosen(null)}>Cancel</button>
        </div>
        <DraftDecision decision={creationDecision} apply={make} discard={() => setChosen(null)}
          blocked={disabled || !definitions} busy={busy} applyLabel="Make this shitpost" />
      </form>}
      {!inspectorStep && <>
      <details><summary>Save a reusable recipe</summary><RecipeStudio /></details>
      <CreativeCollections image={image} title={String(step?.params.title ?? title)} caption={String((step?.params.captions as string[] | undefined)?.[0] ?? caption)} disabled={disabled} />
      <details><summary>Show how it happened</summary><CreationReplay /></details>
      <details><summary>Play a remix challenge</summary><RemixChallenge /></details>
      </>}
      {error && <p role="alert" className="error-text">{error}</p>}
    </div>
  </section>;
}
