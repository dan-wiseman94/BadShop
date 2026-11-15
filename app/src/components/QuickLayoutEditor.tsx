import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { action, imageUrl, queries, useArtifact, useCoreQuery } from "../data";
import { showError, useUI } from "../store";
import { copyText } from "../native";
import { DraftDecision, useDraftDecision } from "./DraftDecision";
import { RpcError } from "../rpc";
import { useEditorPreview } from "../useEditorPreview";
import { EditorPreviewControls } from "./EditorPreviewControls";
import type { MaterialTarget } from "./Studio";
import type { Artifact, Params, Session, Step } from "../types";
import type { ResponseLayout } from "../wire.generated";

export function layoutForImage(session: Session | undefined, image: string | null): Step | undefined {
  if (!session || !image) return;
  const producers = new Map<string, Step>();
  for (const step of session.steps) {
    for (const id of [...step.outputs, ...(step.previous_outputs ?? []), ...Object.values(step.output_ports ?? {})]) producers.set(id, step);
  }
  const found = new Set<Step>();
  const visited = new Set<string>();
  const pending = [image];
  while (pending.length) {
    const id = pending.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    const producer = producers.get(id);
    if (!producer) continue;
    if (producer.tool === "layout") {
      found.add(producer);
      continue;
    }
    for (const [input, [invocation, port]] of Object.entries(producer.input_bindings ?? {})) {
      const output = producers.get(input)?.invocation_id === invocation ? input
        : session.steps.find(step => step.invocation_id === invocation)?.output_ports?.[port];
      if (output) pending.push(output);
    }
    // Legacy records can contain resolved references without explicit port bindings.
    for (const value of Object.values(producer.params).flat()) {
      if (typeof value === "string" && producers.has(value) && !(value in (producer.input_bindings ?? {}))) pending.push(value);
    }
  }
  return found.size === 1 ? found.values().next().value : undefined;
}

function Picture({ id }: { id: string }) {
  const { data } = useArtifact(id, true);
  return data ? <img className="quick-slot-thumb" src={imageUrl(data)} alt="" /> : null;
}

type Draft = { revision: number; params: Params };

export function QuickLayoutEditor({ session, step, layout, materials, disabled, onAdvanced, onHistory, onDuplicate, onFormats, onDraft, onBrowse, ref }: {
  session: Session;
  step: Step;
  layout: ResponseLayout;
  materials: Artifact[];
  disabled: boolean;
  onAdvanced: () => void;
  onHistory: (stepId?: string) => void;
  onDuplicate: () => Promise<void>;
  onFormats?: () => void;
  onDraft: (stepId: string | null) => void;
  onBrowse?: (target: MaterialTarget) => void;
  ref?: Ref<() => Promise<boolean>>;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [retainedImport, setRetainedImport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blocker, setBlocker] = useState("");
  const [failure, setFailure] = useState<{ stepId: string; revision: number } | null>(null);
  const decision = useDraftDecision(!!draft, busy);
  const { data: tools } = useCoreQuery("tools.list");
  const schema = tools?.find(tool => tool.name === "layout")?.schema.properties as {
    title?: { maxLength?: number };
    captions?: { items?: { maxLength?: number } };
  } | undefined;
  const titleLimit = schema?.title?.maxLength;
  const captionLimit = schema?.captions?.items?.maxLength;
  const selected = useUI(state => state.selectedElement);
  const captionFields = useRef<(HTMLTextAreaElement | null)[]>([]);
  useEffect(() => {
    if (selected?.stepId === step.id && selected.focusText && selected.slotIndex !== undefined)
      captionFields.current[selected.slotIndex]?.focus();
  }, [selected, step.id]);
  const params = draft?.params ?? step.params;
  const stale = !!draft && draft.revision !== session.document_revision;
  const unavailable = disabled || busy;
  const preview = useEditorPreview({
    session,
    target: { step_id: step.id },
    scope: "final",
    params,
    active: !!draft && !stale && !unavailable && !session.turn_running && !session.batch_running,
    dirty: !!draft,
  });
  const candidates = materials.filter(artifact => {
    if (!artifact.produced_by) return true;
    const producer = session.steps.find(item => item.id === artifact.produced_by);
    return !!producer && producer.index < step.index;
  });
  function slotPictures(fields: Params) {
    const images = (fields.images as string[] | undefined) ?? [];
    const slots = fields.image_slots as number[] | null;
    return layout.slots.map((_, i) => images[slots ? slots.indexOf(i) : i] ?? "");
  }

  const pictures = slotPictures(params);
  const captions = (params.captions as string[] | undefined) ?? [];
  const currentParams = useRef(params);
  currentParams.current = params;
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  function update(fields: Params, acceptedRevision?: number) {
    setBlocker("");
    onDraft(step.invocation_id ?? null);
    setDraft(previous => ({
      revision: acceptedRevision ?? previous?.revision ?? session.document_revision,
      params: { ...(previous?.params ?? step.params), ...fields },
    }));
  }

  function replace(index: number, id: string, all = false, acceptedRevision?: number) {
    setBlocker("");
    onDraft(step.invocation_id ?? null);
    setDraft(previous => {
      const fields = previous?.params ?? step.params;
      const next = slotPictures(fields).map((current, i) => all || i === index ? id : current);
      const images = next.filter(Boolean);
      const slots = next.flatMap((image, i) => image ? [i] : []);
      return {
        revision: acceptedRevision ?? previous?.revision ?? session.document_revision,
        params: { ...fields, images, image_slots: fields.image_slots || slots.some((slot, i) => slot !== i) ? slots : null },
      };
    });
  }

  function browse(index: number) {
    const revision = session.document_revision;
    const generation = useUI.getState().documentGeneration;
    const fingerprint = (steps: Step[]) => JSON.stringify(steps.slice(step.index - 1).map(item =>
      [item.invocation_id, item.params, item.input_bindings, item.output_ports, item.status]));
    const before = fingerprint(session.steps);
    const isCurrent = (expected: number) => {
      const current = queries.getQueryData<Session>(["session.get"]);
      return alive.current && slotPictures(currentParams.current)[index] === pictures[index] &&
        useUI.getState().documentGeneration === generation && current?.document_revision === expected &&
        current.context?.branch_id === session.context?.branch_id && fingerprint(current.steps) === before;
    };
    onBrowse?.({
      label: `Replace picture in slot ${index + 1}`,
      beforeStepIndex: step.index,
      revision,
      isCurrent: expected => expected === revision && isCurrent(expected),
      assign: (id, receipt) => {
        if (!receipt && isCurrent(revision)) {
          replace(index, id);
          return;
        }
        if (receipt?.base_revision !== revision || receipt.result_revision === undefined || !isCurrent(receipt.result_revision))
          throw new Error("Picture added to Materials. The edit target changed, so the slot was left as it was.");
        replace(index, id, false, receipt.result_revision);
        setRetainedImport(true);
      },
    });
  }

  function clearDraft() {
    preview.clear();
    setDraft(null);
    setRetainedImport(false);
    onDraft(null);
    setBlocker("");
    setError("");
  }

  function discardDraft() {
    clearDraft();
    if (retainedImport)
      useUI.getState().set({ notice: "Picture added to Materials; changes to this joke were canceled." });
  }

  async function apply(replay: "local" | "none" = "local") {
    if (!draft || stale || unavailable || !preview.canApply()) return false;
    const current = queries.getQueryData<Session>(["session.get"]);
    if (current?.document_revision !== draft.revision || current.context?.branch_id !== session.context?.branch_id) {
      setError("The project changed. Reload saved controls before applying.");
      return false;
    }
    preview.clear();
    setBusy(true);
    setError("");
    setFailure(null);
    useUI.getState().set({ notice: null });
    try {
      const result = await action("steps.edit", { step_id: step.id, params: draft.params, replay });
      if (result.replay?.status === "blocked") {
        setBlocker(result.replay.blocker?.message ?? "This edit needs replay from History.");
        return false;
      }
      clearDraft();
      if (result.replay?.status === "failed") {
        setFailure({ stepId: result.replay.failed_step?.step_id ?? step.id, revision: result.replay.revision });
        setError(`Changes were saved, but replay failed. ${result.replay.failed_step?.message ?? ""}`);
        return false;
      }
      useUI.getState().set({ notice: replay === "none" ? "Changes saved. Replay from History to update the image." : "Changes applied." });
      return true;
    } catch (problem) {
      if (problem instanceof RpcError && problem.operationId) showError(problem);
      setError(problem instanceof Error ? problem.message : String(problem));
      return false;
    } finally {
      setBusy(false);
    }
  }

  useImperativeHandle(ref, () => decision.request);

  async function navigate(next: () => void) {
    if (await decision.request()) next();
  }

  return <form className="quick-form" aria-label="Edit this joke" onSubmit={event => { event.preventDefault(); void apply(); }}>
    <h3>Edit this joke</h3>
    <label>Headline<textarea rows={2} value={String(params.title ?? "")} maxLength={titleLimit}
      disabled={unavailable} onChange={event => update({ title: event.target.value })} /></label>
    {layout.slots.map((slot, index) => {
      const name = layout.slots.filter(item => item.name === slot.name).length === 1 && slot.name
        ? slot.name : String(index + 1);
      return <div className="quick-slot" key={index}>
        <label>Caption {name}<textarea ref={node => { captionFields.current[index] = node; }} rows={2} maxLength={captionLimit} value={captions[index] ?? ""}
          disabled={unavailable} onChange={event => {
            const next = Array.from({ length: Math.max(index + 1, captions.length) }, (_, i) => captions[i] ?? "");
            next[index] = event.target.value;
            update({ captions: next });
          }} /></label>
        <div className="quick-slot-picture">
          {pictures[index] && <Picture id={pictures[index]} />}
          <label>Picture for {name}<select value={pictures[index]} disabled={unavailable}
            onChange={event => replace(index, event.target.value)}>
            <option value="">No picture</option>
            {pictures[index] && !candidates.some(candidate => candidate.id === pictures[index]) &&
              <option value={pictures[index]}>{session.artifacts[pictures[index]]?.label ?? "Current picture"}</option>}
            {candidates.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
          </select></label>
        </div>
        {onBrowse && <button type="button" disabled={unavailable || stale} onClick={() => browse(index)}>
          Find a replacement for {name}
        </button>}
        {layout.slots.length > 1 && pictures[index] && pictures.some(id => id !== pictures[index]) &&
          <button type="button" disabled={unavailable} onClick={() => replace(index, pictures[index], true)}>
            Use this picture in all slots
          </button>}
      </div>;
    })}
    {draft && !stale && <section aria-label="Draft preview">
      <EditorPreviewControls preview={preview} />
      {preview.result?.plan && <p>Changes this step. Checks {preview.result.plan.later_steps} later steps and reuses unchanged results.</p>}
      {preview.result?.plan?.message && <p>{preview.result.plan.message}</p>}
      {preview.result?.image && <>
        <p>Draft preview · {preview.result.plan?.scope === "final" ? "Includes later steps" : "This step only"}</p>
        <img alt="Uncommitted joke preview" src={preview.result.image}
          style={{ width: "100%", maxHeight: "32dvh", objectFit: "contain", imageRendering: "pixelated" }} />
      </>}
    </section>}
    {stale && <div role="alert">The project changed while you were editing.
      <button type="button" onClick={clearDraft}>Reload saved controls</button>
      <button type="button" onClick={() => void copyText(JSON.stringify(params, null, 2))
        .then(() => useUI.getState().set({ notice: "Draft values copied." })).catch(showError)}>Copy draft values</button>
    </div>}
    {blocker && <div role="alert">{blocker} <button type="button" onClick={() => onHistory()}>Open History</button>
      <button type="button" disabled={unavailable || stale || preview.busy} onClick={() => void apply("none")}>Save changes without replay</button></div>}
    {error && <p role="alert" className="error-text">{error}</p>}
    {failure?.revision === session.document_revision && <div className="quick-editor-actions">
      <button type="button" disabled={unavailable} onClick={() => void action("history.undo", { expected_revision: failure.revision })
        .catch(showError)}>Undo edit</button>
      <button type="button" onClick={() => onHistory(failure.stepId)}>Inspect failed step</button>
    </div>}
    <div className="quick-editor-actions quick-form-footer">
      <button className="primary" disabled={unavailable || stale || preview.busy || !draft}>Apply changes</button>
      {draft && <button type="button" disabled={busy} onClick={discardDraft}>Cancel</button>}
      <button type="button" disabled={unavailable} onClick={() => void navigate(() => { void onDuplicate(); })}>Duplicate take</button>
      {onFormats && <button type="button" disabled={busy} onClick={() => void navigate(onFormats)}>Try another format</button>}
      <button type="button" disabled={busy} onClick={onAdvanced}>Edit in workspace</button>
    </div>
    <DraftDecision decision={decision} apply={apply} discard={discardDraft} blocked={unavailable || stale || preview.busy} busy={busy} />
  </form>;
}
