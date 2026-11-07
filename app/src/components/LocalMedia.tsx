import { Button } from "./Button";
import { useOperation } from "../useOperation";
import { InputField, SelectField, TextAreaField } from "./Fields";
import { useState } from "react";
import "../localMedia.css";
import { action, useCoreQuery, useSession } from "../data";
import { chooseMediaFile, chooseCollectionFolder } from "../native";
import { useUI } from "../store";
import type { Artifact, MediaPreview, CollectionEntry } from "../types";

export function LocalMedia({ onAttach }: { onAttach: (id: string) => void }) {
  const { busy, error, notice, setNotice, perform } = useOperation();
  const [mode, setMode] = useState<"video" | "document" | "folder">("video");
  const [path, setPath] = useState("");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<MediaPreview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [crop, setCrop] = useState<number[] | null>(null);
  const [origin, setOrigin] = useState<number[] | null>(null);
  const [animate, setAnimate] = useState(false);
  const [delay, setDelay] = useState(100);
  const [collection, setCollection] = useState("");
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<CollectionEntry[]>([]);
  const [editing, setEditing] = useState<CollectionEntry | null>(null);
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");

  const { data: collections = [] } = useCoreQuery("collections.list");
  const { data: session } = useSession();
  const ready = useUI((state) => state.status === "ready");
  const disabled = busy || !ready || !!session?.turn_running;

  function attach(images: Artifact[]) {
    images.forEach((image) => onAttach(image.id));
    setNotice(`${images.length} image(s) added to chat`);
  }
  const active = preview?.candidates.find((c) => selected[0] === c.id);
  function point(event: React.PointerEvent<HTMLImageElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * active!.width),
      Math.round(Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) * active!.height),
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
          <Button
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
            label={title}
          />
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
                ...(mode === "video" ? { start, ...(end ? { end: Number(end) } : {}) } : { page }),
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
              const chosen = mode === "folder" ? await chooseCollectionFolder() : await chooseMediaFile(mode);
              if (chosen) setPath(chosen);
            })
          }
        >
          Choose {mode === "folder" ? "folder" : "file"}
        </button>
        {mode === "video" && (
          <>
            <InputField
              label="Start time (seconds)"
              type="number"
              min="0"
              step="0.1"
              bind={[start, setStart]}
            />
            <InputField
              label="End time (optional)"
              type="number"
              min="0"
              step="0.1"
              placeholder="Up to 30 seconds by default"
              bind={[end, setEnd]}
            />
          </>
        )}
        {mode === "document" && (
          <InputField label="Page number" type="number" min="1" bind={[page, setPage]} />
        )}
        <Button
          className="primary"
          disabled={disabled || !path.trim()}
          label={busy ? "Working…" : mode === "folder" ? "Index selected folder" : "Preview source"}
        />
      </form>
      {preview && (
        <>
          <details>
            <summary>Contact sheet</summary>
            <img className="media-sheet" src={preview.sheet_data_url} alt="Numbered source frames" />
          </details>
          {preview.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
          <div className="studio-grid">
            {preview.candidates.map((frame) => (
              <label className="studio-card" key={frame.id}>
                <img className="studio-thumb" src={frame.thumbnail_data_url} alt={frame.label} />
                <span>
                  <input
                    type="checkbox"
                    aria-label={`Select ${frame.label}`}
                    checked={selected.includes(frame.id)}
                    onChange={(e) => {
                      setSelected((old) =>
                        e.target.checked ? [...old, frame.id] : old.filter((id) => id !== frame.id),
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
                Drag across this preview to choose a region. Coordinates refer to the {active.width} ×{" "}
                {active.height} working image.
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
                      value={crop?.[i] ?? [0, 0, active.width, active.height][i]}
                      onChange={(e) =>
                        setCrop((old) => {
                          const next = [...(old ?? [0, 0, active.width, active.height])];
                          next[i] = Number(e.target.value);
                          return next;
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              {crop && <Button onClick={() => setCrop(null)} label="Use whole frame / page" />}
            </>
          )}
          {selected.length > 1 && (
            <div className="studio-form">
              <InputField
                label="Make an animated sequence"
                inputFirst
                labelClassName="check-label"
                type="checkbox"
                bind={[animate, setAnimate]}
              />
              <InputField
                label="Frame delay (milliseconds)"
                type="number"
                min="20"
                max="10000"
                bind={[delay, setDelay]}
              />
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
                setEntries(await action("collections.search", { id: collection, query })),
              );
            }}
          >
            <SelectField
              label="Indexed collection"
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
            </SelectField>
            <InputField
              label="Find by name, tag, or description"
              placeholder="Disappointed dog"
              bind={[query, setQuery]}
            />
            <Button disabled={disabled || !collection} label="Search collection" />
          </form>
          <div className="studio-grid">
            {entries.map((entry) => (
              <article className="studio-card" key={entry.id}>
                <img className="studio-thumb" src={entry.thumbnail_data_url} alt={entry.name} />
                <strong>{entry.name}</strong>
                <small>
                  {entry.tags.join(" · ")}
                  {entry.duplicate_of ? " · duplicate image" : ""}
                </small>
                <p>{entry.description}</p>
                <div className="studio-actions">
                  <Button
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
                    label="Use local image"
                  />
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      setEditing(entry);
                      setTags(entry.tags.join(", "));
                      setDescription(entry.description);
                    }}
                    label="Edit description / tags"
                  />
                  <Button
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
                    label="Ask agent for tags"
                  />
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
              <TextAreaField label="Description" bind={[description, setDescription]} />
              <InputField label="Collection tags" bind={[tags, setTags]} />
              <Button disabled={disabled} label="Save searchable description" />
              <Button type="button" onClick={() => setEditing(null)} label="Cancel" />
            </form>
          )}
        </>
      )}
    </div>
  );
}
