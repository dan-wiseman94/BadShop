import { Button } from "./components/Button";
import { ThemeIcon } from "./components/ThemeIcon";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Plus,
  AlertTriangle,
  X,
  Copy,
  RefreshCw,
  FileJson,
  ClipboardPaste,
} from "lucide-react";
import { Chat } from "./components/Chat";
import { ON_DEVICE } from "./constants";
import { Viewer } from "./components/Viewer";
import { Timeline, ToolPalette } from "./components/Timeline";
import { Settings, Welcome } from "./components/Settings";
import { ErrorNotice } from "./components/ErrorNotice";
import { Studio } from "./components/Studio";
import { QuickStart } from "./components/QuickStart";
import { sourceCard } from "./sourceCard";
import { SaveChangesDialog, useSessionActions } from "./sessionActions";
import { usePaneLayout } from "./layout";
import { action, importBlob, run, startCore, useCoreQuery, useSession } from "./data";
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
} from "./native";
import { reportNativeReadiness } from "./nativeReadiness";
import type { ApprovalMode } from "./types";
import { readPreference, savePreference, useReducedMotion } from "./appearance";
import { useUpdates, UpdateProgress } from "./updates";
import "./themes.css";
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
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) event.preventDefault();
        if (event.key === "ArrowLeft") onResize(side === "left" ? -16 : 16);
        if (event.key === "ArrowRight") onResize(side === "left" ? 16 : -16);
        if (event.key === "Home") onResize((side === "left" ? 260 : 270) - value);
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
  const reducedMotion = useReducedMotion(ui.motion);
  useEffect(() => {
    document.documentElement.dataset.density = ui.density;
    document.documentElement.dataset.motion = reducedMotion ? "reduced" : "full";
    document.documentElement.style.fontSize = `${(13 * ui.textScale) / 100}px`;
  }, [ui.density, ui.textScale, reducedMotion]);
  const [attachments, setAttachments] = useState<string[]>([]);
  const { workbench, widths, resize, reset, contentWidth } = usePaneLayout();
  const documents = useSessionActions();
  const { data: settings } = useCoreQuery("settings.get");
  const updates = useUpdates(() => documents.request({ kind: "close" }), settings?.no_remote ?? true);
  const [welcome, setWelcome] = useState(!localStorage.getItem("badshop.welcome"));
  // Existing users keep their workbench; first-time users begin with quick ideas.
  const [workspace, setWorkspace] = useState(() => readPreference("workspace", localStorage.getItem("badshop.welcome") ? "advanced" : "quick"));
  const [history, setHistory] = useState(false);
  const chooseWorkspace = (value: string) => { setWorkspace(value); savePreference("workspace", value); };
  const [menu, setMenu] = useState(false);
  const [studioOpen, setStudioOpen] = useState(false);
  const [ideaDrafts, setIdeaDrafts] = useState<{ id: string; text: string; generation: number }[]>([]);
  const consumeIdeaDraft = useCallback((id: string) => {
    setIdeaDrafts((previous) => previous.filter((draft) => draft.id !== id));
  }, []);
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const [restoredDismissed, setRestoreDismissed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const previousSession = useRef<string | undefined>(undefined);
  const sessionMenu = useRef<HTMLDivElement>(null);
  useEffect(() => startCore(), []);
  useEffect(() => {
    if (!native) return;
    let current = true;
    void reportNativeReadiness(
      {
        ready: ui.status === "ready" && Boolean(session?.id) && Boolean(profiles) && !sessionError,
        sessionId: session?.id ?? "",
        revision: session?.document_revision ?? 0,
        unsaved: session?.unsaved_changes ?? false,
        welcome,
        closePending: Boolean(documents.pending),
      },
      () => current,
    ).catch((error) => console.error("Native readiness probe failed", error));
    return () => {
      current = false;
    };
  }, [
    ui.status,
    session?.id,
    session?.document_revision,
    session?.unsaved_changes,
    sessionError,
    !!profiles,
    welcome,
    documents.pending,
  ]);
  useEffect(() => {
    if (previousSession.current && previousSession.current !== session?.id) {
      setAttachments([]);
      useUI.getState().set({ selectedStep: null, selectedArtifact: null });
    }
    previousSession.current = session?.id;
  }, [session?.id]);
  useEffect(() => {
    setAttachments([]);
    setIdeaDrafts([]);
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
  const save = useCallback((as = false) => run(() => documents.save(as)), [documents.save]);
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
        setStudioOpen(false);
        if (useUI.getState().pick) {
          useUI.getState().set({ pick: null });
          return;
        }
        useUI.getState().set({ settingsOpen: false, paletteOpen: false, pick: null });
        setMenu(false);
      }
      if (document.querySelector('[role="dialog"], dialog[open]')) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (native && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v"
        && !target?.closest("input, textarea, select") && !target?.isContentEditable) {
        // WebKit does not dispatch an image paste event from a focused button/canvas.
        // Use the native clipboard there; editable controls keep their normal paste.
        event.preventDefault();
        run(async () => { await addBlob(await clipboardImage()); });
      }
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
  }, [save, documents.open, documents.pending, documents.cancel, addBlob]);
  useEffect(() => {
    if (!ui.notice) return;
    const timer = setTimeout(() => useUI.getState().set({ notice: null }), 6000);
    return () => clearTimeout(timer);
  }, [ui.notice]);
  const paste = (event: React.ClipboardEvent) => {
    const text = event.clipboardData.getData("text/plain");
    if (text.includes('"badshop_source"')) {
      event.preventDefault();
      event.stopPropagation();
      run(async () => {
        const params = sourceCard(text);
        if (!params) throw new Error("Invalid browser source card.");
        const step = await action("tools.run", { tool: "acquire", params });
        if (step.status !== "done" || !step.outputs[0])
          throw new Error(step.error?.message ?? "The image could not be imported.");
        setAttachments((previous) => [...new Set([...previous, step.outputs[0]])]);
        useUI.getState().set({ selectedArtifact: step.outputs[0] });
      });
      return;
    }
    const images = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
    if (images.length) {
      event.preventDefault();
      event.stopPropagation();
      run(async () => {
        for (const image of images) await addBlob(image, image.name);
      });
    }
  };
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
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || !dialog.contains(document.activeElement))
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
    studioOpen,
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
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);
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
              <span className="unsaved-dot" aria-hidden="true" title="Unsaved changes">
                ●
              </span>
            )}
            <ChevronDown size={14} />
          </button>
          {menu && (
            <div className="dropdown" id="session-actions">
              <Button
                disabled={ui.status !== "ready" || session?.turn_running}
                onClick={() => {
                  setMenu(false);
                  setNewSessionOpen(true);
                }}
                label="New session"
                icon={Plus}
                iconSize={15}
              />
              <button
                disabled={ui.status !== "ready" || session?.turn_running}
                onClick={() => {
                  setMenu(false);
                  run(documents.open);
                }}
              >
                <ThemeIcon name="open" size={16} />
                Open session<kbd>Ctrl O</kbd>
              </button>
              <button
                disabled={ui.status !== "ready"}
                onClick={() => {
                  setMenu(false);
                  save();
                }}
              >
                <ThemeIcon name="save" size={16} />
                Save session<kbd>Ctrl S</kbd>
              </button>
              <Button
                disabled={ui.status !== "ready"}
                onClick={() => {
                  setMenu(false);
                  save(true);
                }}
                label="Save as…"
                icon="save"
                iconSize={15}
              />
              <Button
                onClick={() => {
                  setMenu(false);
                  run(async () => {
                    const path = await projectPath(true, true);
                    if (path) await action("session.export_recipe", { path });
                  });
                }}
                label="Export recipe"
                icon={FileJson}
                iconSize={15}
              />
              <hr />
              <Button
                onClick={() => {
                  setMenu(false);
                  importImages();
                }}
                label="Import images"
                icon={Plus}
                iconSize={15}
              />
              {native && (
                <Button
                  onClick={() =>
                    run(async () => {
                      await addBlob(await clipboardImage());
                    })
                  }
                  label="Paste clipboard image"
                  icon={ClipboardPaste}
                  iconSize={15}
                />
              )}
            </div>
          )}
        </div>
        <div className="header-center">
          <div className="segmented workspace-switch" aria-label="Workspace">
            <button aria-pressed={workspace === "quick"} onClick={() => chooseWorkspace("quick")}>Quick ideas</button>
            <button aria-pressed={workspace === "advanced"} onClick={() => chooseWorkspace("advanced")}>Art director</button>
          </div>
          {workspace === "advanced" && <>
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
                {profiles?.length ? "Select provider" : "Choose your art director"}
              </option>
              {profiles?.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.id === ON_DEVICE ? profile.label : `${profile.label} / ${profile.model || profile.cli}`}
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
          </>}
        </div>
        <div className="header-actions">
          {workspace === "quick" && <button aria-pressed={history} onClick={() => setHistory(!history)}>History</button>}
          <button
            className="studio-launch"
            aria-label="Images & directions"
            disabled={ui.status !== "ready"}
            onClick={() => setStudioOpen(true)}
          >
            <ThemeIcon name="images" size={18} />
            <span className="studio-launch-full">Images & directions</span>
            <span className="studio-launch-short">Images</span>
          </button>
          <button
            className="quiet"
            title="Save session"
            aria-label="Save session"
            disabled={ui.status !== "ready"}
            onClick={() => save()}
          >
            <ThemeIcon name="save" size={18} />
          </button>
          <button
            className="quiet"
            title="Settings"
            aria-label="Settings"
            onClick={() => ui.set({ settingsOpen: true })}
          >
            <ThemeIcon name="settings" size={18} />
          </button>
          <Button
            className="export"
            type="submit"
            form="export-canvas-image"
            title="Export the image shown on the canvas"
            disabled={ui.status !== "ready" || !Object.keys(session?.artifacts ?? {}).length}
            label="Export"
            icon="export"
            iconSize={15}
          />
        </div>
      </header>
      {!ui.settingsOpen &&
        !studioOpen &&
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
          <Button
            disabled={ui.status !== "ready" || session?.turn_running}
            onClick={() => run(() => documents.request({ kind: "restore" }))}
            label="Restore session"
          />
          <Button onClick={() => setRestoreDismissed(true)} label="Dismiss" />
        </div>
      )}
      {disconnected && (
        <main className="core-error">
          <AlertTriangle size={40} />
          <h1>{ui.status === "failed" ? "The core could not start." : "The core connection was lost."}</h1>
          <p>Your session is autosaved after every step. Restart the core to continue.</p>
          {ui.logPath && <code>{ui.logPath}</code>}
          <div>
            <Button
              className="primary"
              onClick={() => run(restart)}
              label="Restart core"
              icon={RefreshCw}
              iconSize={16}
            />
            <Button
              onClick={() =>
                run(async () => {
                  await copyText(await diagnostics());
                  ui.set({ notice: "Diagnostics copied" });
                })
              }
              label="Copy diagnostics"
              icon={Copy}
              iconSize={16}
            />
          </div>
        </main>
      )}
      <main
        className={`workbench ${workspace === "quick" ? "quick-workbench" : "advanced-workbench"} ${history ? "show-history" : ""}`}
        hidden={disconnected}
        inert={ui.status !== "ready"}
        ref={workbench}
        style={{
          display: disconnected ? "none" : undefined,
          gridTemplateColumns: `${widths.left}px 6px minmax(250px,1fr)${workspace === "advanced" || history ? ` 6px ${widths.right}px` : ""}`,
        }}
      >
        <QuickStart key={`quick-${ui.documentGeneration}`} onImport={importImages} onAdvanced={() => chooseWorkspace("advanced")} />
        <Chat
          key={`chat-${ui.documentGeneration}`}
          attachments={attachments}
          onAttachments={setAttachments}
          onImport={importImages}
          onPaste={paste}
          draft={ideaDrafts.find((draft) => draft.generation === ui.documentGeneration)}
          onDraftConsumed={consumeIdeaDraft}
        />
        <Resizer
          side="left"
          value={widths.left}
          maximum={contentWidth - widths.right - 262}
          onResize={(delta) => resize("left", delta)}
          onReset={reset}
        />
        <Viewer key={`viewer-${ui.documentGeneration}`} onImport={importImages} />
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
          {session?.steps.length ?? 0} steps / {Object.keys(session?.artifacts ?? {}).length ?? 0} images
        </span>
        <span>
          {session?.turn_running
            ? "Agent working"
            : ui.status === "ready"
              ? "Connected"
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
      {ui.settingsOpen && !documents.pending && <Settings updates={updates} />}
      {updates.info?.version && !ui.settingsOpen && !documents.pending && updates.phase === "idle" && (
        <div className="update-notice" role="status">
          badshop {updates.info.version} is available.
          <button onClick={() => ui.set({ settingsOpen: true })}>Review update in Settings → Updates</button>
        </div>
      )}
      <UpdateProgress updates={updates} />
      {ui.paletteOpen && !documents.pending && <ToolPalette />}
      {studioOpen && !documents.pending && (
        <Studio
          onClose={() => setStudioOpen(false)}
          onAttach={(id) => setAttachments((previous) => [...new Set([...previous, id])])}
          onDraft={(text) => {
            chooseWorkspace("advanced");
            setIdeaDrafts((previous) => [
              ...previous,
              { id: crypto.randomUUID(), text, generation: ui.documentGeneration },
            ]);
            setStudioOpen(false);
            useUI.getState().set({ notice: "Brief added to chat. Review it before sending." });
          }}
        />
      )}
      <SaveChangesDialog actions={documents} />
      {welcome && ui.status === "ready" && !ui.settingsOpen && !documents.pending && (
        <Welcome onClose={closeWelcome} onManual={() => { chooseWorkspace("advanced"); closeWelcome(); }} />
      )}
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
          <button aria-label="Dismiss notification" onClick={() => ui.set({ notice: null })}>
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
      <section className="modal new-session-modal" role="dialog" aria-modal="true" aria-label="New session">
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
            <input autoFocus value={name} maxLength={200} onChange={(event) => setName(event.target.value)} />
          </label>
          <div>
            <Button type="button" onClick={onClose} label="Cancel" />
            <Button
              type="submit"
              className="primary"
              disabled={busy}
              label={busy ? "Creating…" : "Create session"}
            />
          </div>
        </form>
      </section>
    </div>
  );
}
