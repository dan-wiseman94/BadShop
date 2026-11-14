import { useState } from "react";
import { imageUrl, useArtifact } from "../data";
import type { Params } from "../types";

export function CutoutRepair({ value, change, disabled }: {
  value: Params; change: (value: Params) => void; disabled: boolean;
}) {
  const { data } = useArtifact(typeof value.image === "string" ? value.image : null);
  const [points, setPoints] = useState<number[][]>([]);
  const [mode, setMode] = useState("keep_regions");
  const [zoom, setZoom] = useState(1);
  if (!data) return null;
  const regions = (key: string) => Array.isArray(value[key]) ? value[key] as number[][][] : [];
  return <section aria-label="Repair cutout selection">
    <h3>Keep or remove part of the subject</h3>
    <p>Click around a region on the original picture, then add it. Preview changes shows the repaired cutout. Removal wins where regions overlap.</p>
    <label>Region action <select value={mode} disabled={disabled} onChange={e => setMode(e.target.value)}>
      <option value="keep_regions">Keep this part</option><option value="remove_regions">Remove this part</option>
    </select></label>
    <label>Selection zoom <select value={zoom} onChange={e => setZoom(Number(e.target.value))}>
      <option value={1}>Fit</option><option value={2}>2×</option><option value={4}>4×</option>
    </select></label>
    <div style={{ overflow: "auto", maxHeight: 500 }}>
    <svg viewBox={`0 0 ${data.meta.width} ${data.meta.height}`} role="img" aria-label="Original picture for cutout regions"
      style={{ width: `${zoom * 100}%`, maxWidth: "none", display: "block", cursor: "crosshair", background: "#888" }}
      onClick={event => {
        if (disabled || points.length >= 100) return;
        const svg = event.currentTarget;
        const matrix = svg.getScreenCTM();
        if (!matrix) return;
        const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
        setPoints([...points, [Math.max(0, Math.min(data.meta.width - 1, Math.round(point.x))),
          Math.max(0, Math.min(data.meta.height - 1, Math.round(point.y)))]]);
      }}>
      <image href={imageUrl(data)} width={data.meta.width} height={data.meta.height} />
      {["keep_regions", "remove_regions"].flatMap(key => regions(key).map((region, i) =>
        <polygon key={`${key}-${i}`} points={region.map(p => p.join(",")).join(" ")} fill="none"
          stroke={key === "keep_regions" ? "#00ff00" : "#ff0000"} strokeWidth={2} vectorEffect="non-scaling-stroke" />))}
      <polyline points={points.map(p => p.join(",")).join(" ")} fill="none" stroke="#ffff00" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      {points.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={3} fill="#ffff00" />)}
    </svg>
    </div>
    <button type="button" disabled={disabled || points.length < 3 || regions(mode).length >= 32}
      onClick={() => { change({ ...value, [mode]: [...regions(mode), points] }); setPoints([]); }}>Add region</button>
    <button type="button" disabled={disabled || !points.length} onClick={() => setPoints(points.slice(0, -1))}>Undo point</button>
    <button type="button" disabled={disabled || !regions(mode).length}
      onClick={() => change({ ...value, [mode]: regions(mode).slice(0, -1) })}>Undo last region</button>
    <button type="button" disabled={disabled} onClick={() => {
      change({ ...value, keep_regions: [], remove_regions: [] }); setPoints([]);
    }}>Reset selection repairs</button>
  </section>;
}
