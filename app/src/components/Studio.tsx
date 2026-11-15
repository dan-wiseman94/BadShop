import { useLibraryPage } from '../libraryPage';
import { Button } from "./Button";
import { ThemeIcon } from "./ThemeIcon";
import { useOperation } from "../useOperation";
import { InputField, SelectField, TextAreaField } from "./Fields";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { action, imageUrl, queries, run, useArtifact, useCoreQuery, useSession } from "../data";
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
import { Cast } from "./Cast";
import { RecipeStudio } from "./RecipeStudio";
import "../materials.css";
import type { Artifact, LibraryEntry, Session } from "../types";
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
  actionLabel?: string;
  purpose?: DiscoverParams["purpose"];
  beforeStepIndex?: number;
  revision: number;
  isCurrent: (revision: number) => boolean;
  assign: (id: string, receipt?: MaterialReceipt) => void;
};

const materialDestinations = [
  ["Find material", [["project", "In this project"], ["discover", "Find images"], ["local", "Local files and clips"]]],
  ["My library", [["library", "Junk drawer"], ["characters", "Characters"], ["recent", "Recent choices"], ["recipes", "Recipes"]]],
  ["Formats", [["layouts", "Layouts & packs"], ["retro", "Retro workbench"], ["ideas", "Idea mixer"], ["pairs", "Image pairs"]]],
  ["More tools", [["sheets", "Sprite sheets"]]],
] as const;
export type MaterialDestination = (typeof materialDestinations)[number][1][number][0];
const selectionDestinations: MaterialDestination[] = ["project", "discover", "local", "library", "characters"];

type ImportResult = MaterialReceipt & { working: { id: string } };
type ImportIntent = { revision: number; browser: object; generation: number; target?: MaterialTarget | null };

function ProjectThumbnail({ artifact }: { artifact: Artifact }) {
  const { data } = useArtifact(artifact.id, true);
  return <img className="studio-thumb" src={imageUrl(data)} alt="" />;
}

function ProjectPictures({ session, target, disabled, onSelect }: {
  session: Session | undefined;
  target?: MaterialTarget | null;
  disabled: boolean;
  onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const artifacts = Object.values(session?.artifacts ?? {});
  const originals = new Set(artifacts.map(artifact => artifact.original_id));
  const producers = new Map(session?.steps.map(step => [step.id, step.index]));
  const pictures = artifacts.filter(artifact => !originals.has(artifact.id) &&
    artifact.label.toLowerCase().includes(filter.trim().toLowerCase())).reverse();
  const pageSize = 50;
  const currentPage = Math.min(page, Math.max(0, Math.ceil(pictures.length / pageSize) - 1));
  const shown = pictures.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  return <>
    <InputField label="Search project pictures" bind={[filter, value => { setPage(0); setFilter(value); }]} />
    {!shown.length && <p>{filter.trim() ? "No project pictures match." : "Add a picture to use it in this project."}</p>}
    {pictures.length > pageSize && <nav aria-label="Project picture pages">
      <Button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} label="Previous pictures" />
      <span> {currentPage + 1} of {Math.ceil(pictures.length / pageSize)} </span>
      <Button type="button" disabled={(currentPage + 1) * pageSize >= pictures.length}
        onClick={() => setPage(currentPage + 1)} label="Next pictures" />
    </nav>}
    <div className="studio-grid">
      {shown.map(artifact => {
        const madeLater = !!artifact.produced_by && target?.beforeStepIndex !== undefined &&
          (producers.get(artifact.produced_by) ?? Infinity) >= target.beforeStepIndex;
        return <article key={artifact.id} className="studio-card">
          <ProjectThumbnail artifact={artifact} />
          <strong>{artifact.label}</strong>
          <small>{artifact.source?.license || "Rights not supplied"}</small>
          {madeLater && <p>Made after this step. Choose an imported or earlier picture.</p>}
          <Button type="button" disabled={disabled || madeLater} onClick={() => onSelect(artifact.id)}
            label={target?.actionLabel ?? target?.label ?? "Show in canvas"} />
        </article>;
      })}
    </div>
  </>;
}

export function Studio({
  open = true,
  compact = true,
  destination,
  onClose,
  onAttach,
  onDraft,
  target,
}: {
  open?: boolean;
  compact?: boolean;
  destination?: MaterialDestination;
  onClose: () => void;
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
  target?: MaterialTarget | null;
}) {
  const { busy, error, setError, perform } = useOperation();
  const [tab, setTab] = useState<MaterialDestination>("discover");
  const generation = useUI((s) => s.documentGeneration);
  const [visited, setVisited] = useState<MaterialDestination[]>(["discover"]);
  const scroll = useRef<HTMLDivElement>(null);
  const scrollPositions = useRef(new Map<MaterialDestination, number>());
  function showTab(value: MaterialDestination) {
    if (value !== tab && scroll.current) scrollPositions.current.set(tab, scroll.current.scrollTop);
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
  const { entries: library, controls: libraryPages } = useLibraryPage(filter,
    target && tab === "characters" ? ["cast"] : []);
  const project = session?.context?.document_incarnation ?? session?.id;
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
  const previousProject = useRef(project);
  useLayoutEffect(() => {
    if (previousProject.current === project) return;
    previousProject.current = project;
    setTab("discover");
    setVisited(["discover"]);
    setQuery("");
    setSource("all");
    setPurpose("subject");
    setMaterial("photo");
    setPose("");
    setExpression("");
    setSameSubject(false);
    setCandidates([]);
    setNotes("");
    setSearchHealth({});
    setLink("");
    setFilter("");
    setName("");
    setTags("");
    setEditing(null);
    setConfirmRemove(null);
    scrollPositions.current.clear();
  }, [project]);
  const disabled = busy || !ready || session?.turn_running || session?.batch_running;

  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const browser = useRef<object | null>(null);
  const currentTarget = useRef(target);
  currentTarget.current = target;
  useLayoutEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (!open) {
      if (node.open) node.close();
      const previous = opener.current;
      opener.current = null;
      if (previous) requestAnimationFrame(() => {
        if (!dialog.current?.open && previous.isConnected) previous.focus({ preventScroll: true });
      });
      return;
    }
    if (!opener.current && document.activeElement instanceof HTMLElement)
      opener.current = document.activeElement;
    if (node.open && node.matches(":modal") === compact) return;
    if (node.open) node.close();
    if (compact) node.showModal();
    else node.show();
    heading.current?.focus({ preventScroll: true });
  }, [open, compact]);
  useLayoutEffect(() => {
    if (!open) return;
    browser.current = {};
    const next = destination && (!target || selectionDestinations.includes(destination))
      ? destination : target ? "project" : undefined;
    if (next) showTab(next);
    if (target?.purpose) setPurpose(target.purpose);
    setError("");
    return () => { browser.current = null; };
  }, [open, destination, target, project]);
  useLayoutEffect(() => {
    if (!open || !scroll.current) return;
    scroll.current.scrollTop = scrollPositions.current.get(tab) ?? 0;
  }, [open, tab, compact]);

  function closeBrowser() {
    if (scroll.current) scrollPositions.current.set(tab, scroll.current.scrollTop);
    browser.current = null;
    onClose();
  }

  function beginImport(): ImportIntent {
    const revision = queries.getQueryData<Session>(["session.get"])?.document_revision;
    if (!browser.current || revision === undefined || (target && !target.isCurrent(revision)))
      throw new Error("The edit target changed. Close Materials and reopen the current selection.");
    return { revision, browser: browser.current, target, generation };
  }

  function stillBrowsing(intent: ImportIntent) {
    return browser.current === intent.browser && currentTarget.current === intent.target &&
      useUI.getState().documentGeneration === intent.generation;
  }

  function pickProjectPicture(id: string) {
    void perform(async () => {
      beginImport();
      if (target) {
        target.assign(id);
        closeBrowser();
      } else {
        onAttach(id);
        if (compact) closeBrowser();
      }
    });
  }

  async function importMaterial(
    load: (revision: number, operationId: string) => Promise<ImportResult>,
    intent = beginImport(),
  ) {
    const operationId = crypto.randomUUID().replaceAll("-", "");
    try {
      const result = await load(intent.revision, operationId);
      if (!stillBrowsing(intent)) return;
      if (target) {
        if (result.operation_id !== operationId) throw new Error("The import result could not be matched to this edit.");
        target.assign(result.working.id, result);
        closeBrowser();
      } else {
        onAttach(result.working.id);
        useUI.getState().set({ notice: "Picture added to Materials." });
      }
    } catch (error) {
      if (!stillBrowsing(intent)) return;
      if (error instanceof Error && "operationId" in error) showError(error);
      throw error;
    }
  }

  function acquire(params: AcquireParams) {
    return importMaterial((expected_revision, operationId) =>
      action("materials.acquire", { params, expected_revision }, { operationId }));
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
    <dialog className="modal studio materials-dialog materials-pane" ref={dialog}
      data-docked={!compact} aria-modal={compact || undefined} aria-labelledby="studio-title"
      onCancel={event => { event.preventDefault(); closeBrowser(); }}
      onKeyDown={event => {
        if (!compact && event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          event.stopPropagation();
          closeBrowser();
        }
      }}>
        <div className="modal-heading">
          <div>
            <h2 id="studio-title" ref={heading} tabIndex={-1}>{target?.label ?? "Materials"}</h2>
          </div>
          <button type="button" aria-label="Close materials" onClick={closeBrowser}>
            <ThemeIcon name="close" size={18} />
          </button>
        </div>
        <div className="materials-scroll" ref={scroll} onScroll={event => {
          if (open) scrollPositions.current.set(tab, event.currentTarget.scrollTop);
        }}>
        <nav className="studio-tabs" aria-label="Material destinations">
          {materialDestinations.map(([label, tabs]) => {
            const available = tabs.filter(([id]) => !target || selectionDestinations.includes(id));
            return available.length ? (
              <div key={label} className="studio-tab-group" role="group" aria-label={label}>
                <span>{label}</span>
                <div>
                  {available.map(([id, title]) => <Button key={id} type="button"
                    aria-pressed={tab === id} onClick={() => showTab(id)} label={title} />)}
                </div>
              </div>
            ) : null;
          })}
        </nav>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {session?.turn_running && <p>Stop the agent before changing images.</p>}
        {visited.includes("project") && <div hidden={tab !== "project"}>
          <ProjectPictures key={project} session={session} target={target} disabled={!!disabled} onSelect={pickProjectPicture} />
        </div>}
        {visited.includes("discover") && (
          <div hidden={tab !== "discover"}>
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
                          label={target?.actionLabel ?? target?.label ?? "Add to Materials"}
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
          </div>
        )}
        {(visited.includes("library") || (target && visited.includes("characters"))) && (
          <div hidden={tab !== "library" && !(target && tab === "characters")}>
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
                        onClick={() => void perform(() => importMaterial((expected_revision, operationId) =>
                          action("library.import", { id: entry.id, expected_revision }, { operationId })))}
                        label={target?.actionLabel ?? target?.label ?? "Add to Materials"}
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
          </div>
        )}
        {!target && visited.includes("characters") && <div hidden={tab !== "characters"}>
          <Cast key={project} image={image ?? ""} disabled={!!disabled} onUse={onAttach} />
        </div>}
        {visited.includes("recipes") && <div hidden={tab !== "recipes"}><RecipeStudio key={project} /></div>}
        {visited.includes("layouts") && <div hidden={tab !== "layouts"}><LayoutsPacks key={project} onAttach={onAttach} /></div>}
        {visited.includes("retro") && <div hidden={tab !== "retro"}>
          <RetroStudio
            key={project}
            onAttach={onAttach}
            onDraft={onDraft}
          />
        </div>}
        {visited.includes("ideas") && <div hidden={tab !== "ideas"}>
          <IdeaMixer
            key={project}
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
          <SpriteSheet key={project} onAttach={onAttach} />
        </div>}
        {visited.includes("local") && <div hidden={tab !== "local"}>
          {target ? <div>
            <p>Choose one picture to replace the selected slot.</p>
            <button type="button" disabled={!native || disabled} onClick={() => void perform(async () => {
              const intent = beginImport();
              const paths = await pickImages();
              const path = paths?.[0];
              if (!path || !stillBrowsing(intent)) return;
              if (paths.length !== 1) throw new Error("Choose one picture for this slot.");
              await importMaterial((expected_revision, operationId) =>
                action("artifacts.import", { path, expected_revision }, { operationId }), intent);
            })}>Choose local picture</button>
            {!native && <p>Open the desktop app to use the file picker here, or choose a picture from My library.</p>}
          </div> : <LocalMedia key={project} onAttach={onAttach} />}
        </div>}
        {visited.includes("pairs") && <div hidden={tab !== "pairs"}>
          <ImagePairs key={project} onAttach={onAttach} />
        </div>}
        {visited.includes("recent") && <div hidden={tab !== "recent"}><RecentChoices key={project} /></div>}
        </div>
    </dialog>
  );
}
