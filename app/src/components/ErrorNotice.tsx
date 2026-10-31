import { useEffect, useRef, useState } from "react";
import { AlertTriangle, RotateCcw, X } from "lucide-react";
import { action, run, useSession } from "../data";
import { useUI } from "../store";
export function ErrorNotice({ className = "" }: { className?: string }) {
  const error = useUI((state) => state.error);
  const errorAction = useUI((state) => state.errorAction);
  const { data: session } = useSession();
  const [busy, setBusy] = useState(false);
  const notice = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = notice.current;
    if (error && node?.closest('[role="dialog"]')) {
      node.scrollIntoView?.({ block: "nearest" });
      node.focus({ preventScroll: true });
    }
  }, [error]);
  if (!error) return null;
  return (
    <div
      className={`error-notice ${className}`}
      role="alert"
      ref={notice}
      tabIndex={-1}
    >
      <AlertTriangle size={16} />
      <span>{error}</span>
      {errorAction === "retry-turn" && (
        <button
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
        >
          <RotateCcw size={13} />
          {busy ? "Retrying…" : "Retry turn"}
        </button>
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
