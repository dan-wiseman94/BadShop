import { useState } from "react";
import { action, useCoreQuery, useSession } from "../data";
import { useOperation } from "../useOperation";

export function ProjectHome({ onClose, onOpen, onBrowse, onNew, onRestore }: {
  onClose: () => void; onOpen: (path: string) => Promise<void>; onBrowse: () => Promise<void>;
  onNew: () => void; onRestore: () => Promise<void>;
}) {
  const { data: projects, error: loadError } = useCoreQuery("projects.recent");
  const { data: session } = useSession();
  const [search, setSearch] = useState("");
  const { busy, error, perform } = useOperation();
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const filtered = projects?.filter(project => `${project.name} ${project.path}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="modal-backdrop">
    <section className="modal project-home" role="dialog" aria-modal="true" aria-label="Project home">
      <div className="modal-heading"><h2>Your projects</h2><button onClick={onClose} aria-label="Close project home">Close</button></div>
      <div className="manual-turn-controls">
        <button disabled={disabled} onClick={onNew}>New project</button>
        <button disabled={disabled} onClick={() => void perform(onBrowse)}>Open project file</button>
      </div>
      {session?.restorable && <section aria-label="Project recovery">
        <h3>Recover interrupted work</h3><p>An autosaved project is available from your previous run.</p>
        <button disabled={disabled} onClick={() => void perform(onRestore)}>Recover autosaved project</button>
      </section>}
      <label>Find a recent project<input value={search} onChange={event => setSearch(event.target.value)} /></label>
      {(error || loadError) && <p role="alert">{error || loadError?.message}</p>}
      {!projects && !loadError && <p role="status">Loading recent projects…</p>}
      {projects?.length === 0 && <p>Saved and opened projects appear here. Your editable work is stored in .badshop files.</p>}
      {!!projects?.length && !filtered?.length && <p>No matching projects.</p>}
      <div className="project-home-grid">{filtered?.map(project => <article key={project.path}>
        <button className="project-home-open" disabled={disabled || !project.available}
          onClick={() => void perform(() => onOpen(project.path))}>
          {project.thumbnail ? <img src={`data:image/png;base64,${project.thumbnail}`} alt="" /> : <span aria-hidden="true">▧</span>}
          <strong>{project.name}</strong>
        </button>
        <p className="muted">{project.path}</p>
        <small>{new Date(project.opened_at * 1000).toLocaleString()}</small>
        {!project.available && <p>File moved or unavailable. Use Open project file to locate it.</p>}
        <button disabled={busy} onClick={() => void perform(async () => { await action("projects.forget", { path: project.path }); })}
          aria-label={`Remove ${project.name} from recent projects`}>Remove from recents</button>
      </article>)}</div>
      <p className="muted">Removing an entry leaves its project file untouched.</p>
    </section>
  </div>;
}
