import { useEffect, useState } from "react";
import { action, useCoreQuery } from "../data";
import { packPath } from "../native";
import { useOperation } from "../useOperation";
import { useUI } from "../store";
import { LibraryImage } from "./LibraryImage";
import type { LibraryEntry } from "../types";

const value = (entry: LibraryEntry, prefix: string) => entry.tags.find(tag => tag.startsWith(prefix))?.slice(prefix.length) ?? "";

export function Cast({ image, disabled, onUse }: { image: string; disabled: boolean; onUse: (id: string) => void }) {
  const { data: entries = [] } = useCoreQuery("library.list");
  const { busy, error, perform } = useOperation();
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [collection, setCollection] = useState("");
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<LibraryEntry | null>(null);
  const [removing, setRemoving] = useState("");
  const cast = entries.filter(e => e.tags.includes("cast"));
  const collections = [...new Set(cast.map(e => value(e, "collection:")).filter(Boolean))];
  const activeFilter = collections.includes(filter) ? filter : "";
  useEffect(() => {
    if (filter && !entries.some(e => e.tags.includes("cast") && value(e, "collection:") === filter)) setFilter("");
  }, [entries, filter]);
  const shown = cast.filter(e => !activeFilter || value(e, "collection:") === activeFilter);
  const locked = disabled || busy;
  function reset() { setEditing(null); setName(""); setExpression(""); setCollection(""); }
  return <section aria-label="Your cast" className="quick-form">
    <h3>Your recurring characters</h3>
    <p>Keep a face, pet or prop for the next joke. Each expression is a picture in your Junk drawer.</p>
    <form onSubmit={e => { e.preventDefault(); void perform(async () => {
      const tags = [...(editing?.tags ?? []).filter(t => t !== "cast" && !t.startsWith("expression:") && !t.startsWith("collection:")),
        "cast", ...(expression.trim() ? [`expression:${expression.trim()}`] : []), ...(collection.trim() ? [`collection:${collection.trim()}`] : [])];
      if (editing) await action("library.update", { id: editing.id, name: name.trim(), tags });
      else await action("library.save", { artifact_id: image, name: name.trim(), tags });
      reset();
    }); }}>
      <label>Character name<input value={name} maxLength={100} required disabled={locked} onChange={e => setName(e.target.value)} /></label>
      <label>Expression or role<input value={expression} maxLength={60} disabled={locked} onChange={e => setExpression(e.target.value)} placeholder="Triumphant, disappointed, suspicious…" /></label>
      <label>Cast collection<input value={collection} maxLength={60} disabled={locked} onChange={e => setCollection(e.target.value)} placeholder="Our party, the office, my pets…" /></label>
      <button disabled={locked || !name.trim() || (!image && !editing)}>{editing ? "Update character" : "Keep this picture in my cast"}</button>
      {editing && <button type="button" disabled={locked} onClick={reset}>Cancel character edit</button>}
    </form>
    <label>Show cast collection<select value={activeFilter} onChange={e => setFilter(e.target.value)}>
      <option value="">All my characters</option>
      {collections.map(group => <option key={group}>{group}</option>)}
    </select></label>
    <div className="quick-cards">{shown.map(entry => <article key={entry.id}>
      <LibraryImage entry={entry} /><strong>{entry.name}</strong><small>{value(entry, "expression:")}</small>
      <button disabled={locked} onClick={() => void perform(async () => {
        const generation = useUI.getState().documentGeneration;
        const result = await action("library.import", { id: entry.id });
        if (generation === useUI.getState().documentGeneration) onUse(result.working.id);
      })}>Use {entry.name}</button>
      <button disabled={locked} onClick={() => { setEditing(entry); setName(entry.name); setExpression(value(entry, "expression:")); setCollection(value(entry, "collection:")); }}>Edit character</button>
      <button disabled={locked} onClick={() => setRemoving(entry.id)}>Remove character</button>
      {removing === entry.id && <><p>Remove this saved character? Existing projects keep their pictures.</p>
        <button disabled={locked} onClick={() => void perform(async () => { await action("library.remove", { id: entry.id }); setRemoving(""); if (editing?.id === entry.id) reset(); })}>Confirm remove character</button>
        <button disabled={locked} onClick={() => setRemoving("")}>Keep character</button></>}
    </article>)}</div>
    <button disabled={locked || !shown.length || shown.length > 100} onClick={() => void perform(async () => {
      const path = await packPath(true);
      if (path) { await action("packs.export", { ids: shown.map(e => e.id), path, name: activeFilter || "My cast" }); useUI.getState().set({ notice: `Cast pack saved to ${path}` }); }
    })}>Export this cast collection</button>
    <button disabled={locked} onClick={() => void perform(async () => { const path = await packPath(false); if (path) await action("packs.import", { path }); })}>Import a cast pack</button>
    <p>Cast packs contain the selected pictures, available originals and source credits. Review those pictures before sharing.</p>
    {error && <p role="alert">{error}</p>}
  </section>;
}
