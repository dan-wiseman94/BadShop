import { Button } from "./Button";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, RotateCcw, X } from "lucide-react";
import { action, run, useSession } from "../data";
import { useUI } from "../store";
import { rpc } from "../rpc";
export function ErrorNotice({ className = "" }: { className?: string }) {
  const error = useUI((state) => state.error);
  const errorAction = useUI((state) => state.errorAction);
  const operationId = useUI((state) => state.errorOperationId);
  const [receipt, setReceipt] = useState<string | null>(null);
  const { data: session } = useSession();
  const [busy, setBusy] = useState(false);
  const notice = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setReceipt(null);
    const node = notice.current;
    if (error && node?.closest('[role="dialog"]')) {
      node.scrollIntoView?.({ block: "nearest" });
      node.focus({ preventScroll: true });
    }
  }, [error]);
  if (!error) return null;
  return (
    <div className={`error-notice ${className}`} role="alert" ref={notice} tabIndex={-1}>
      <AlertTriangle size={16} />
      <span>{error}</span>
      {operationId && <Button label="Check operation" disabled={busy} onClick={() => run(async () => {
        setBusy(true);
        try {
          const result = await rpc.request('operations.get', { operation_id: operationId });
          setReceipt(result.status === 'committed' ? 'This operation committed. Refresh the session to inspect its result.'
            : result.status === 'pending' ? 'This operation was accepted, but its final outcome is unknown. Inspect the session before repeating it.'
            : 'No retained receipt was found. Inspect the session before repeating this operation.');
        } finally { setBusy(false); }
      })} />}
      {receipt && <span role="status">{receipt}</span>}
      {errorAction === "retry-turn" && (
        <Button
          disabled={busy || session?.turn_running}
          onClick={() =>
            run(async () => {
              setBusy(true);
              try {
                await action("chat.retry");
                useUI.getState().set({ error: null, errorAction: null });
              } finally {
                setBusy(false);
              }
            })
          }
          label={busy ? "Retrying…" : "Retry turn"}
          icon={RotateCcw}
          iconSize={13}
        />
      )}
      <button
        aria-label="Dismiss error"
        onClick={() => useUI.getState().set({ error: null, errorAction: null })}
      >
        <X size={14} />
      </button>
    </div>
  );
}
