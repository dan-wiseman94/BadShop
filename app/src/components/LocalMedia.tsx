import { useState } from "react";
import "../localMedia.css";
import { action, useCoreQuery, useSession } from "../data";
import { chooseMediaFile, chooseCollectionFolder } from "../native";
import { useUI } from "../store";
import type { Artifact } from "../types";

type Frame = {
  id: string;
  label: string;
  time_s?: number;
  page?: number;
  thumbnail_data_url: string;
  width: number;
  height: number;
};
type Preview = {
  id: string;
  source_name: string;
  kind: string;
  width: number;
  height: number;
  sheet_data_url: string;
  candidates: Frame[];
  warnings: string[];
};
type Indexed = {
  id: string;
  name: string;
  tags: string[];
  description: string;
  thumbnail_data_url: string;
  width: number;
  height: number;
  duplicate_of?: string | null;
};

export function LocalMedia({ onAttach }: { onAttach: (id: string) => void }) {
  const [mode, setMode] = useState<"video" | "document" | "folder">("video");
  const [path, setPath] = useState("");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [crop, setCrop] = useState<number[] | null>(null);
  const [origin, setOrigin] = useState<number[] | null>(null);
  const [animate, setAnimate] = useState(false);
  const [delay, setDelay] = useState(100);
  const [collection, setCollection] = useState("");
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<Indexed[]>([]);
  const [editing, setEditing] = useState<Indexed | null>(null);
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { data: collections = [] } = useCoreQuery("collections.list");
  const { data: session } = useSession();
  const ready = useUI((state) => state.status === "ready");
  const disabled = busy || !ready || !!session?.turn_running;
  async function perform(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function attach(images: Artifact[]) {
    images.forEach((image) => onAttach(image.id));
    setNotice(`${images.length} image(s) added to chat`);
  }
  const active = preview?.candidates.find((c) => selected[0] === c.id);
  function point(event: React.PointerEvent<HTMLImageElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.round(
        Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) *
          active!.width,
      ),
      Math.round(
        Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) *
          active!.height,
      ),
    ];
  }
  return (
    <div className="local-media">
      <nav className="studio-tabs" aria-label="Local source kinds">
        {[
          ["video", "Video / GIF"],
          ["document", "Pages / scans"],
          ["folder", "My folders"],
        ].map(([id, title]) => (
          <button
            key={id}
            aria-pressed={mode === id}
            disabled={busy}
            onClick={() => {
              setMode(id as typeof mode);
              setPath("");
              setPreview(null);
              setCrop(null);
              setSelected([]);
            }}
          >
            {title}
          </button>
        ))}
      </nav>
      <p>
        {mode === "folder"
          ? "Index a folder you choose. Images stay on disk until selected; filenames, tags, descriptions, and thumbnails stay in a local index."
          : "Preview a source you choose, then import only the frames or page region you need. Selected pixels and source details are saved with the project."}
      </p>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <form
        className="studio-form"
        onSubmit={(e) => {
          e.preventDefault();
          void perform(async () => {
            if (mode === "folder") {
              const result = await action("collections.index", { path });
              setCollection(result.id);
              setEditing(null);
              setEntries(await action("collections.search", { id: result.id }));
              setNotice(
                `${result.count} images indexed; ${result.duplicates} duplicates. ${result.warnings.join(" ")}`,
              );
            } else {
              const result = await action("media.preview", {
                path,
                kind: mode,
                ...(mode === "video"
                  ? { start, ...(end ? { end: Number(end) } : {}) }
                  : { page }),
              });
              setPreview(result);
              setSelected([]);
              setCrop(null);
            }
          });
        }}
      >
        <label className="wide">
          {mode === "folder" ? "Selected folder" : "Selected source file"}
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="Absolute path, or choose below"
            required
          />
        </label>
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            void perform(async () => {
              const chosen =
                mode === "folder"
                  ? await chooseCollectionFolder()
                  : await chooseMediaFile(mode);
              if (chosen) setPath(chosen);
            })
          }
        >
          Choose {mode === "folder" ? "folder" : "file"}
        </button>
        {mode === "video" && (
          <>
            <label>
              Start time (seconds)
              <input
                type="number"
                min="0"
                step="0.1"
                value={start}
                onChange={(e) => setStart(Number(e.target.value))}
              />
            </label>
            <label>
              End time (optional)
              <input
                type="number"
                min="0"
                step="0.1"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                placeholder="Up to 30 seconds by default"
              />
            </label>
          </>
        )}
        {mode === "document" && (
          <label>
            Page number
            <input
              type="number"
              min="1"
              value={page}
              onChange={(e) => setPage(Number(e.target.value))}
            />
          </label>
        )}
        <button className="primary" disabled={disabled || !path.trim()}>
          {busy
            ? "Working…"
            : mode === "folder"
              ? "Index selected folder"
              : "Preview source"}
        </button>
      </form>
      {preview && (
        <>
          <details>
            <summary>Contact sheet</summary>
            <img
              className="media-sheet"
              src={preview.sheet_data_url}
              alt="Numbered source frames"
            />
          </details>
          {preview.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
          <div className="studio-grid">
            {preview.candidates.map((frame) => (
              <label className="studio-card" key={frame.id}>
                <img
                  className="studio-thumb"
                  src={frame.thumbnail_data_url}
                  alt={frame.label}
                />
                <span>
                  <input
                    type="checkbox"
                    aria-label={`Select ${frame.label}`}
                    checked={selected.includes(frame.id)}
                    onChange={(e) => {
                      setSelected((old) =>
                        e.target.checked
                          ? [...old, frame.id]
                          : old.filter((id) => id !== frame.id),
                      );
                      setCrop(null);
                    }}
                  />
                  {frame.label}
                </span>
              </label>
            ))}
          </div>
          {active && selected.length === 1 && (
            <>
              <p>
                Drag across this preview to choose a region. Coordinates refer
                to the {active.width} × {active.height} working image.
              </p>
              <div
                className="media-crop-stage"
                style={{ width: Math.min(600, active.width), maxWidth: "100%" }}
              >
                <img
                  draggable={false}
                  src={active.thumbnail_data_url}
                  alt="Drag to select a source region"
                  onPointerCancel={() => setOrigin(null)}
                  onPointerDown={(e) => {
                    e.currentTarget.setPointerCapture(e.pointerId);
                    setOrigin(point(e));
                    setCrop(null);
                  }}
                  onPointerUp={(e) => {
                    if (!origin) return;
                    const end = point(e);
                    const box = [
                      Math.min(origin[0], end[0]),
                      Math.min(origin[1], end[1]),
                      Math.max(origin[0], end[0]),
                      Math.max(origin[1], end[1]),
                    ];
                    setCrop(box[0] < box[2] && box[1] < box[3] ? box : null);
                    setOrigin(null);
                  }}
                />
                {crop && (
                  <span
                    className="media-crop-box"
                    style={{
                      left: `${(crop[0] / active.width) * 100}%`,
                      top: `${(crop[1] / active.height) * 100}%`,
                      width: `${((crop[2] - crop[0]) / active.width) * 100}%`,
                      height: `${((crop[3] - crop[1]) / active.height) * 100}%`,
                    }}
                  />
                )}
              </div>
              <div className="studio-form">
                {["Left", "Top", "Right", "Bottom"].map((label, i) => (
                  <label key={label}>
                    Crop {label.toLowerCase()}
                    <input
                      type="number"
                      min="0"
                      max={i % 2 ? active.height : active.width}
                      value={
                        crop?.[i] ?? [0, 0, active.width, active.height][i]
                      }
                      onChange={(e) =>
                        setCrop((old) => {
                          const next = [
                            ...(old ?? [0, 0, active.width, active.height]),
                          ];
                          next[i] = Number(e.target.value);
                          return next;
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              {crop && (
                <button onClick={() => setCrop(null)}>
                  Use whole frame / page
                </button>
              )}
            </>
          )}
          {selected.length > 1 && (
            <div className="studio-form">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={animate}
                  onChange={(e) => setAnimate(e.target.checked)}
                />
                Make an animated sequence
              </label>
              <label>
                Frame delay (milliseconds)
                <input
                  type="number"
                  min="20"
                  max="10000"
                  value={delay}
                  onChange={(e) => setDelay(Number(e.target.value))}
                />
              </label>
            </div>
          )}
          <button
            className="primary"
            disabled={disabled || !selected.length}
            onClick={() =>
              void perform(async () => {
                const result = await action("media.import", {
                  preview_id: preview.id,
                  candidate_ids: selected,
                  ...(crop && selected.length === 1
                    ? { crop: crop as [number, number, number, number] }
                    : {}),
                  animate: selected.length > 1 && animate,
                  delay,
                });
                attach(result.artifacts);
              })
            }
          >
            Import selected {crop ? "region" : "frames"}
          </button>
        </>
      )}
      {mode === "folder" && (
        <>
          <form
            className="studio-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () =>
                setEntries(
                  await action("collections.search", { id: collection, query }),
                ),
              );
            }}
          >
            <label>
              Indexed collection
              <select
                value={collection}
                onChange={(e) => {
                  setCollection(e.target.value);
                  setEntries([]);
                  setEditing(null);
                }}
              >
                <option value="">Choose a collection</option>
                {collections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.count})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Find by name, tag, or description
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Disappointed dog"
              />
            </label>
            <button disabled={disabled || !collection}>
              Search collection
            </button>
          </form>
          <div className="studio-grid">
            {entries.map((entry) => (
              <article className="studio-card" key={entry.id}>
                <img
                  className="studio-thumb"
                  src={entry.thumbnail_data_url}
                  alt={entry.name}
                />
                <strong>{entry.name}</strong>
                <small>
                  {entry.tags.join(" · ")}
                  {entry.duplicate_of ? " · duplicate image" : ""}
                </small>
                <p>{entry.description}</p>
                <div className="studio-actions">
                  <button
                    disabled={disabled}
                    onClick={() =>
                      void perform(async () => {
                        const result = await action("collections.import", {
                          collection_id: collection,
                          id: entry.id,
                        });
                        attach([result.working]);
                      })
                    }
                  >
                    Use local image
                  </button>
                  <button
                    disabled={disabled}
                    onClick={() => {
                      setEditing(entry);
                      setTags(entry.tags.join(", "));
                      setDescription(entry.description);
                    }}
                  >
                    Edit description / tags
                  </button>
                  <button
                    disabled={disabled || !session?.provider_profile_id}
                    onClick={() =>
                      void perform(async () => {
                        const result = await action("collections.import", {
                          collection_id: collection,
                          id: entry.id,
                        });
                        onAttach(result.working.id);
                        await action("chat.send", {
                          text: "Describe only the attached image for my local image collection. Suggest a short literal description and comma-separated tags for visible objects, expressions, facing direction and framing. Do not modify images. I will review and save the text myself.",
                          attachments: [result.working.id],
                        });
                        setNotice(
                          "The selected image was sent to your art director. Review its suggested tags in chat, then save them here.",
                        );
                      })
                    }
                  >
                    Ask agent for tags
                  </button>
                </div>
              </article>
            ))}
          </div>
          {editing && (
            <form
              className="studio-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  await action("collections.update", {
                    collection_id: collection,
                    id: editing.id,
                    tags: tags
                      .split(",")
                      .map((t) => t.trim())
                      .filter(Boolean),
                    description,
                  });
                  setEntries(
                    await action("collections.search", {
                      id: collection,
                      query,
                    }),
                  );
                  setEditing(null);
                });
              }}
            >
              <strong className="wide">Describe {editing.name}</strong>
              <label>
                Description
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <label>
                Collection tags
                <input value={tags} onChange={(e) => setTags(e.target.value)} />
              </label>
              <button disabled={disabled}>Save searchable description</button>
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </form>
          )}
        </>
      )}
    </div>
  );
}
