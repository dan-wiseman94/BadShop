import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  FolderOpen,
  Save,
  Plus,
  Download,
  Settings2,
  AlertTriangle,
  X,
  Copy,
  RefreshCw,
  FileJson,
  ClipboardPaste,
} from "lucide-react";
import { Chat } from "./components/Chat";
import { Viewer } from "./components/Viewer";
import { Timeline, ToolPalette } from "./components/Timeline";
import { Settings, Welcome } from "./components/Settings";
import { ErrorNotice } from "./components/ErrorNotice";
import { SaveChangesDialog, useSessionActions } from "./sessionActions";
import { usePaneLayout } from "./layout";
import {
  action,
  importBlob,
  run,
  startCore,
  useCoreQuery,
  useSession,
} from "./data";
import { useUI } from "./store";
import {
  clipboardImage,
  copyText,
  diagnostics,
  native,
  onFileDrop,
  pickImages,
  projectPath,
  restart,
  reveal,
} from "./native";
import type { ApprovalMode } from "./types";
function Resizer({
  side,
  onResize,
  value,
  maximum,
  onReset,
}: {
  side: "left" | "right";
  onResize: (delta: number) => void;
  value: number;
  maximum: number;
  onReset: () => void;
}) {
  const start = useRef(0);
  return (
    <div
      className="resizer"
      role="separator"
      aria-label={`Resize ${side === "left" ? "chat" : "steps"} pane`}
      aria-orientation="vertical"
      aria-valuenow={Math.round(value)}
      aria-valuemin={side === "left" ? 260 : 270}
      aria-valuemax={Math.round(maximum)}
      tabIndex={0}
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
          event.preventDefault();
        if (event.key === "ArrowLeft") onResize(side === "left" ? -16 : 16);
        if (event.key === "ArrowRight") onResize(side === "left" ? 16 : -16);
        if (event.key === "Home")
          onResize((side === "left" ? 260 : 270) - value);
        if (event.key === "End") onResize(maximum - value);
      }}
      onPointerDown={(event) => {
        start.current = event.clientX;
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const delta = event.clientX - start.current;
        start.current = event.clientX;
        onResize(side === "left" ? delta : -delta);
      }}
    >
      <span />
    </div>
  );
}
export default function App() {
  const { data: session, error: sessionError } = useSession();
  const { data: profiles } = useCoreQuery("providers.list");
  const ui = useUI();
  const [attachments, setAttachments] = useState<string[]>([]);
  const { workbench, widths, resize, reset, contentWidth } = usePaneLayout();
  const documents = useSessionActions();
  const [welcome, setWelcome] = useState(
    !localStorage.getItem("badshop.welcome"),
  );
  const [menu, setMenu] = useState(false);
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const [restoredDismissed, setRestoreDismissed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const previousSession = useRef<string | undefined>(undefined);
  const sessionMenu = useRef<HTMLDivElement>(null);
  useEffect(() => startCore(), []);
  useEffect(() => {
    if (previousSession.current && previousSession.current !== session?.id) {
      setAttachments([]);
      useUI.getState().set({ selectedStep: null, selectedArtifact: null });
    }
    previousSession.current = session?.id;
  }, [session?.id]);
  useEffect(() => {
    setAttachments([]);
  }, [ui.documentGeneration]);
  useEffect(() => {
    if (!session) return;
    setAttachments((previous) => {
      const valid = previous.filter((id) => session.artifacts[id]);
      return valid.length === previous.length ? previous : valid;
    });
  }, [session?.artifacts]);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () =>
      (document.documentElement.dataset.theme =
        ui.theme === "system" ? (media.matches ? "dark" : "light") : ui.theme);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [ui.theme]);
  const addPath = useCallback(
    async (path: string) => {
      if (path.toLowerCase().endsWith(".badshop")) {
        return documents.request({ kind: "open", path });
      }
      const result = await action("artifacts.import", { path });
      setAttachments((previous) => [...previous, result.working.id]);
      useUI.getState().set({ selectedArtifact: result.working.id });
      return true;
    },
    [documents.request],
  );
  const addBlob = useCallback(async (blob: Blob, name?: string) => {
    const result = await importBlob(blob, name);
    setAttachments((previous) => [...previous, result.working.id]);
    useUI.getState().set({ selectedArtifact: result.working.id });
  }, []);
  const importImages = useCallback(() => {
    if (native)
      run(async () => {
        const paths = await pickImages();
        for (const path of paths ?? []) await addPath(path);
      });
    else fileInput.current?.click();
  }, [addPath]);
  useEffect(() => {
    let disposed = false;
    const unlisten = onFileDrop((paths) =>
      run(async () => {
        for (const path of paths) if (!(await addPath(path))) break;
      }),
    );
    void unlisten.then((fn) => {
      if (disposed) fn();
    });
    return () => {
      disposed = true;
      void unlisten.then((fn) => fn());
    };
  }, [addPath]);
  const save = useCallback(
    (as = false) => run(() => documents.save(as)),
    [documents.save],
  );
  useEffect(() => {
    if (!menu) return;
    const closeOutside = (event: PointerEvent) => {
      if (!sessionMenu.current?.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [menu]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (documents.pending) {
          documents.cancel();
          return;
        }
        setNewSessionOpen(false);
        if (useUI.getState().pick) {
          useUI.getState().set({ pick: null });
          return;
        }
        useUI
          .getState()
          .set({ settingsOpen: false, paletteOpen: false, pick: null });
        setMenu(false);
      }
      if (document.querySelector('[role="dialog"]')) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        save(event.shiftKey);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o") {
        event.preventDefault();
        run(documents.open);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [save, documents.open, documents.pending, documents.cancel]);
  useEffect(() => {
    if (!ui.notice) return;
    const timer = setTimeout(
      () => useUI.getState().set({ notice: null }),
      6000,
    );
    return () => clearTimeout(timer);
  }, [ui.notice]);
  const paste = (event: React.ClipboardEvent) => {
    const images = Array.from(event.clipboardData.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    if (images.length) {
      event.preventDefault();
      event.stopPropagation();
      run(async () => {
        for (const image of images) await addBlob(image, image.name);
      });
    }
  };
  const exportImage = () =>
    run(async () => {
      const id =
        ui.selectedArtifact ??
        session?.steps.find((step) => step.id === ui.selectedStep)
          ?.outputs[0] ??
        session?.steps
          .slice()
          .reverse()
          .find((step) => step.outputs.length)?.outputs[0] ??
        Object.values(session?.artifacts ?? {})[0]?.id;
      if (!id) throw new Error("Add an image or run a tool before exporting.");
      const result = await action("export", { artifact_id: id });
      useUI.getState().set({ notice: `Exported to ${result.path}` });
      await reveal(result.path);
    });
  useEffect(() => {
    if (ui.pick) return;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    const previous = document.activeElement as HTMLElement | null;
    const focusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]',
        ),
      ).filter((node) => node.getClientRects().length > 0);
    focusable()[0]?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const nodes = focusable();
      const first = nodes[0];
      const last = nodes.at(-1);
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !dialog.contains(document.activeElement))
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !dialog.contains(document.activeElement))
      ) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      previous?.focus();
    };
  }, [
    ui.settingsOpen,
    ui.paletteOpen,
    welcome,
    ui.status,
    ui.pick,
    newSessionOpen,
    documents.pending,
  ]);
  const closeWelcome = () => {
    localStorage.setItem("badshop.welcome", "1");
    setWelcome(false);
  };
  const disconnected = ui.status === "failed" || ui.status === "disconnected";
  return (
    <div
      className="app"
      onPaste={paste}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node))
          setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (native) return;
        const files = Array.from(event.dataTransfer.files);
        run(async () => {
          for (const file of files) await addBlob(file, file.name);
        });
      }}
    >
      <header className="app-header">
        <div className="brand">
          badshop<span>✱</span>
        </div>
        <div className="session-menu" ref={sessionMenu}>
          <button
            className="session-name"
            aria-expanded={menu}
            aria-controls="session-actions"
            onClick={() => setMenu(!menu)}
          >
            <span className="session-label">{session?.name ?? "Untitled"}</span>
            {session?.unsaved_changes && (
              <span
                className="unsaved-dot"
                aria-hidden="true"
                title="Unsaved changes"
              >
                ●
              </span>
            )}
            <ChevronDown size={14} />
          </button>
          {menu && (
            <div className="dropdown" id="session-actions">
              <button
                disabled={ui.status !== "ready" || session?.turn_running}
                onClick={() => {
                  setMenu(false);
                  setNewSessionOpen(true);
                }}
              >
                <Plus size={15} />
                New session
              </button>
              <button
                disabled={ui.status !== "ready" || session?.turn_running}
                onClick={() => {
                  setMenu(false);
                  run(documents.open);
                }}
              >
                <FolderOpen size={15} />
                Open session<kbd>Ctrl O</kbd>
              </button>
              <button
                disabled={ui.status !== "ready"}
                onClick={() => {
                  setMenu(false);
                  save();
                }}
              >
                <Save size={15} />
                Save session<kbd>Ctrl S</kbd>
              </button>
              <button
                disabled={ui.status !== "ready"}
                onClick={() => {
                  setMenu(false);
                  save(true);
                }}
              >
                <Save size={15} />
                Save as…
              </button>
              <button
                onClick={() => {
                  setMenu(false);
                  run(async () => {
                    const path = await projectPath(true, true);
                    if (path) await action("session.export_recipe", { path });
                  });
                }}
              >
                <FileJson size={15} />
                Export recipe
              </button>
              <hr />
              <button
                onClick={() => {
                  setMenu(false);
                  importImages();
                }}
              >
                <Plus size={15} />
                Import images
              </button>
              {native && (
                <button
                  onClick={() =>
                    run(async () => {
                      await addBlob(await clipboardImage());
                    })
                  }
                >
                  <ClipboardPaste size={15} />
                  Paste clipboard image
                </button>
              )}
            </div>
          )}
        </div>
        <div className="header-center">
          <label className="provider-select">
            <span className="provider-symbol">✱</span>
            <select
              aria-label="Active provider"
              value={session?.provider_profile_id ?? ""}
              disabled={ui.status !== "ready" || session?.turn_running}
              onChange={(event) =>
                event.target.value === "add"
                  ? ui.set({ settingsOpen: true })
                  : run(() =>
                      action("providers.select", {
                        profile_id: event.target.value,
                      }),
                    )
              }
            >
              <option value="" disabled>
                {profiles?.length
                  ? "Select provider"
                  : "Choose your art director"}
              </option>
              {profiles?.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.label} / {profile.model || profile.cli}
                </option>
              ))}
              <option value="add">+ Add provider…</option>
            </select>
          </label>
          <span className="header-divider" />
          <label className="approval-select">
            <span className="approval-dot" />
            <select
              aria-label="Approval mode"
              disabled={ui.status !== "ready"}
              value={session?.approval_mode ?? "ask_changes"}
              onChange={(event) =>
                run(() =>
                  action("session.set_approval_mode", {
                    mode: event.target.value as ApprovalMode,
                  }),
                )
              }
            >
              <option value="auto">Auto</option>
              <option value="ask_changes">Ask for changes</option>
              <option value="ask_all">Ask for everything</option>
            </select>
          </label>
        </div>
        <div className="header-actions">
          <button
            className="quiet"
            title="Save session"
            aria-label="Save session"
            disabled={ui.status !== "ready"}
            onClick={() => save()}
          >
            <Save size={17} />
          </button>
          <button
            className="quiet"
            title="Settings"
            aria-label="Settings"
            onClick={() => ui.set({ settingsOpen: true })}
          >
            <Settings2 size={18} />
          </button>
          <button
            className="export"
            onClick={exportImage}
            disabled={
              ui.status !== "ready" ||
              !Object.keys(session?.artifacts ?? {}).length
            }
          >
            <Download size={15} />
            Export
          </button>
        </div>
      </header>
      {!ui.settingsOpen &&
        !ui.paletteOpen &&
        !welcome &&
        !newSessionOpen &&
        !documents.pending && <ErrorNotice />}
      {sessionError && !ui.error && (
        <div className="error-banner" role="alert">
          {sessionError.message}
        </div>
      )}
      {session?.restorable && !restoredDismissed && (
        <div className="restore-banner">
          <span>An autosaved session is available from your last run.</span>
          <button
            disabled={ui.status !== "ready" || session?.turn_running}
            onClick={() => run(() => documents.request({ kind: "restore" }))}
          >
            Restore session
          </button>
          <button onClick={() => setRestoreDismissed(true)}>Dismiss</button>
        </div>
      )}
      {disconnected && (
        <main className="core-error">
          <AlertTriangle size={40} />
          <h1>
            {ui.status === "failed"
              ? "The core could not start."
              : "The core connection was lost."}
          </h1>
          <p>
            Your session is autosaved after every step. Restart the core to
            continue.
          </p>
          {ui.logPath && <code>{ui.logPath}</code>}
          <div>
            <button className="primary" onClick={() => run(restart)}>
              <RefreshCw size={16} />
              Restart core
            </button>
            <button
              onClick={() =>
                run(async () => {
                  await copyText(await diagnostics());
                  ui.set({ notice: "Diagnostics copied" });
                })
              }
            >
              <Copy size={16} />
              Copy diagnostics
            </button>
          </div>
        </main>
      )}
      <main
        className="workbench"
        hidden={disconnected}
        inert={ui.status !== "ready"}
        ref={workbench}
        style={{
          display: disconnected ? "none" : undefined,
          gridTemplateColumns: `${widths.left}px 6px minmax(250px,1fr) 6px ${widths.right}px`,
        }}
      >
        <Chat
          key={`chat-${ui.documentGeneration}`}
          attachments={attachments}
          onAttachments={setAttachments}
          onImport={importImages}
          onPaste={paste}
        />
        <Resizer
          side="left"
          value={widths.left}
          maximum={contentWidth - widths.right - 262}
          onResize={(delta) => resize("left", delta)}
          onReset={reset}
        />
        <Viewer
          key={`viewer-${ui.documentGeneration}`}
          onImport={importImages}
        />
        <Resizer
          side="right"
          value={widths.right}
          maximum={contentWidth - widths.left - 262}
          onResize={(delta) => resize("right", delta)}
          onReset={reset}
        />
        <Timeline key={`timeline-${ui.documentGeneration}`} />
      </main>
      <footer className="app-footer">
        <span className="footer-brand">Bad is the deliverable.</span>
        <span>
          {session?.steps.length ?? 0} steps /{" "}
          {Object.keys(session?.artifacts ?? {}).length ?? 0} images
        </span>
        <span>
          {session?.turn_running
            ? "Agent working"
            : ui.status === "ready"
              ? "All systems questionable"
              : "Starting core…"}
        </span>
      </footer>
      {newSessionOpen && !documents.pending && (
        <NewSession
          onClose={() => setNewSessionOpen(false)}
          onCreate={async (name) => {
            setNewSessionOpen(false);
            await documents.request({ kind: "new", name });
          }}
        />
      )}
      {ui.settingsOpen && !documents.pending && <Settings />}
      {ui.paletteOpen && !documents.pending && <ToolPalette />}
      <SaveChangesDialog actions={documents} />
      {welcome &&
        ui.status === "ready" &&
        !ui.settingsOpen &&
        !documents.pending && <Welcome onClose={closeWelcome} />}
      {dragging && (
        <div className="drop-overlay">
          <Plus size={40} />
          <h2>Drop it like it’s 2005.</h2>
          <p>Add images to this session</p>
        </div>
      )}
      {ui.notice && (
        <div className="toast" role="status">
          {ui.notice}
          <button
            aria-label="Dismiss notification"
            onClick={() => ui.set({ notice: null })}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <input
        className="sr-only"
        ref={fileInput}
        aria-label="Import image files"
        type="file"
        accept="image/*"
        multiple
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          run(async () => {
            for (const file of files) await addBlob(file, file.name);
          });
          event.target.value = "";
        }}
      />
    </div>
  );
}

function NewSession({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("Untitled");
  const [busy, setBusy] = useState(false);
  return (
    <div className="modal-backdrop">
      <section
        className="modal new-session-modal"
        role="dialog"
        aria-modal="true"
        aria-label="New session"
      >
        <div className="modal-heading">
          <div>
            <h2>New session</h2>
            <p>A fresh start for a terrible idea.</p>
          </div>
          <button aria-label="Close new session" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <ErrorNotice />
        <form
          onSubmit={(event) => {
            event.preventDefault();
            run(async () => {
              setBusy(true);
              try {
                await onCreate(name.trim() || "Untitled");
                onClose();
              } finally {
                setBusy(false);
              }
            });
          }}
        >
          <label>
            Session name
            <input
              autoFocus
              value={name}
              maxLength={200}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <div>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Creating…" : "Create session"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
