import { Button } from "./Button";
import { ThemeIcon } from "./ThemeIcon";
import { useOperation } from "../useOperation";
import { InputField, SelectField, TextAreaField } from "./Fields";
import { useEffect, useState } from "react";
import { action, run, useCoreQuery, useSession } from "../data";
import { useSelectedArtifact, useUI } from "../store";
import { openLink } from "../native";
import { sourceCard } from "../sourceCard";
import { ArtifactThumb } from "./Viewer";
import { LayoutsPacks } from "./LayoutsPacks";
import { ImagePairs } from "./ImagePairs";
import { RecentChoices } from "./RecentChoices";
import { LocalMedia } from "./LocalMedia";
import { IdeaMixer } from "./IdeaMixer";
import { SpriteSheet } from "./SpriteSheet";
import { RetroStudio } from "./RetroStudio";
import { LibraryImage } from "./LibraryImage";
import { directionLabel } from "../directions";
import type { LibraryEntry, Params } from "../types";

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
export function Studio({
  onClose,
  onAttach,
  onDraft,
}: {
  onClose: () => void;
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
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
  const [sheet, setSheet] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [link, setLink] = useState("");
  const [filter, setFilter] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [branchName, setBranchName] = useState("");
  const [fromStep, setFromStep] = useState("");
  const [editing, setEditing] = useState<LibraryEntry | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const { data: session } = useSession();
  const { data: library = [] } = useCoreQuery("library.list");
  const { data: branches } = useCoreQuery("branches.list");
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
    setSheet(null);
    setNotes("");
  }, [session?.id]);
  const disabled = busy || !ready || !!session?.turn_running;

  async function acquire(params: Params) {
    const step = await action("tools.run", { tool: "acquire", params });
    if (step.status !== "done" || !step.outputs[0])
      throw new Error(
        [step.error?.message ?? "The image could not be imported.", step.error?.hint]
          .filter(Boolean)
          .join(" "),
      );
    onAttach(step.outputs[0]);
    useUI.getState().set({
      selectedArtifact: step.outputs[0],
      notice: "Image added to your session and attached to chat",
    });
  }
  async function search(variation = "balanced", candidate?: Candidate) {
    const step = await action("tools.run", {
      tool: "discover",
      params: {
        query: query || candidate?.title,
        source: sources.some((item) => item.id === source && item.configured) ? source : "all",
        purpose,
        material,
        n: 8,
        ...(candidate ? { reference_url: candidate.thumbnail || candidate.url } : {}),
        ...(pose.trim() ? { pose: pose.trim() } : {}),
        ...(expression.trim() ? { expression: expression.trim() } : {}),
        same_subject: sameSubject,
        variation,
        ...(variation === "different" ? { exclude_urls: candidates.map((c) => c.url) } : {}),
      },
    });
    if (step.status !== "done")
      throw new Error([step.error?.message ?? "Search failed.", step.error?.hint].filter(Boolean).join(" "));
    setCandidates((step.data?.candidates ?? []) as Candidate[]);
    setSheet(step.outputs[0] ?? null);
    setNotes(step.result_text);
  }
  const tagList = () =>
    tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  return (
    <div className="modal-backdrop">
      <section className="modal studio" role="dialog" aria-modal="true" aria-labelledby="studio-title">
        <div className="modal-heading">
          <div>
            <h2 id="studio-title">Images & directions</h2>
            <p>Find material, keep your favorites, and try another take.</p>
          </div>
          <button aria-label="Close images and directions" onClick={onClose}>
            <ThemeIcon name="close" size={18} />
          </button>
        </div>
        <nav className="studio-tabs" aria-label="Images and directions">
          {[
            ["discover", "Find images"],
            ["retro", "Retro workbench"],
            ["ideas", "Idea mixer"],
            ["library", "Junk drawer"],
            ["branches", "Branches"],
            ["layouts", "Layouts & packs"],
            ["local", "Clips, pages & folders"],
            ["sheets", "Sprite sheets"],
            ["pairs", "Image pairs"],
            ["recent", "Recent choices"],
          ].map(([id, label]) => (
            <Button
              key={id}
              aria-pressed={tab === id}
              onClick={() => {
                showTab(id);
              }}
              label={label}
            />
          ))}
        </nav>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {session?.turn_running && <p>Stop the agent before changing images or branches.</p>}
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
                  {sources.map((item) => (
                    <tr key={item.id}>
                      <td>{item.name}</td>
                      <td>{item.configured ? "Configured" : "Needs configuration"}</td>
                      <td>{item.health?.status === "responded" ? `Responded · ${item.health.results} results (${item.health.step_id})`
                        : item.health?.status === "failed" ? `Failed (${item.health.step_id})` : "Not checked"}</td>
                      <td>{item.env_var ? <code>{item.env_var}</code> : "No key needed"}</td>
                    </tr>
                  ))}
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
              <Button
                className="primary"
                disabled={disabled || !query.trim()}
                label={busy ? "Working…" : "Find candidates"}
              />
            </form>
            {sheet && (
              <div className="studio-sheet">
                <ArtifactThumb
                  id={sheet}
                  label="Candidate contact sheet"
                  onClick={() => useUI.getState().set({ selectedArtifact: sheet })}
                />
              </div>
            )}
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
                          label="Use image"
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
                            const result = await action("library.import", {
                              id: entry.id,
                            });
                            onAttach(result.working.id);
                            useUI.getState().set({
                              selectedArtifact: result.working.id,
                              notice: `${entry.name} attached to chat`,
                            });
                          })
                        }
                        label="Use image"
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
        {tab === "branches" && (
          <>
            <p>
              Each branch keeps its own images, chat, and editable steps. Switching preserves your current
              work; save the project to keep every branch together.
            </p>
            <form
              className="studio-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  await action("branches.create", {
                    name: branchName,
                    ...(fromStep ? { from_step: fromStep } : {}),
                    expected_revision: session?.document_revision,
                  });
                  setBranchName("");
                  setFromStep("");
                });
              }}
            >
              <InputField
                label="New branch name"
                placeholder="Giant dog version"
                required
                bind={[branchName, setBranchName]}
              />
              <SelectField label="Start from" bind={[fromStep, setFromStep]}>
                <option value="">Current state</option>
                {session?.steps
                  .filter((s) => s.status === "done")
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      Step {s.index}: {s.tool}
                    </option>
                  ))}
              </SelectField>
              <Button disabled={disabled || !branchName.trim()} label="Create & switch" />
            </form>
            <div className="studio-grid">
              {branches?.branches.map((branch) => (
                <article className="studio-card" key={branch.id}>
                  {branch.preview_id && session?.artifacts[branch.preview_id] && (
                    <ArtifactThumb id={branch.preview_id} label={directionLabel(branch.name)} />
                  )}
                  <strong>
                    {directionLabel(branch.name)}
                    {branch.id === branches.active_id ? " (current)" : ""}
                  </strong>
                  <small>{branch.step_count} steps</small>
                  <Button
                    disabled={disabled || branch.id === branches.active_id}
                    onClick={() =>
                      void perform(async () => {
                        await action("branches.switch", {
                          id: branch.id,
                          expected_revision: session?.document_revision,
                        });
                      })
                    }
                    label="Switch to this take"
                  />
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
            onInspect={(id) => {
              useUI.getState().set({ selectedArtifact: id, selectedStep: null, viewerZoom: 1 });
              onClose();
            }}
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
              setSheet(null);
              setNotes("");
              showTab("discover");
            }}
          />
        </div>}
        {visited.includes("sheets") && <div hidden={tab !== "sheets"}>
          <SpriteSheet key={generation} onAttach={onAttach} />
        </div>}
        {visited.includes("local") && <div hidden={tab !== "local"}><LocalMedia key={generation} onAttach={onAttach} /></div>}
        {visited.includes("pairs") && <div hidden={tab !== "pairs"}>
          <ImagePairs key={generation} onAttach={onAttach} />
        </div>}
        {visited.includes("recent") && <div hidden={tab !== "recent"}><RecentChoices key={generation} /></div>}
      </section>
    </div>
  );
}
