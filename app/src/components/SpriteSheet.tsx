import { useState } from "react";
import { action, imageUrl, useArtifact, useSession } from "../data";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";

type Margins = [number, number, number, number];
type Gap = [number, number];
export type SheetCell = {
  index: number;
  row: number;
  column: number;
  box: [number, number, number, number];
  width: number;
  height: number;
};

// Keep this integer-only geometry in sync with engine/sheets.py:grid_cells. Tests on both sides
// use the same uneven-size example, including sparse cells, margins and gaps.
export function sheetCells(
  width: number,
  height: number,
  rows: number,
  columns: number,
  margins: Margins,
  gap: Gap,
): SheetCell[] {
  if (![rows, columns].every((n) => Number.isInteger(n) && n >= 1 && n <= 16))
    throw new Error("Rows and columns must be whole numbers from 1 to 16.");
  if (
    ![...margins, ...gap].every(
      (n) => Number.isInteger(n) && n >= 0 && n <= 100_000,
    )
  )
    throw new Error(
      "Margins and gaps must be nonnegative whole pixels (at most 100000).",
    );
  const [left, top, right, bottom] = margins;
  const [gapX, gapY] = gap;
  const usableW = width - left - right - gapX * (columns - 1);
  const usableH = height - top - bottom - gapY * (rows - 1);
  if (usableW < columns || usableH < rows)
    throw new Error(
      "Margins and gaps must leave at least one pixel per row and column.",
    );
  const cellW = Math.floor(usableW / columns),
    extraW = usableW % columns;
  const cellH = Math.floor(usableH / rows),
    extraH = usableH % rows;
  return Array.from({ length: rows * columns }, (_, index) => {
    const row = Math.floor(index / columns),
      column = index % columns;
    const x = left + column * (cellW + gapX) + Math.min(column, extraW);
    const y = top + row * (cellH + gapY) + Math.min(row, extraH);
    const w = cellW + Number(column < extraW),
      h = cellH + Number(row < extraH);
    return {
      index,
      row,
      column,
      box: [x, y, x + w, y + h],
      width: w,
      height: h,
    };
  });
}

export function SpriteSheet({ onAttach }: { onAttach: (id: string) => void }) {
  const { data: session } = useSession();
  const ready = useUI((s) => s.status === "ready");
  const current = useUI((s) => s.selectedArtifact);
  const [sourceId, setSourceId] = useState(current ?? "");
  const [rows, setRows] = useState(2);
  const [columns, setColumns] = useState(2);
  const [margins, setMargins] = useState<Margins>([0, 0, 0, 0]);
  const [gap, setGap] = useState<Gap>([0, 0]);
  const [selection, setSelection] = useState<{
    key: string;
    indices: number[];
  }>({ key: "", indices: [] });
  const [results, setResults] = useState<{ id: string; cell: SheetCell }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const artifacts = Object.values(session?.artifacts ?? {});
  const originals = new Set(
    artifacts.map((a) => a.original_id).filter(Boolean),
  );
  const images = artifacts.filter((a) => !originals.has(a.id));
  const source = images.find((a) => a.id === sourceId) ?? images[0];
  const { data: preview, error: previewError } = useArtifact(
    source?.id ?? null,
  );
  const disabled = !ready || busy || !!session?.turn_running;
  let cells: SheetCell[] = [],
    gridError = "";
  if (source) {
    try {
      cells = sheetCells(
        source.width,
        source.height,
        rows,
        columns,
        margins,
        gap,
      );
    } catch (e) {
      gridError = e instanceof Error ? e.message : String(e);
    }
  }
  const key = JSON.stringify([source?.id, rows, columns, margins, gap]);
  const selected = selection.key === key ? selection.indices : [];
  function changeGrid(update: () => void) {
    update();
    setSelection({ key: "", indices: [] });
    setNotice("");
    setError("");
  }
  function toggle(index: number) {
    if (disabled || (!selected.includes(index) && selected.length >= 64))
      return;
    setSelection({
      key,
      indices: selected.includes(index)
        ? selected.filter((i) => i !== index)
        : [...selected, index].sort((a, b) => a - b),
    });
  }
  async function extract(indices: number[]) {
    if (
      disabled ||
      !source ||
      gridError ||
      !indices.length ||
      indices.length > 64
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const step = await action("tools.run", {
        tool: "slice_sheet",
        params: {
          image: source.id,
          rows,
          columns,
          margins,
          gap,
          cells: indices,
        },
      });
      if (step.status !== "done" || step.outputs.length !== indices.length)
        throw new Error(
          [step.error?.message, step.error?.hint].filter(Boolean).join(" ") ||
            "The cells could not be extracted.",
        );
      const extracted = (step.data?.cells ??
        indices.map((i) => cells[i])) as SheetCell[];
      setResults(step.outputs.map((id, i) => ({ id, cell: extracted[i] })));
      step.outputs.forEach(onAttach);
      useUI.getState().set({ selectedArtifact: step.outputs[0] });
      setNotice(`${indices.length} cells extracted and attached to chat.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <p>
        Slice a sprite sheet or image grid into separate images. Choose cells on
        the preview; each tile keeps its exact pixels and transparent padding.
      </p>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className="studio-form">
        <label className="wide">
          Sprite sheet image
          <select
            value={source?.id ?? ""}
            disabled={disabled}
            onChange={(e) => changeGrid(() => setSourceId(e.target.value))}
          >
            {!images.length && <option value="">Import an image first</option>}
            {images.map((image) => (
              <option key={image.id} value={image.id}>
                {image.label} ({image.width}×{image.height})
              </option>
            ))}
          </select>
        </label>
        <label>
          Rows
          <input
            type="number"
            min={1}
            max={16}
            step={1}
            value={rows}
            disabled={disabled}
            onChange={(e) => changeGrid(() => setRows(Number(e.target.value)))}
          />
        </label>
        <label>
          Columns
          <input
            type="number"
            min={1}
            max={16}
            step={1}
            value={columns}
            disabled={disabled}
            onChange={(e) =>
              changeGrid(() => setColumns(Number(e.target.value)))
            }
          />
        </label>
        {(["Left", "Top", "Right", "Bottom"] as const).map((name, i) => (
          <label key={name}>
            {name} margin
            <input
              type="number"
              min={0}
              max={100000}
              step={1}
              value={margins[i]}
              disabled={disabled}
              onChange={(e) =>
                changeGrid(() =>
                  setMargins(
                    (previous) =>
                      previous.map((v, n) =>
                        n === i ? Number(e.target.value) : v,
                      ) as Margins,
                  ),
                )
              }
            />
          </label>
        ))}
        {(["Horizontal", "Vertical"] as const).map((name, i) => (
          <label key={name}>
            {name} gap
            <input
              type="number"
              min={0}
              max={100000}
              step={1}
              value={gap[i]}
              disabled={disabled}
              onChange={(e) =>
                changeGrid(() =>
                  setGap(
                    (previous) =>
                      previous.map((v, n) =>
                        n === i ? Number(e.target.value) : v,
                      ) as Gap,
                  ),
                )
              }
            />
          </label>
        ))}
      </div>
      {source && (
        <p>
          Coordinates use the selected {source.width}×{source.height} image.
          Indices start at 0, left to right, then top to bottom. Extra pixels go
          to the first rows and columns.
        </p>
      )}
      {gridError && (
        <p role="alert" className="error-banner">
          {gridError}
        </p>
      )}
      {previewError && (
        <p role="alert" className="error-banner">
          Could not load the sheet preview.
        </p>
      )}
      {source && !preview && !previewError && <p>Loading sheet preview…</p>}
      {source && preview && !gridError && (
        <svg
          viewBox={`0 0 ${source.width} ${source.height}`}
          role="group"
          aria-label="Sprite sheet cell selection"
          style={{
            display: "block",
            width: "100%",
            maxHeight: 440,
            background: "var(--bg)",
            imageRendering: "pixelated",
          }}
        >
          <image
            href={imageUrl(preview)}
            width={source.width}
            height={source.height}
          />
          {cells.map((cell) => {
            const [x, y] = cell.box;
            const checked = selected.includes(cell.index);
            const blocked = disabled || (!checked && selected.length >= 64);
            return (
              <g
                key={cell.index}
                role="checkbox"
                tabIndex={blocked ? -1 : 0}
                aria-label={`Cell ${cell.index}, row ${cell.row}, column ${cell.column}`}
                aria-checked={checked}
                aria-disabled={blocked}
                onClick={() => toggle(cell.index)}
                onKeyDown={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    toggle(cell.index);
                  }
                }}
                style={{ cursor: blocked ? "default" : "pointer" }}
              >
                <title>{`Cell ${cell.index}: [${cell.box.join(", ")}), ${cell.width}×${cell.height} pixels`}</title>
                <rect
                  x={x}
                  y={y}
                  width={cell.width}
                  height={cell.height}
                  fill={checked ? "#ffd34f" : "#000000"}
                  fillOpacity={checked ? 0.35 : 0.04}
                  stroke={checked ? "#ffd34f" : "#ffffff"}
                  strokeWidth={checked ? 3 : 1}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={x + cell.width / 2}
                  y={y + cell.height / 2}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="white"
                  stroke="black"
                  strokeWidth={Math.max(
                    0.5,
                    Math.min(cell.width, cell.height) / 45,
                  )}
                  paintOrder="stroke"
                  fontSize={Math.max(1, Math.min(cell.width, cell.height) / 3)}
                  pointerEvents="none"
                >
                  {cell.index}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      <p aria-live="polite">
        {selected.length} selected (maximum 64)
        {selected.length ? `: ${selected.join(", ")}` : ""}
      </p>
      <div className="studio-actions">
        <button
          disabled={disabled || !selected.length}
          onClick={() => setSelection({ key, indices: [] })}
        >
          Clear selection
        </button>
        <button
          className="primary"
          disabled={disabled || !preview || !!gridError || !selected.length}
          onClick={() => void extract(selected)}
        >
          {busy ? "Extracting…" : "Extract selected and attach"}
        </button>
        <button
          disabled={
            disabled ||
            !preview ||
            !!gridError ||
            !cells.length ||
            cells.length > 64
          }
          onClick={() => void extract(cells.map((cell) => cell.index))}
        >
          Extract all and attach
        </button>
      </div>
      {cells.length > 64 && (
        <p>This grid has {cells.length} cells. Select up to 64 at a time.</p>
      )}
      <div className="studio-grid">
        {results
          .filter((result) => !!session?.artifacts[result.id])
          .map(({ id, cell }) => (
            <article className="studio-card" key={`${id}-${cell.index}`}>
              <strong>
                Cell {cell.index} · row {cell.row}, column {cell.column}
              </strong>
              <ArtifactThumb
                id={id}
                label={`Extracted cell ${cell.index}`}
                onClick={() => useUI.getState().set({ selectedArtifact: id })}
              />
              <small>
                {cell.width}×{cell.height} px · box [{cell.box.join(", ")})
              </small>
              <button disabled={disabled} onClick={() => onAttach(id)}>
                Attach cell {cell.index}
              </button>
            </article>
          ))}
      </div>
    </div>
  );
}
