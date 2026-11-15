import { useEffect, useRef } from "react";

export function useDraftDecision(dirty: boolean, busy: boolean) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef<((proceed: boolean) => void) | null>(null);

  useEffect(() => () => { pending.current?.(false); }, []);

  async function request() {
    if (busy) return false;
    if (!dirty) return true;
    if (!dialog.current || dialog.current.open) return false;
    dialog.current.showModal();
    return new Promise<boolean>(resolve => { pending.current = resolve; });
  }

  function finish(proceed: boolean) {
    const resolve = pending.current;
    pending.current = null;
    dialog.current?.close();
    resolve?.(proceed);
  }

  return { dialog, request, finish };
}

export function DraftDecision({ decision, apply, discard, blocked, busy, applyLabel = "Apply changes" }: {
  decision: ReturnType<typeof useDraftDecision>;
  apply: () => Promise<boolean>;
  discard: () => void;
  blocked: boolean;
  busy: boolean;
  applyLabel?: string;
}) {
  return <dialog className="quick-draft-decision" ref={decision.dialog} aria-label="Unsaved changes to this joke"
    onCancel={event => { event.preventDefault(); if (!busy) decision.finish(false); }}>
    <p>Keep your changes before leaving this joke?</p>
    <div className="quick-editor-actions">
      <button type="button" disabled={blocked || busy} onClick={async () => decision.finish(await apply())}>{applyLabel}</button>
      <button type="button" disabled={busy} onClick={() => { discard(); decision.finish(true); }}>Discard changes</button>
      <button type="button" disabled={busy} autoFocus onClick={() => decision.finish(false)}>Keep editing</button>
    </div>
  </dialog>;
}
