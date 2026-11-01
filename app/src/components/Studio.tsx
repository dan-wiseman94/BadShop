import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { action, imageUrl, useCoreQuery, useSession } from "../data";
import { rpc } from "../rpc";
import { useUI } from "../store";
import { openLink } from "../native";
import { sourceCard } from "../sourceCard";
import { ArtifactThumb } from "./Viewer";
import { LayoutsPacks } from "./LayoutsPacks";
import { ImagePairs } from "./ImagePairs";
import { RecentChoices } from "./RecentChoices";
import { LocalMedia } from "./LocalMedia";
import { IdeaMixer } from "./IdeaMixer";
import { SpriteSheet } from "./SpriteSheet";
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
function LibraryImage({ entry }: { entry: LibraryEntry }) {
  const { data } = useQuery({
    queryKey: ["library.thumbnail", entry.id],
    queryFn: ({ signal }) =>
      rpc.request("library.thumbnail", { id: entry.id, max_px: 240 }, signal),
  });
  return <img className="studio-thumb" src={imageUrl(data)} alt={entry.name} />;
}
export function Studio({
  onClose,
  onAttach,
  onDraft,
}: {
  onClose: () => void;
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
}) {
  const [tab, setTab] = useState("discover");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [purpose, setPurpose] = useState("subject");
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
    if (sources.length && source !== "all" && !sources.some(item => item.id === source && item.configured)) setSource("all");
  }, [sources, source]);
  const selected = useUI((s) => s.selectedArtifact);
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
  async function perform(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function acquire(params: Params) {
    const step = await action("tools.run", { tool: "acquire", params });
    if (step.status !== "done" || !step.outputs[0])
      throw new Error(
        [
          step.error?.message ?? "The image could not be imported.",
          step.error?.hint,
        ]
          .filter(Boolean)
          .join(" "),
      );
    onAttach(step.outputs[0]);
    useUI
      .getState()
      .set({
        selectedArtifact: step.outputs[0],
        notice: "Image added to your session and attached to chat",
      });
  }
  async function search(variation = "balanced", candidate?: Candidate) {
    const step = await action("tools.run", {
      tool: "discover",
      params: {
        query: query || candidate?.title,
        source: sources.some(item => item.id === source && item.configured) ? source : "all",
        purpose,
        n: 8,
        ...(candidate
          ? { reference_url: candidate.thumbnail || candidate.url }
          : {}),
        ...(pose.trim() ? { pose: pose.trim() } : {}),
        ...(expression.trim() ? { expression: expression.trim() } : {}),
        same_subject: sameSubject,
        variation,
        ...(variation === "different"
          ? { exclude_urls: candidates.map((c) => c.url) }
          : {}),
      },
    });
    if (step.status !== "done")
      throw new Error(
        [step.error?.message ?? "Search failed.", step.error?.hint]
          .filter(Boolean)
          .join(" "),
      );
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
      <section
        className="modal studio"
        role="dialog"
        aria-modal="true"
        aria-labelledby="studio-title"
      >
        <div className="modal-heading">
          <div>
            <h2 id="studio-title">Images & directions</h2>
            <p>Find material, keep your favorites, and try another take.</p>
          </div>
          <button aria-label="Close images and directions" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <nav className="studio-tabs" aria-label="Images and directions">
          {[
            ["discover", "Find images"],
            ["ideas", "Idea mixer"],
            ["library", "Junk drawer"],
            ["branches", "Branches"],
            ["layouts", "Layouts & packs"],
            ["local", "Clips, pages & folders"],
            ["sheets", "Sprite sheets"],
            ["pairs", "Image pairs"],
            ["recent", "Recent choices"],
          ].map(([id, label]) => (
            <button
              key={id}
              aria-pressed={tab === id}
              onClick={() => {
                setTab(id);
                setError("");
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {session?.turn_running && (
          <p>Stop the agent before changing images or branches.</p>
        )}
        {tab === "discover" && (
          <>
            <details className="collection-status">
              <summary>Collection availability</summary>
              <p>Ready means the required configuration is present; it does not test the service or validate its credentials.</p>
              {sourceError && <p role="alert">Could not read collection configuration. Reconnect to the core and try again.</p>}
              <table><thead><tr><th>Collection</th><th>Status</th><th>Setup</th></tr></thead><tbody>{sources.map(item => <tr key={item.id}>
                <td>{item.name}</td><td>{item.configured ? "Ready" : "Needs configuration"}</td>
                <td>{item.env_var ? <code>{item.env_var}</code> : "No key needed"}</td>
              </tr>)}</tbody></table>
              <p>Set the named environment variable before starting the app. Credential values are never shown here.</p>
            </details>
            <form
              className="studio-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(() => search());
              }}
            >
              <label className="wide">
                Subject or scene
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="A furious dog at an office desk"
                  required
                />
              </label>
              <label>
                Collection
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="all">All public collections</option>
                  {sources.map(item => (
                    <option key={item.id} value={item.id} disabled={!item.configured}>
                      {item.name}{!item.configured ? " (needs configuration)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Needed for
                <select
                  value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}
                >
                  {[
                    ["subject", "Main subject"],
                    ["head", "Head swap"],
                    ["background", "Background"],
                    ["object", "Object / prop"],
                  ].map(([id, title]) => (
                    <option key={id} value={id}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Pose / framing
                <input
                  value={pose}
                  onChange={(e) => setPose(e.target.value)}
                  placeholder="Facing left, whole head visible"
                />
              </label>
              <label>
                Expression
                <input
                  value={expression}
                  onChange={(e) => setExpression(e.target.value)}
                  placeholder="Surprised, mouth open"
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={sameSubject}
                  onChange={(e) => setSameSubject(e.target.checked)}
                />
                More pictures of this exact subject
              </label>
              <button className="primary" disabled={disabled || !query.trim()}>
                {busy ? "Working…" : "Find candidates"}
              </button>
            </form>
            {sheet && (
              <div className="studio-sheet">
                <ArtifactThumb
                  id={sheet}
                  label="Candidate contact sheet"
                  onClick={() =>
                    useUI.getState().set({ selectedArtifact: sheet })
                  }
                />
              </div>
            )}
            {!!candidates.length && (
              <div className="studio-grid">
                {candidates.map((c, i) => {
                  const preview = [
                    c.thumbnail_data_url,
                    c.preview,
                    c.thumbnail,
                  ].find((v) => v?.startsWith("data:image/"));
                  return (
                    <article className="studio-card" key={c.id ?? c.url}>
                      {preview && (
                        <img
                          className="studio-thumb"
                          src={preview}
                          alt={c.title}
                        />
                      )}
                      <strong>
                        {i + 1}. {c.title}
                      </strong>
                      <small>
                        {c.source.kind} ·{" "}
                        {c.source.license || "Rights not supplied"}
                      </small>
                      {c.reasons?.length ? (
                        <small>{c.reasons.join(" · ")}</small>
                      ) : null}
                      <div className="studio-actions">
                        <button
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
                        >
                          Use image
                        </button>
                        <button
                          disabled={disabled}
                          onClick={() =>
                            void perform(() => search("similar", c))
                          }
                        >
                          More like this
                        </button>
                        <button
                          disabled={disabled}
                          onClick={() =>
                            void perform(() => search("different", c))
                          }
                        >
                          Different view
                        </button>
                        {(c.source.page ?? c.page)?.match(/^https?:\/\//) && (
                          <button
                            onClick={() =>
                              void perform(async () => {
                                await openLink((c.source.page ?? c.page)!);
                              })
                            }
                          >
                            Source
                          </button>
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
              <label>
                Image URL or browser source card
                <textarea
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                  placeholder="Paste an image address or use the browser helper’s Send image to badshop action"
                />
              </label>
              <button disabled={disabled || !link.trim()}>
                Import selected web image
              </button>
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
                      .find(
                        (s) =>
                          s.tool === "find" &&
                          s.params.image === image &&
                          s.data?.faces,
                      );
                    await action("library.save", {
                      artifact_id: image,
                      name,
                      tags: tagList(),
                      metadata: {
                        ...(faceStep?.data?.faces
                          ? { faces: faceStep.data.faces }
                          : {}),
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
                  placeholder={
                    image
                      ? session?.artifacts[image]?.label
                      : "Select an image first"
                  }
                  required
                />
              </label>
              <label>
                Tags, separated by commas
                <input
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="screaming, facing right, giant head"
                />
              </label>
              <button
                disabled={disabled || (!image && !editing) || !name.trim()}
              >
                {editing ? "Update asset" : "Save to junk drawer"}
              </button>
              {editing && (
                <button
                  type="button"
                  onClick={() => {
                    setEditing(null);
                    setName("");
                    setTags("");
                  }}
                >
                  Cancel editing
                </button>
              )}
            </form>
            <label className="studio-filter">
              Search saved images
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Name or tag"
              />
            </label>
            {!library.length && (
              <p>
                Keep useful heads, props, backgrounds, and cutouts here for your
                next session.
              </p>
            )}
            <div className="studio-grid">
              {library
                .filter((e) =>
                  `${e.name} ${e.tags.join(" ")}`
                    .toLowerCase()
                    .includes(filter.toLowerCase()),
                )
                .map((entry) => (
                  <article className="studio-card" key={entry.id}>
                    <LibraryImage entry={entry} />
                    <strong>{entry.name}</strong>
                    <small>{entry.tags.join(" · ")}</small>
                    <small>
                      {entry.artifact.source?.license || "Rights not supplied"}
                    </small>
                    <div className="studio-actions">
                      <button
                        disabled={disabled}
                        onClick={() =>
                          void perform(async () => {
                            const result = await action("library.import", {
                              id: entry.id,
                            });
                            onAttach(result.working.id);
                            useUI
                              .getState()
                              .set({
                                selectedArtifact: result.working.id,
                                notice: `${entry.name} attached to chat`,
                              });
                          })
                        }
                      >
                        Use image
                      </button>
                      <button
                        disabled={disabled}
                        onClick={() => {
                          setEditing(entry);
                          setName(entry.name);
                          setTags(entry.tags.join(", "));
                        }}
                      >
                        Edit tags / name
                      </button>
                      <button
                        disabled={disabled}
                        onClick={() => setConfirmRemove(entry.id)}
                      >
                        Remove
                      </button>
                      {confirmRemove === entry.id && (
                        <>
                          <span>Remove from the drawer?</span>
                          <button
                            disabled={disabled}
                            onClick={() =>
                              void perform(async () => {
                                await action("library.remove", {
                                  id: entry.id,
                                });
                                setConfirmRemove(null);
                              })
                            }
                          >
                            Yes, remove
                          </button>
                          <button onClick={() => setConfirmRemove(null)}>
                            Keep
                          </button>
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
              Each branch keeps its own images, chat, and editable steps.
              Switching preserves your current work; save the project to keep
              every branch together.
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
              <label>
                New branch name
                <input
                  value={branchName}
                  onChange={(e) => setBranchName(e.target.value)}
                  placeholder="Giant dog version"
                  required
                />
              </label>
              <label>
                Start from
                <select
                  value={fromStep}
                  onChange={(e) => setFromStep(e.target.value)}
                >
                  <option value="">Current state</option>
                  {session?.steps
                    .filter((s) => s.status === "done")
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        Step {s.index}: {s.tool}
                      </option>
                    ))}
                </select>
              </label>
              <button disabled={disabled || !branchName.trim()}>
                Create & switch
              </button>
            </form>
            <div className="studio-grid">
              {branches?.branches.map((branch) => (
                <article className="studio-card" key={branch.id}>
                  {branch.preview_id &&
                    session?.artifacts[branch.preview_id] && (
                      <ArtifactThumb
                        id={branch.preview_id}
                        label={branch.name}
                      />
                    )}
                  <strong>
                    {branch.name}
                    {branch.id === branches.active_id ? " (current)" : ""}
                  </strong>
                  <small>{branch.step_count} steps</small>
                  <button
                    disabled={disabled || branch.id === branches.active_id}
                    onClick={() =>
                      void perform(async () => {
                        await action("branches.switch", {
                          id: branch.id,
                          expected_revision: session?.document_revision,
                        });
                      })
                    }
                  >
                    Switch to this take
                  </button>
                </article>
              ))}
            </div>
          </>
        )}
        {tab === "layouts" && <LayoutsPacks key={session?.id} onAttach={onAttach} />}
        {tab === "ideas" && <IdeaMixer onDraft={onDraft} onSearch={value => {
          setQuery(value); setPurpose("background"); setSource("all"); setPose(""); setExpression("");
          setSameSubject(false); setCandidates([]); setSheet(null); setNotes(""); setTab("discover");
        }} />}
        {tab === "sheets" && <SpriteSheet key={`${session?.id}-${useUI.getState().documentGeneration}`} onAttach={onAttach} />}
        {tab === "local" && <LocalMedia key={session?.id} onAttach={onAttach} />}
        {tab === "pairs" && <ImagePairs key={`${session?.id}-${useUI.getState().documentGeneration}`} onAttach={onAttach} />}
        {tab === "recent" && <RecentChoices />}
      </section>
    </div>
  );
}
