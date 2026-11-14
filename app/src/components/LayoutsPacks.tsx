import { Button } from "./Button";
import { useOperation } from "../useOperation";
import { InputField, SelectField } from "./Fields";
import { useState } from "react";
import { action, queries, useCoreQuery, useSession } from "../data";
import { packPath } from "../native";
import { useUI } from "../store";
import type { LayoutDefinition } from "../types";
import { ArtifactThumb } from "./Viewer";

type Box = LayoutDefinition["slots"][number]["box"];
export function LayoutsPacks({ onAttach }: { onAttach: (id: string) => void }) {
  const { busy, error, notice, setNotice, perform } = useOperation();
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
  const [focalPoints, setFocalPoints] = useState<number[][]>([]);
  const [panelBorder, setPanelBorder] = useState(3);
  const [panelPadding, setPanelPadding] = useState(0);
  const [preview, setPreview] = useState<{ signature: string; images: string[] } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  const ready = useUI((s) => s.status === "ready");
  const disabled = !ready || busy || !!session?.turn_running;
  const definition = definitions.find((item) => item.id === template);
  const assigned = images.map((id, index) => ({ id, index })).filter(item => item.id);
  const params = {
    template, title, images: assigned.map(item => item.id), image_slots: assigned.map(item => item.index),
    captions: definition?.slots.map((_, i) => captions[i] ?? "") ?? [], fit,
    panel_border: panelBorder, panel_padding: panelPadding, exact_text: true,
    focal_points: definition?.slots.map((_, i) => focalPoints[i] ?? [0.5, 0.5]) ?? [],
    ...(boxes ? { slots: boxes } : {}),
  };
  const signature = JSON.stringify(params);

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
        Arrange real images into fixed slots. Every image, caption, and position stays editable in the
        timeline.
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
            const step = await action("tools.run", {
              tool: "layout",
              params,
            });
            if (step.status !== "done" || !step.outputs[0])
              throw new Error(
                [step.error?.message, step.error?.hint].filter(Boolean).join(" ") ||
                  "The layout could not be created.",
              );
            onAttach(step.outputs[0]);
            useUI.getState().set({ selectedArtifact: step.outputs[0] });
            setNotice("Layout created and attached to chat.");
          });
        }}
      >
        <div className="studio-form">
          <InputField label="Panel border (px)" type="number" min={0} max={30} value={panelBorder}
            disabled={disabled} onChange={event => setPanelBorder(event.target.valueAsNumber)} />
          <InputField label="Panel inner margin (px)" type="number" min={0} max={100} value={panelPadding}
            disabled={disabled} onChange={event => setPanelPadding(event.target.valueAsNumber)} />
          <SelectField
            label="Layout template"
            value={template}
            onChange={(e) => {
              setTemplate(e.target.value);
              setImages([]);
              setCaptions([]);
              setBoxes(null);
              setFocalPoints([]);
            }}
          >
            {definitions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.max_images} slots)
              </option>
            ))}
          </SelectField>
          <InputField label="Layout title" maxLength={300} bind={[title, setTitle]} />
          <SelectField
            label="Image fitting"
            bind={[fit, setFit]}
            options={[
              ["contain", "Keep whole image"] as const,
              ["cover", "Crop to fill slot"] as const,
              ["stretch", "Stretch to slot"] as const,
            ]}
          />
        </div>
        <div className="studio-grid">
          {definition?.slots.map((slot, index) => (
            <fieldset className="studio-card" key={`${template}-${index}`}
              onDragOver={event => { if (!disabled) event.preventDefault(); }}
              onDrop={event => {
                event.preventDefault();
                if (disabled) return;
                const id = event.dataTransfer.getData("application/x-badshop-artifact");
                if (session?.artifacts[id]) setImages(previous => replace(previous, index, id));
              }}>
              <legend>{slot.name}</legend>
              <label>
                Image for {slot.name}
                <select
                  aria-label={`Image for ${slot.name}`}
                  value={images[index] ?? ""}
                  onChange={(e) => setImages((previous) => replace(previous, index, e.target.value))}
                >
                  <option value="">Leave empty</option>
                  {Object.values(session?.artifacts ?? {}).map((image) => (
                    <option key={image.id} value={image.id}>
                      {image.label} ({image.width}×{image.height})
                    </option>
                  ))}
                </select>
              </label>
              <details><summary>Choose {slot.name} visually</summary><div className="artifact-list">
                {Object.values(session?.artifacts ?? {}).filter(image => !Object.values(session?.artifacts ?? {}).some(other => other.original_id === image.id)).map(image =>
                  <ArtifactThumb key={image.id} id={image.id} label={image.label}
                    onClick={() => { if (!disabled) setImages(previous => replace(previous, index, image.id)); }} />)}
              </div></details>
              {fit === "cover" && <div>
                {["Horizontal", "Vertical"].map((axis, coordinate) => <label key={axis}>
                  {axis} crop focus for {slot.name}
                  <input type="range" min={0} max={1} step={0.01} value={focalPoints[index]?.[coordinate] ?? 0.5}
                    onChange={event => setFocalPoints(previous => {
                      const point = [...(previous[index] ?? [0.5, 0.5])];
                      point[coordinate] = Number(event.target.value);
                      return replace(previous, index, point);
                    })} />
                </label>)}
              </div>}
              <label>
                Caption for {slot.name}
                <textarea
                  maxLength={1000}
                  value={captions[index] ?? ""}
                  onChange={(e) => setCaptions((previous) => replace(previous, index, e.target.value))}
                />
              </label>
              <details>
                <summary>Image slot coordinates</summary>
                <div className="slot-coordinates">
                  {["Left", "Top", "Right", "Bottom"].map((axis, coordinate) => (
                    <label key={axis}>
                      {axis}
                      <input
                        type="number"
                        min={0}
                        max={coordinate % 2 ? definition.height : definition.width}
                        value={(boxes ?? definition.slots.map((s) => s.box))[index][coordinate]}
                        onChange={(e) =>
                          setBoxes((previous) => {
                            const next = (previous ?? definition.slots.map((s) => s.box)).map(
                              (b) => [...b] as Box,
                            );
                            next[index][coordinate] = Number(e.target.value);
                            return next;
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
              </details>
            </fieldset>
          ))}
        </div>
        <Button type="button" disabled={disabled || !definition || !session} label="Preview layout"
          onClick={() => void perform(async () => setPreview({ signature, images: await action("tools.preview", {
            tool: "layout", params, expected_revision: session!.document_revision,
          }) }))} />
        {preview?.signature === signature && <div>
          {preview.images.map((src, index) => <img key={index} src={src} alt="Uncommitted layout preview" style={{ maxWidth: "100%", maxHeight: 360, imageRendering: "pixelated" }} />)}
          <Button type="button" label="Dismiss layout preview" onClick={() => setPreview(null)} />
        </div>}
        <Button className="primary" disabled={disabled || !definition} label="Create layout" />
      </form>
      <h3>Period asset packs</h3>
      <p>Original hard-edged decorations, ready to install into your junk drawer.</p>
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
                  setNotice(`${entries.length} assets added to your junk drawer.`);
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
        Choose saved assets to export. Packs include images, originals, tags, source credits, and placement
        anchors.
      </p>
      <div className="pack-selection">
        {library.map((entry) => (
          <label key={entry.id} className="check-label">
            <input
              type="checkbox"
              checked={selected.includes(entry.id)}
              onChange={(e) =>
                setSelected((previous) =>
                  e.target.checked ? [...previous, entry.id] : previous.filter((id) => id !== entry.id),
                )
              }
            />
            {entry.name}
          </label>
        ))}
      </div>
      <div className="studio-actions">
        <Button
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
          label="Export selected assets"
        />
        <Button
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
          label="Import asset pack"
        />
      </div>
    </div>
  );
}
