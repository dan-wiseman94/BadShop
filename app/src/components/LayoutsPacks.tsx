import { useState } from "react";
import { action, queries, useCoreQuery, useSession } from "../data";
import { packPath } from "../native";
import { useUI } from "../store";

type Box = [number, number, number, number];
type Layout = {
  id: string;
  name: string;
  width: number;
  height: number;
  max_images: number;
  slots: { name: string; box: Box; caption_box: Box; mask: string }[];
};
export function LayoutsPacks({ onAttach }: { onAttach: (id: string) => void }) {
  const { data: definitions = [] } = useCoreQuery("layouts.list");
  const { data: packs = [] } = useCoreQuery("packs.list");
  const { data: library = [] } = useCoreQuery("library.list");
  const { data: session } = useSession();
  const [template, setTemplate] = useState("trading-card");
  const [title, setTitle] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [captions, setCaptions] = useState<string[]>([]);
  const [boxes, setBoxes] = useState<Box[] | null>(null);
  const [fit, setFit] = useState("contain");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const ready = useUI((s) => s.status === "ready");
  const disabled = !ready || busy || !!session?.turn_running;
  const definition = (definitions as Layout[]).find(
    (item) => item.id === template,
  );
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
  function replace<T>(previous: T[], index: number, value: T): T[] {
    const next = previous.slice();
    next[index] = value;
    return next;
  }
  return (
    <div className="layouts-packs">
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <h3>Build a layout</h3>
      <p>
        Arrange real images into fixed slots. Every image, caption, and position
        stays editable in the timeline.
      </p>
      {definition && (
        <svg
          viewBox={`0 0 ${definition.width} ${definition.height}`}
          role="img"
          aria-label={`${definition.name} slot preview`}
          style={{
            height: 180,
            maxWidth: "100%",
            display: "block",
            margin: "12px auto",
          }}
        >
          <rect
            width={definition.width}
            height={definition.height}
            fill="var(--bg)"
            stroke="var(--muted)"
            strokeWidth={4}
          />
          {definition.slots.map((item, index) => {
            const [x1, y1, x2, y2] = boxes?.[index] ?? item.box;
            return (
              <g key={index}>
                <rect
                  x={x1}
                  y={y1}
                  width={Math.max(0, x2 - x1)}
                  height={Math.max(0, y2 - y1)}
                  fill="var(--raised)"
                  stroke="var(--accent)"
                  strokeWidth={5}
                />
                <text
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2}
                  textAnchor="middle"
                  fill="var(--text)"
                  fontSize={35}
                >
                  {index + 1}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void perform(async () => {
            const assigned = images
              .map((id, index) => ({ id, index }))
              .filter((item) => item.id);
            const step = await action("tools.run", {
              tool: "layout",
              params: {
                template,
                title,
                images: assigned.map((item) => item.id),
                image_slots: assigned.map((item) => item.index),
                captions:
                  definition?.slots.map((_, i) => captions[i] ?? "") ?? [],
                fit,
                ...(boxes ? { slots: boxes } : {}),
              },
            });
            if (step.status !== "done" || !step.outputs[0])
              throw new Error(
                [step.error?.message, step.error?.hint]
                  .filter(Boolean)
                  .join(" ") || "The layout could not be created.",
              );
            onAttach(step.outputs[0]);
            useUI.getState().set({ selectedArtifact: step.outputs[0] });
            setNotice("Layout created and attached to chat.");
          });
        }}
      >
        <div className="studio-form">
          <label>
            Layout template
            <select
              value={template}
              onChange={(e) => {
                setTemplate(e.target.value);
                setImages([]);
                setCaptions([]);
                setBoxes(null);
              }}
            >
              {(definitions as Layout[]).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.max_images} slots)
                </option>
              ))}
            </select>
          </label>
          <label>
            Layout title
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={300}
            />
          </label>
          <label>
            Image fitting
            <select value={fit} onChange={(e) => setFit(e.target.value)}>
              <option value="contain">Keep whole image</option>
              <option value="cover">Crop to fill slot</option>
              <option value="stretch">Stretch to slot</option>
            </select>
          </label>
        </div>
        <div className="studio-grid">
          {definition?.slots.map((slot, index) => (
            <fieldset className="studio-card" key={`${template}-${index}`}>
              <legend>{slot.name}</legend>
              <label>
                Image for {slot.name}
                <select
                  aria-label={`Image for ${slot.name}`}
                  value={images[index] ?? ""}
                  onChange={(e) =>
                    setImages((previous) =>
                      replace(previous, index, e.target.value),
                    )
                  }
                >
                  <option value="">Leave empty</option>
                  {Object.values(session?.artifacts ?? {}).map((image) => (
                    <option key={image.id} value={image.id}>
                      {image.label} ({image.width}×{image.height})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Caption for {slot.name}
                <textarea
                  maxLength={1000}
                  value={captions[index] ?? ""}
                  onChange={(e) =>
                    setCaptions((previous) =>
                      replace(previous, index, e.target.value),
                    )
                  }
                />
              </label>
              <details>
                <summary>Image slot coordinates</summary>
                <div className="slot-coordinates">
                  {["Left", "Top", "Right", "Bottom"].map(
                    (axis, coordinate) => (
                      <label key={axis}>
                        {axis}
                        <input
                          type="number"
                          min={0}
                          max={
                            coordinate % 2
                              ? definition.height
                              : definition.width
                          }
                          value={
                            (boxes ?? definition.slots.map((s) => s.box))[
                              index
                            ][coordinate]
                          }
                          onChange={(e) =>
                            setBoxes((previous) => {
                              const next = (
                                previous ?? definition.slots.map((s) => s.box)
                              ).map((b) => [...b] as Box);
                              next[index][coordinate] = Number(e.target.value);
                              return next;
                            })
                          }
                        />
                      </label>
                    ),
                  )}
                </div>
              </details>
            </fieldset>
          ))}
        </div>
        <button className="primary" disabled={disabled || !definition}>
          Create layout
        </button>
      </form>
      <h3>Period asset packs</h3>
      <p>
        Original hard-edged decorations, ready to install into your junk drawer.
      </p>
      <div className="studio-grid">
        {packs.map((pack) => (
          <article className="studio-card" key={pack.id}>
            <strong>{pack.name}</strong>
            <p>{pack.description}</p>
            <small>{pack.count} reusable assets</small>
            <button
              disabled={disabled}
              onClick={() =>
                void perform(async () => {
                  const entries = await action("packs.install", {
                    id: pack.id,
                  });
                  await queries.invalidateQueries({
                    queryKey: ["library.list"],
                  });
                  setNotice(
                    `${entries.length} assets added to your junk drawer.`,
                  );
                })
              }
            >
              Install {pack.name}
            </button>
          </article>
        ))}
      </div>
      <h3>Share a pack</h3>
      <p>
        Choose saved assets to export. Packs include images, originals, tags,
        source credits, and placement anchors.
      </p>
      <div className="pack-selection">
        {library.map((entry) => (
          <label key={entry.id} className="check-label">
            <input
              type="checkbox"
              checked={selected.includes(entry.id)}
              onChange={(e) =>
                setSelected((previous) =>
                  e.target.checked
                    ? [...previous, entry.id]
                    : previous.filter((id) => id !== entry.id),
                )
              }
            />
            {entry.name}
          </label>
        ))}
      </div>
      <div className="studio-actions">
        <button
          disabled={disabled || !selected.length}
          onClick={() =>
            void perform(async () => {
              const path = await packPath(true);
              if (typeof path !== "string") return;
              const result = await action("packs.export", {
                ids: selected,
                path,
              });
              setNotice(`Exported ${result.count} assets to ${result.path}`);
            })
          }
        >
          Export selected assets
        </button>
        <button
          disabled={disabled}
          onClick={() =>
            void perform(async () => {
              const path = await packPath(false);
              if (typeof path !== "string") return;
              const result = await action("packs.import", { path });
              await queries.invalidateQueries({ queryKey: ["library.list"] });
              setNotice(`Imported ${result.count} assets from ${result.name}.`);
            })
          }
        >
          Import asset pack
        </button>
      </div>
    </div>
  );
}
