import { useLibraryPage } from '../libraryPage';
import { Button } from "./Button";
import { ThemeIcon } from "./ThemeIcon";
import { useOperation } from "../useOperation";
import { InputField, SelectField, TextAreaField } from "./Fields";
import { useEffect, useRef, useState } from "react";
import { action, queries, run, useCoreQuery, useSession } from "../data";
import { showError, useSelectedArtifact, useUI } from "../store";
import { openLink, native, pickImages } from "../native";
import { sourceCard } from "../sourceCard";
import { LayoutsPacks } from "./LayoutsPacks";
import { ImagePairs } from "./ImagePairs";
import { RecentChoices } from "./RecentChoices";
import { LocalMedia } from "./LocalMedia";
import { IdeaMixer } from "./IdeaMixer";
import { SpriteSheet } from "./SpriteSheet";
import { RetroStudio } from "./RetroStudio";
import { LibraryImage } from "./LibraryImage";
import type { LibraryEntry, Session } from "../types";
import type { AcquireParams, DiscoverParams, ResponseSourceHealth } from "../wire.generated";

type Candidate = {
  id: string;
  title: string;
  url: string;
  thumbnail?: string;
  preview?: string;
  thumbnail_data_url?: string;
  page?: string;
  source: {
    kind: string;
    page?: string;
    title?: string;
    license?: string;
    creator?: string;
  };
  reasons?: string[];
};
export type MaterialReceipt = { operation_id?: string; base_revision?: number; result_revision?: number };
export type MaterialTarget = {
  label: string;
  revision: number;
  isCurrent: (revision: number) => boolean;
  assign: (id: string, receipt?: MaterialReceipt) => void;
};

export function Studio({
  onClose,
  onAttach,
  onDraft,
  target,
}: {
  onClose: () => void;
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
  target?: MaterialTarget | null;
}) {
  const { busy, error, setError, perform } = useOperation();
  const [tab, setTab] = useState("discover");
  const generation = useUI((s) => s.documentGeneration);
  const [visited, setVisited] = useState<string[]>([]);
  useEffect(() => { setVisited([tab]); }, [generation]);
  function showTab(value: string) {
    setTab(value);
    setVisited((previous) => previous.includes(value) ? previous : [...previous, value]);
    setError("");
  }

  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [purpose, setPurpose] = useState("subject");
  const [material, setMaterial] = useState("photo");
  const [pose, setPose] = useState("");
  const [expression, setExpression] = useState("");
  const [sameSubject, setSameSubject] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [notes, setNotes] = useState("");
  const [searchHealth, setSearchHealth] = useState<Record<string, ResponseSourceHealth>>({});
  const [link, setLink] = useState("");
  const [filter, setFilter] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [editing, setEditing] = useState<LibraryEntry | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const { data: session } = useSession();
  const { entries: library, controls: libraryPages } = useLibraryPage(filter);
  const { data: sources = [], error: sourceError } = useCoreQuery("sources.status");
  useEffect(() => {
    if (sources.length && source !== "all" && !sources.some((item) => item.id === source && item.configured))
      setSource("all");
  }, [sources, source]);
  const selected = useSelectedArtifact(session?.steps);
  const selectedStep = useUI((s) => s.selectedStep);
  const ready = useUI((s) => s.status === "ready");
  const image =
    selected ??
    session?.steps.find((s) => s.id === selectedStep)?.outputs[0] ??
    session?.steps
      .slice()
      .reverse()
      .find((s) => s.outputs.length)?.outputs[0] ??
    Object.keys(session?.artifacts ?? {})[0];
  useEffect(() => {
    setCandidates([]);
    setNotes("");
    setSearchHealth({});
  }, [generation]);
  const disabled = busy || !ready || !!session?.turn_running;

  const dialog = useRef<HTMLDialogElement>(null);
  const open = useRef(true);
  useEffect(() => {
    dialog.current?.showModal();
    open.current = true;
    return () => { open.current = false; };
  }, []);

  function beginImport() {
    const revision = queries.getQueryData<Session>(["session.get"])?.document_revision;
    if (revision === undefined || (target && !target.isCurrent(revision)))
      throw new Error("The edit target changed. Close Materials and reopen the current selection.");
    return revision;
  }

  function receive(id: string, receipt: MaterialReceipt, operationId: string) {
    if (!open.current) return;
    if (target) {
      if (receipt.operation_id !== operationId) throw new Error("The import result could not be matched to this edit.");
      target.assign(id, receipt);
      onClose();
      return;
    }
    onAttach(id);
    useUI.getState().set({ notice: "Picture added to Materials." });
  }

  async function acquire(params: AcquireParams) {
    const expected_revision = beginImport();
    const operationId = crypto.randomUUID().replaceAll("-", "");
    try {
      const result = await action("materials.acquire", { params, expected_revision }, { operationId });
      receive(result.working.id, result, operationId);
    } catch (error) {
      if (error instanceof Error && "operationId" in error) showError(error);
      throw error;
    }
  }

  async function search(variation: DiscoverParams["variation"] = "balanced", candidate?: Candidate) {
    const result = await action("materials.discover", {
      params: {
        query: query || candidate?.title || "",
        source: (sources.some(item => item.id === source && item.configured) ? source : "all") as DiscoverParams["source"],
        purpose: purpose as DiscoverParams["purpose"],
        material: material as DiscoverParams["material"],
        n: 8,
        ...(candidate ? { reference_url: candidate.thumbnail || candidate.url } : {}),
        ...(pose.trim() ? { pose: pose.trim() } : {}),
        ...(expression.trim() ? { expression: expression.trim() } : {}),
        same_subject: sameSubject,
        variation,
        ...(variation === "different" ? { exclude_urls: candidates.map(c => c.url) } : {}),
      },
    });
    if (useUI.getState().documentGeneration !== generation) return;
    setCandidates(result.candidates as Candidate[]);
    setSearchHealth(result.source_health);
    setNotes((result.warnings ?? []).join("\n"));
  }
  const tagList = () =>
    tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  return (
    <dialog className="modal studio materials-dialog" ref={dialog} aria-labelledby="studio-title"
      onCancel={event => { event.preventDefault(); onClose(); }}>
        <div className="modal-heading">
          <div>
            <h2 id="studio-title">{target?.label ?? "Materials"}</h2>
          </div>
          <button aria-label="Close materials" onClick={onClose}>
            <ThemeIcon name="close" size={18} />
          </button>
        </div>
        <nav className="studio-tabs" aria-label="Material destinations">
          {([
            ["Find material", [["discover", "Find images"], ["local", "Clips, pages & folders"]]],
            ["My library", [["library", "Junk drawer"], ["recent", "Recent choices"]]],
            ["Formats", [["layouts", "Layouts & packs"], ["retro", "Retro workbench"], ["ideas", "Idea mixer"],
              ["sheets", "Sprite sheets"], ["pairs", "Image pairs"]]],
          ] as const).map(([label, tabs]) => (
            <div key={label} className="studio-tab-group" role="group" aria-label={label}>
              <span>{label}</span>
              <div>
                {tabs.filter(([id]) => !target || ["discover", "local", "library"].includes(id)).map(([id, title]) => (
                  <Button key={id} aria-pressed={tab === id} onClick={() => showTab(id)} label={title} />
                ))}
              </div>
            </div>
          ))}
        </nav>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {session?.turn_running && <p>Stop the agent before changing images.</p>}
        {tab === "discover" && (
          <>
            <p className="muted">
              {[
                ["pexels", "Photos provided by Pexels", "https://www.pexels.com/"],
                ["pixabay", "Images from Pixabay", "https://pixabay.com/"],
              ]
                .filter(([id]) => candidates.some((c) => c.source.kind === id))
                .map(([id, label, url]) => (
                  <Button key={id} onClick={() => run(() => openLink(url))} label={label} />
                ))}
            </p>
            <details className="collection-status">
              <summary>Collection availability</summary>
              <p>
                Configuration and the last search in this project are separate. A previous response does not
                guarantee current availability or useful pictures. No background test requests are sent.
              </p>
              {sourceError && (
                <p role="alert">
                  Could not read collection configuration. Reconnect to the core and try again.
                </p>
              )}
              <table>
                <thead>
                  <tr>
                    <th>Collection</th>
                    <th>Status</th>
                    <th>Last search in project</th>
                    <th>Setup</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map(item => {
                    const health = searchHealth[item.id] ?? item.health;
                    const measuredAt = health?.step_id ? ` (Step ${health.step_id})` : "";
                    return <tr key={item.id}>
                      <td>{item.name}</td>
                      <td>{item.configured ? "Configured" : "Needs configuration"}</td>
                      <td>{health?.status === "responded" ? `Responded · ${health.results} results${measuredAt}`
                        : health?.status === "failed" ? `Failed${measuredAt}` : "Not checked"}</td>
                      <td>{item.env_var ? <code>{item.env_var}</code> : "No key needed"}</td>
                    </tr>;
                  })}
                </tbody>
              </table>
              <p>
                Set the named environment variable before starting the app. Credential values are never shown
                here.
              </p>
            </details>
            <form
              className="studio-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(() => search());
              }}
            >
              <InputField
                label="Subject or scene"
                labelClassName="wide"
                placeholder="A furious dog at an office desk"
                required
                bind={[query, setQuery]}
              />
              <SelectField label="Collection" bind={[source, setSource]}>
                <option value="all">All public collections</option>
                {sources.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.configured}>
                    {item.name}
                    {!item.configured ? " (needs configuration)" : ""}
                  </option>
                ))}
              </SelectField>
              <Button
                className="primary"
                disabled={disabled || !query.trim()}
                label={busy ? "Working…" : "Find candidates"}
              />
              <details className="studio-search-options wide">
                <summary>Search filters</summary>
                <div className="studio-form">
                  <SelectField label="Kind of picture" bind={[material, setMaterial]}
                    options={[["photo", "Photos"], ["illustration", "Illustrations & icons"], ["object", "Museum objects"], ["any", "Any"]]} />
                  <p className="muted">Picture kind chooses collections when searching all sources. Check the previews; it does not classify every image.</p>
                  <SelectField
                    label="Needed for"
                    bind={[purpose, setPurpose]}
                    options={[
                      ["subject", "Main subject"],
                      ["head", "Head swap"],
                      ["background", "Background"],
                      ["object", "Object / prop"],
                    ].map(([id, title]) => [id, title] as const)}
                  />
                  <InputField
                    label="Pose / framing"
                    placeholder="Facing left, whole head visible"
                    bind={[pose, setPose]}
                  />
                  <InputField
                    label="Expression"
                    placeholder="Surprised, mouth open"
                    bind={[expression, setExpression]}
                  />
                  <InputField
                    label="More pictures of this exact subject"
                    inputFirst
                    labelClassName="check-label"
                    type="checkbox"
                    bind={[sameSubject, setSameSubject]}
                  />
                </div>
              </details>
            </form>
            {!!candidates.length && (
              <div className="studio-grid">
                {candidates.map((c, i) => {
                  const preview = [c.thumbnail_data_url, c.preview, c.thumbnail].find((v) =>
                    v?.startsWith("data:image/"),
                  );
                  return (
                    <article className="studio-card" key={c.id ?? c.url}>
                      {preview && <img className="studio-thumb" src={preview} alt={c.title} />}
                      <strong>
                        {i + 1}. {c.title}
                      </strong>
                      <small>
                        {c.source.kind} · {c.source.license || "Rights not supplied"}
                      </small>
                      {c.reasons?.length ? <small>{c.reasons.join(" · ")}</small> : null}
                      <div className="studio-actions">
                        <Button
                          disabled={disabled}
                          onClick={() =>
                            void perform(() =>
                              acquire({
                                url: c.url,
                                source_kind: c.source.kind,
                                page: c.source.page ?? c.page,
                                title: c.title,
                                license: c.source.license,
                                creator: c.source.creator,
                              }),
                            )
                          }
                          label={target?.label ?? "Add to Materials"}
                        />
                        <Button
                          disabled={disabled}
                          onClick={() => void perform(() => search("similar", c))}
                          label="More like this"
                        />
                        <Button
                          disabled={disabled}
                          onClick={() => void perform(() => search("different", c))}
                          label="Different view"
                        />
                        {(c.source.page ?? c.page)?.match(/^https?:\/\//) && (
                          <Button
                            onClick={() =>
                              void perform(async () => {
                                await openLink((c.source.page ?? c.page)!);
                              })
                            }
                            label="Source"
                          />
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
            {notes && (
              <details>
                <summary>Search details</summary>
                <pre className="studio-notes">{notes}</pre>
              </details>
            )}
            <form
              className="studio-import"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  await acquire(sourceCard(link) ?? { url: link.trim() });
                  setLink("");
                });
              }}
            >
              <TextAreaField
                label="Image URL or browser source card"
                placeholder="Paste an image address or use the browser helper’s Send image to badshop action"
                bind={[link, setLink]}
              />
              <Button disabled={disabled || !link.trim()} label="Import selected web image" />
            </form>
          </>
        )}
        {tab === "library" && (
          <>
            <form
              className="studio-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  if (editing)
                    await action("library.update", {
                      id: editing.id,
                      name,
                      tags: tagList(),
                    });
                  else if (image) {
                    const faceStep = session?.steps
                      .slice()
                      .reverse()
                      .find((s) => s.tool === "find" && s.params.image === image && s.data?.faces);
                    await action("library.save", {
                      artifact_id: image,
                      name,
                      tags: tagList(),
                      metadata: {
                        ...(Array.isArray(faceStep?.data?.faces) ? { faces: faceStep.data.faces } : {}),
                      },
                    });
                  }
                  setName("");
                  setTags("");
                  setEditing(null);
                });
              }}
            >
              <label>
                {editing ? "Rename saved asset" : "Save selected image as"}
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={image ? session?.artifacts[image]?.label : "Select an image first"}
                  required
                />
              </label>
              <InputField
                label="Tags, separated by commas"
                placeholder="screaming, facing right, giant head"
                bind={[tags, setTags]}
              />
              <Button
                disabled={disabled || (!image && !editing) || !name.trim()}
                label={editing ? "Update asset" : "Save to junk drawer"}
              />
              {editing && (
                <Button
                  type="button"
                  onClick={() => {
                    setEditing(null);
                    setName("");
                    setTags("");
                  }}
                  label="Cancel editing"
                />
              )}
            </form>
            <InputField
              label="Search saved images"
              labelClassName="studio-filter"
              placeholder="Name or tag"
              bind={[filter, setFilter]}
            />
            {libraryPages}
            {!library.length && (
              <p>Keep useful heads, props, backgrounds, and cutouts here for your next session.</p>
            )}
            <div className="studio-grid">
              {library
                .filter((e) => `${e.name} ${e.tags.join(" ")}`.toLowerCase().includes(filter.toLowerCase()))
                .map((entry) => (
                  <article className="studio-card" key={entry.id}>
                    <LibraryImage entry={entry} />
                    <strong>{entry.name}</strong>
                    <small>{entry.tags.join(" · ")}</small>
                    <small>{entry.artifact.source?.license || "Rights not supplied"}</small>
                    <div className="studio-actions">
                      <Button
                        disabled={disabled}
                        onClick={() =>
                          void perform(async () => {
                            const operationId = crypto.randomUUID().replaceAll("-", "");
                            const result = await action("library.import", {
                              id: entry.id, expected_revision: beginImport(),
                            }, { operationId });
                            receive(result.working.id, result, operationId);
                          })
                        }
                        label={target?.label ?? "Add to Materials"}
                      />
                      <Button
                        disabled={disabled}
                        onClick={() => {
                          setEditing(entry);
                          setName(entry.name);
                          setTags(entry.tags.join(", "));
                        }}
                        label="Edit tags / name"
                      />
                      <Button disabled={disabled} onClick={() => setConfirmRemove(entry.id)} label="Remove" />
                      {confirmRemove === entry.id && (
                        <>
                          <span>Remove from the drawer?</span>
                          <Button
                            disabled={disabled}
                            onClick={() =>
                              void perform(async () => {
                                await action("library.remove", {
                                  id: entry.id,
                                });
                                setConfirmRemove(null);
                              })
                            }
                            label="Yes, remove"
                          />
                          <Button onClick={() => setConfirmRemove(null)} label="Keep" />
                        </>
                      )}
                    </div>
                  </article>
                ))}
            </div>
          </>
        )}
        {visited.includes("layouts") && <div hidden={tab !== "layouts"}><LayoutsPacks key={generation} onAttach={onAttach} /></div>}
        {visited.includes("retro") && <div hidden={tab !== "retro"}>
          <RetroStudio
            key={generation}
            onAttach={onAttach}
            onDraft={onDraft}
          />
        </div>}
        {visited.includes("ideas") && <div hidden={tab !== "ideas"}>
          <IdeaMixer
            key={generation}
            onDraft={onDraft}
            onSearch={(value) => {
              setQuery(value);
              setPurpose("background");
              setSource("all");
              setPose("");
              setExpression("");
              setSameSubject(false);
              setCandidates([]);
              setNotes("");
              showTab("discover");
            }}
          />
        </div>}
        {visited.includes("sheets") && <div hidden={tab !== "sheets"}>
          <SpriteSheet key={generation} onAttach={onAttach} />
        </div>}
        {visited.includes("local") && <div hidden={tab !== "local"}>
          {target ? <div>
            <p>Choose one picture to replace the selected slot.</p>
            <button type="button" disabled={!native || disabled} onClick={() => void perform(async () => {
              const expected_revision = beginImport();
              const paths = await pickImages();
              if (!paths?.length || !open.current) return;
              if (paths.length !== 1) throw new Error("Choose one picture for this slot.");
              const operationId = crypto.randomUUID().replaceAll("-", "");
              try {
                const result = await action("artifacts.import", { path: paths[0], expected_revision }, { operationId });
                receive(result.working.id, result, operationId);
              } catch (error) {
                if (error instanceof Error && "operationId" in error) showError(error);
                throw error;
              }
            })}>Choose local picture</button>
            {!native && <p>Open the desktop app to use the file picker here, or choose a picture from My library.</p>}
          </div> : <LocalMedia key={generation} onAttach={onAttach} />}
        </div>}
        {visited.includes("pairs") && <div hidden={tab !== "pairs"}>
          <ImagePairs key={generation} onAttach={onAttach} />
        </div>}
        {visited.includes("recent") && <div hidden={tab !== "recent"}><RecentChoices key={generation} /></div>}
    </dialog>
  );
}
