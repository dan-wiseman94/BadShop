import { useCallback, useEffect, useRef, useState } from "react";
import { action, queries, reconcileSessionSnapshot } from "./data";
import { onCloseRequested, projectPath } from "./native";
import { rpc } from "./rpc";
import { showError, useUI } from "./store";
import { ErrorNotice } from "./components/ErrorNotice";
import type { Session } from "./types";

type Destination =
  | { kind: "new"; name: string }
  | { kind: "open"; path: string }
  | { kind: "restore" }
  | { kind: "close" };
type Pending = {
  destination: Destination;
  session: Session;
  resolve: (proceed: boolean) => void;
};

async function snapshot() {
  const session = await rpc.request(
    "session.get",
    undefined,
    AbortSignal.timeout(5000),
  );
  queries.setQueryData<Session>(["session.get"], (previous) =>
    reconcileSessionSnapshot(session, previous),
  );
  return session;
}

/** A user save baseline is distinct from the core's crash-recovery autosave. */
export function useSessionActions() {
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const current = useRef<Pending | null>(null);
  const working = useRef(false);

  const finish = useCallback((proceed: boolean) => {
    const item = current.current;
    current.current = null;
    setPending(null);
    item?.resolve(proceed);
  }, []);
  const cancel = useCallback(() => {
    if (!working.current) finish(false);
  }, [finish]);

  const save = useCallback(
    async (as = false, expected?: Session): Promise<boolean> => {
      const before = await snapshot();
      if (
        expected &&
        (before.id !== expected.id ||
          before.document_revision !== expected.document_revision)
      )
        throw new Error(
          "The session changed while this dialog was open. Review it and choose again.",
        );
      const path = before.path && !as ? before.path : await projectPath(true);
      if (!path) return false;
      const latest = await snapshot();
      if (
        latest.id !== before.id ||
        latest.document_revision !== before.document_revision
      )
        throw new Error(
          "The session changed while choosing a file. Save the current session again.",
        );
      const guard = { expected_revision: latest.document_revision };
      if (before.path && !as) await action("session.save", guard);
      else await action("session.save_as", { path, ...guard });
      useUI.getState().set({ notice: `Saved to ${path}` });
      return true;
    },
    [],
  );

  const replace = useCallback(
    async (destination: Destination, session: Session, discard: boolean) => {
      const guard = {
        expected_revision: session.document_revision,
        discard_unsaved: discard,
      };
      if (destination.kind === "new")
        await action("session.new", { name: destination.name, ...guard });
      if (destination.kind === "open")
        await action("session.open", { path: destination.path, ...guard });
      if (destination.kind === "restore")
        await action("session.restore", guard);
    },
    [],
  );

  const request = useCallback(
    async (destination: Destination): Promise<boolean> => {
      if (current.current || working.current) return false;
      let session: Session;
      try {
        session = await snapshot();
      } catch (error) {
        if (destination.kind !== "close") throw error;
        const cached = queries.getQueryData<Session>(["session.get"]);
        if (!cached) return true; // No document has been loaded in this window yet.
        // A disconnected cache cannot prove there were no changes after its last refresh.
        session = { ...cached, unsaved_changes: true };
      }
      if (current.current || working.current) return false;
      if (session.turn_running && destination.kind !== "close")
        throw new Error("Stop the agent before switching sessions.");
      if (!session.unsaved_changes && !session.turn_running) {
        await replace(destination, session, false);
        return true;
      }
      useUI.getState().set({ error: null, errorAction: null });
      return new Promise<boolean>((resolve) => {
        const item = { destination, session, resolve };
        current.current = item;
        setPending(item);
      });
    },
    [replace],
  );

  const decide = useCallback(
    async (choice: "save" | "discard") => {
      const item = current.current;
      if (!item || working.current) return;
      working.current = true;
      setBusy(true);
      useUI.getState().set({ error: null, errorAction: null });
      try {
        let expected = item.session;
        if (
          item.destination.kind === "close" &&
          item.session.turn_running &&
          useUI.getState().status === "ready"
        ) {
          await action("chat.stop");
          expected = await snapshot();
        }
        if (choice === "save") {
          if (!(await save(false, expected))) return; // Canceling the file picker keeps this dialog.
          expected = await snapshot();
          if (expected.id !== item.session.id)
            throw new Error(
              "The active session changed. Review it before continuing.",
            );
          if (expected.unsaved_changes)
            throw new Error(
              "The session changed after Save. Save the latest changes before continuing.",
            );
        }
        if (
          item.destination.kind === "close" &&
          useUI.getState().status === "ready"
        ) {
          const latest = await snapshot();
          if (
            latest.id !== expected.id ||
            latest.document_revision !== expected.document_revision ||
            latest.turn_running
          )
            throw new Error(
              "The session changed while this dialog was open. Review it and choose again.",
            );
        }
        await replace(item.destination, expected, choice === "discard");
        finish(true);
      } catch (error) {
        // A tool or another client may have changed the session while the dialog was open.
        // Keep the dialog open, display the error, and require a fresh explicit choice.
        try {
          const latest = await snapshot();
          const next = { ...item, session: latest };
          current.current = next;
          setPending(next);
        } catch {
          /* The original failure is more useful than a disconnected refresh. */
        }
        showError(error);
      } finally {
        working.current = false;
        setBusy(false);
      }
    },
    [finish, replace, save],
  );

  useEffect(() => {
    let disposed = false;
    const listener = onCloseRequested(async () => {
      try {
        return await request({ kind: "close" });
      } catch (error) {
        showError(error);
        return false;
      }
    });
    void listener
      .then((off) => {
        if (disposed) off();
      })
      .catch(showError);
    return () => {
      disposed = true;
      void listener.then((off) => off()).catch(() => {});
      current.current?.resolve(false);
      current.current = null;
    };
  }, [request]);

  const open = useCallback(async () => {
    const path = await projectPath(false);
    return path ? request({ kind: "open", path }) : false;
  }, [request]);

  return { pending, busy, request, open, save, cancel, decide };
}

export function SaveChangesDialog({
  actions,
}: {
  actions: ReturnType<typeof useSessionActions>;
}) {
  const { pending, busy, cancel, decide } = actions;
  if (!pending) return null;
  const closing = pending.destination.kind === "close";
  const stopping = closing && pending.session.turn_running;
  return (
    <div className="modal-backdrop">
      <section
        className="modal save-changes-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="save-changes-title"
        aria-describedby="save-changes-description"
      >
        <h2 id="save-changes-title">
          Save changes to “{pending.session.name}”?
        </h2>
        <p id="save-changes-description">
          {stopping
            ? "The agent is still working. Continuing will stop it. "
            : ""}
          Save your work to a project file before{" "}
          {closing ? "closing badshop" : "switching sessions"}.
        </p>
        <ErrorNotice />
        <div className="dialog-actions">
          <button onClick={cancel} disabled={busy} autoFocus>
            Cancel
          </button>
          <button onClick={() => void decide("discard")} disabled={busy}>
            {stopping ? "Stop & discard" : "Discard changes"}
          </button>
          <button
            className="primary"
            onClick={() => void decide("save")}
            disabled={busy}
          >
            {busy
              ? "Working…"
              : stopping
                ? "Stop, save & close"
                : closing
                  ? "Save & close"
                  : "Save & continue"}
          </button>
        </div>
      </section>
    </div>
  );
}
