import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../appearance";
import { action, imageUrl, queries, useArtifact, useCoreQuery, useSession } from "../data";
import { directionLabel, renamedDirection } from "../directions";
import { useUI } from "../store";
import type { Session } from "../types";
import { useOperation } from "../useOperation";
import type { ResponseBranchSummary } from "../wire.generated";
import { Button } from "./Button";
import "../versions.css";

function changeBlock(session: Session | undefined, ready: boolean) {
  if (!ready) return "Wait for BadShop to reconnect before changing takes.";
  if (!session) return "Loading the project…";
  if (session.read_only_reason) return session.read_only_reason;
  if (session.turn_running || session.batch_running ||
      session.steps.some(step => ["proposed", "approved", "running"].includes(step.status)))
    return "Finish or stop the current work before changing takes.";
  return "";
}

function TakeImage({ take, thumbnail }: { take: ResponseBranchSummary; thumbnail: boolean }) {
  const motion = useUI(state => state.motion);
  const still = useReducedMotion(motion);
  const { data, error } = useArtifact(take.preview_id, thumbnail, still);
  const src = imageUrl(data);
  return <>
    <div className="take-image">
      {src ? <img src={src} alt={thumbnail ? "" : directionLabel(take.name)} /> :
        <span>{error ? "Preview unavailable" : take.preview_id ? "Loading image…" : "No preview"}</span>}
    </div>
    {!thumbnail && data?.meta && <small>{data.meta.width} × {data.meta.height}</small>}
  </>;
}

export function Versions({ onClose, onBeforeChange, onViewImage }: {
  onClose: () => void;
  onBeforeChange: () => Promise<boolean>;
  onViewImage?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { data: session } = useSession();
  const { data: branches, error: listError } = useCoreQuery("branches.list");
  const { busy, error, notice, perform, setNotice } = useOperation();
  const ready = useUI(state => state.status === "ready");
  const blocked = changeBlock(session, ready);
  const disabled = busy || !!blocked;
  const [name, setName] = useState("");
  const [fromStep, setFromStep] = useState("");
  const [selection, setSelection] = useState<string[]>([]);
  const [rename, setRename] = useState<{ id: string; name: string } | null>(null);
  const [remove, setRemove] = useState<string | null>(null);
  const takes = branches?.branches ?? [];
  const compared = selection.flatMap(id => takes.filter(take => take.id === id));

  useEffect(() => {
    const panel = dialog.current;
    const opener = document.activeElement;
    panel?.showModal();
    return () => {
      panel?.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  async function change(work: (revision: number) => Promise<void>, duplicated = false) {
    const generation = useUI.getState().documentGeneration;
    if (!await onBeforeChange()) return;
    const current = queries.getQueryData<Session>(["session.get"]);
    const reason = changeBlock(current, useUI.getState().status === "ready");
    if (generation !== useUI.getState().documentGeneration)
      throw new Error("The project changed. Review the available takes before trying again.");
    if (reason || !current) throw new Error(reason);
    await work(current.document_revision);
    const refreshed = queries.getQueryData<NonNullable<typeof branches>>(["branches.list"]);
    const active = refreshed?.branches.find(take => take.id === refreshed.active_id);
    const editing = active ? `Editing: ${directionLabel(active.name)}` : "";
    const unsaved = duplicated && !current.path
      ? "Takes are stored inside this project. Save project to keep them on disk."
      : "";
    setNotice([editing, unsaved].filter(Boolean).join(". "));
  }

  return <dialog
    ref={dialog}
    className="modal versions-dialog"
    aria-label="Versions"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
  >
    <header className="versions-heading">
      <h2>Versions</h2>
      <Button onClick={onClose} disabled={busy} label="Close Versions" />
    </header>
    <form className="versions-duplicate" onSubmit={event => {
      event.preventDefault();
      if (disabled || !name.trim()) return;
      void perform(() => change(async revision => {
        await action("branches.create", {
          name: name.trim(),
          ...(fromStep && { from_step: fromStep }),
          expected_revision: revision,
        });
        setName("");
        setFromStep("");
      }, true));
    }}>
      <label>New take name<input value={name} maxLength={200} required onChange={event => setName(event.target.value)} /></label>
      <label>Start from<select value={fromStep} onChange={event => setFromStep(event.target.value)}>
        <option value="">Current state</option>
        {session?.steps.filter(step => step.status === "done").map(step =>
          <option key={step.id} value={step.id}>Step {step.index}: {step.tool}</option>)}
      </select></label>
      <Button disabled={disabled || !name.trim()} label="Duplicate" />
    </form>
    {blocked && <p className="muted">{blocked}</p>}
    {(error || listError) && <p className="error-banner" role="alert">{error || String(listError)}</p>}
    {notice && <p role="status">{notice}</p>}
    {!!takes.length && <p className="muted">Select up to two takes to compare.</p>}
    {compared.length > 0 && <section className="versions-comparison" aria-label="Take comparison">
      {compared.map(take => <figure key={take.id}>
        <TakeImage take={take} thumbnail={false} />
        <figcaption>{directionLabel(take.name)}</figcaption>
        {onViewImage && take.preview_id && <Button label="Inspect full size" disabled={busy}
          onClick={() => {
            useUI.getState().set({ selectedArtifact: take.preview_id, selectedStep: null, viewerZoom: 1 });
            onViewImage();
            onClose();
          }} />}
      </figure>)}
    </section>}
    <div className="versions-takes">
      {takes.map(take => {
        const active = take.id === branches?.active_id;
        const label = directionLabel(take.name);
        const selected = compared.some(item => item.id === take.id);
        return <article className="versions-take" key={take.id} aria-label={label}>
          <TakeImage take={take} thumbnail />
          <div className="take-controls">
            <div className="take-title"><strong>{label}</strong>{active && <span>Active</span>}</div>
            <small>{take.automatic ? "Automatic" : "Manual"} · {take.step_count} {take.step_count === 1 ? "step" : "steps"}</small>
            <div className="take-actions">
              <label><input type="checkbox" checked={selected}
                disabled={!selected && compared.length === 2}
                onChange={event => setSelection(event.target.checked ? [...compared.map(item => item.id), take.id] :
                  selection.filter(id => id !== take.id))} />Compare</label>
              {!active && <Button label="Open take" disabled={disabled} onClick={() =>
                void perform(() => change(async revision => {
                  await action("branches.switch", { id: take.id, expected_revision: revision });
                }))} />}
              <Button label="Rename" disabled={disabled} onClick={() => {
                setRemove(null);
                setRename({ id: take.id, name: take.name === label ? label : label.slice("Round · ".length) });
              }} />
              {take.automatic && <Button label="Keep" disabled={disabled} onClick={() =>
                void perform(async () => {
                  await action("branches.rename", { id: take.id, name: take.name });
                  setNotice(`Kept ${label}.`);
                })} />}
              {!active && take.id !== session?.undo_branch_id &&
                <Button label="Delete" disabled={disabled} onClick={() => { setRename(null); setRemove(take.id); }} />}
            </div>
            {rename?.id === take.id && <form className="take-actions" onSubmit={event => {
              event.preventDefault();
              if (disabled || !rename.name.trim()) return;
              void perform(async () => {
                await action("branches.rename", { id: take.id, name: renamedDirection(take.name, rename.name.trim()) });
                setRename(null);
              });
            }}>
              <label>Take name<input value={rename.name} autoFocus required maxLength={200 - (take.name.length - label.length)}
                onChange={event => setRename({ id: take.id, name: event.target.value })} /></label>
              <Button label="Save name" disabled={disabled || !rename.name.trim()} />
              <Button type="button" label="Cancel" onClick={() => setRename(null)} disabled={busy} />
            </form>}
            {remove === take.id && <div className="take-actions">
              <span>Delete {label}?</span>
              <Button label="Delete take" disabled={disabled} onClick={() => void perform(async () => {
                await action("branches.remove", { id: take.id });
                setSelection(previous => previous.filter(id => id !== take.id));
                setRemove(null);
              })} />
              <Button label="Cancel" onClick={() => setRemove(null)} disabled={busy} />
            </div>}
          </div>
        </article>;
      })}
    </div>
  </dialog>;
}
