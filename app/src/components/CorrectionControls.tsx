import { useRef, useState } from "react";
import { action, imageUrl, run, useArtifact } from "../data";
import type { Params } from "../types";

export function CorrectionControls({ tool, stepId, value, change, disabled }: {
  tool: string; stepId?: string; value: Params; change: (value: Params) => void; disabled: boolean;
}) {
  const reference = String(value.base ?? value.image ?? "");
  const { data } = useArtifact(reference || null);
  const { data: piece } = useArtifact(tool === "paste" && typeof value.piece === "string" ? value.piece : null);
  const drag = useRef<number[] | null>(null);
  const resizing = useRef(false);
  const [variants, setVariants] = useState<{ amount: number; image: string; label: string; signature: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const update = (patch: Params) => { change({ ...value, ...patch }); setVariants([]); };
  const box = Array.isArray(value.fit_box) ? value.fit_box as number[] : null;
  const fittedScale = box && piece ? Math.max(Math.abs(box[2] - box[0]) / piece.meta.width,
    Math.abs(box[3] - box[1]) / piece.meta.height) * Number(value.scale ?? 1) : null;
  const width = fittedScale && piece ? Math.max(1, Math.round(piece.meta.width * fittedScale)) : Number(value.width ?? piece?.meta.width ?? 100);
  const height = fittedScale && piece ? Math.max(1, Math.round(piece.meta.height * fittedScale))
    : Number(value.height ?? (piece ? piece.meta.height * width / piece.meta.width : width));
  const at = box ? [Math.min(box[0], box[2]) + Math.floor(Math.abs(box[2] - box[0]) / 2),
    Math.min(box[1], box[3]) + Math.floor(Math.abs(box[3] - box[1]) / 2)]
    : Array.isArray(value.at) ? value.at as number[] : [0, 0];
  const anchor = box ? "center" : String(value.anchor ?? "topleft");
  const move = (position: number[]) => update({ at: position, fit_box: undefined,
    ...(tool === "paste" ? { width, height, anchor } : {}) });
  const canPlace = (tool === "paste" && !value.repeat) || tool === "text";
  const field = tool === "paste" ? "rotate" : tool === "text" ? "size" : "seed";
  const alternatives = field === "rotate" ? [-15, 0, 15] : field === "size" ? [24, 40, 64] : [1, 2, 3];
  const point = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [Math.round((event.clientX - rect.left) * (data?.meta.width ?? 1) / rect.width),
      Math.round((event.clientY - rect.top) * (data?.meta.height ?? 1) / rect.height)];
  };
  return <section aria-label="Quick corrections">
    {tool === "text" && <label>Exact caption
      <textarea disabled={disabled} value={String(value.text ?? "")}
        onChange={(event) => update({ text: event.target.value })} />
      <button type="button" disabled={disabled} onClick={() => update({ size: undefined, fit_exact: true })}>Fit these words automatically</button>
    </label>}
    {canPlace && data && <>
      <p>Drag the anchor to place. Arrow keys nudge; Shift moves ten pixels. Preview changes renders the exact result.</p>
      <div role="group" aria-label="Placement controls" tabIndex={disabled ? -1 : 0}
        style={{ position: "relative", maxWidth: 400, touchAction: "none", cursor: "crosshair" }}
        onKeyDown={(event) => {
          if (disabled || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
          event.preventDefault();
          const distance = event.shiftKey ? 10 : 1;
          move([at[0] + (event.key === "ArrowLeft" ? -distance : event.key === "ArrowRight" ? distance : 0),
            at[1] + (event.key === "ArrowUp" ? -distance : event.key === "ArrowDown" ? distance : 0)]);
        }}
        onPointerDown={(event) => {
          if (disabled) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          resizing.current = (event.target as HTMLElement).dataset.resize === "true";
          drag.current = point(event);
          if (!resizing.current) move(drag.current);
        }}
        onPointerMove={(event) => {
          if (!drag.current || disabled) return;
          const position = point(event);
          if (resizing.current) update({ width: Math.max(1, Math.min(1000, (position[0] - at[0]) * (anchor === "topleft" ? 1 : 2))),
            at, anchor, fit_box: undefined, height: undefined });
          else move(position);
        }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <img src={imageUrl(data)} alt="Placement reference" draggable={false} style={{ width: "100%", display: "block" }} />
        {piece && !Number(value.rotate ?? 0) && <div style={{ position: "absolute", left: `${at[0] / data.meta.width * 100}%`,
          top: `${at[1] / data.meta.height * 100}%`, width: `${width / data.meta.width * 100}%`,
          height: `${height / data.meta.height * 100}%`, pointerEvents: "none",
          transform: anchor === "center" ? "translate(-50%, -50%)" : anchor === "bottom" ? "translate(-50%, -100%)" : undefined }}>
          <img src={imageUrl(piece)} alt="Replacement piece" draggable={false}
            style={{ width: "100%", height: "100%", display: "block", imageRendering: "pixelated",
              transform: `rotate(${-Number(value.rotate ?? 0)}deg) scaleX(${value.flip ? -1 : 1})` }} />
          <button type="button" data-resize="true" aria-label="Drag to resize piece" disabled={disabled}
            style={{ position: "absolute", right: 0, bottom: 0, pointerEvents: "auto", cursor: "nwse-resize" }}>↘</button>
        </div>}
        <span style={{ position: "absolute", left: `${at[0] / data.meta.width * 100}%`,
          top: `${at[1] / data.meta.height * 100}%`, color: "#ff00ff", transform: "translate(-50%, -50%)", pointerEvents: "none" }}>✛</span>
      </div>
      <label>Rotation <input type="range" min={-180} max={180} step={1} disabled={disabled}
        value={Number(value.rotate ?? 0)} onChange={(event) => update({ rotate: Number(event.target.value) })} /></label>
      {tool === "paste" && <>
        <label>Width <input type="number" min={1} max={1000} disabled={disabled} value={width}
          onChange={(event) => update({ width: event.target.valueAsNumber, at, anchor, fit_box: undefined })} /></label>
        <button type="button" disabled={disabled} onClick={() => update({ flip: !value.flip })}>Flip piece</button>
      </>}
    </>}
    {stepId && ["paste", "text", "sparkle", "deepfry", "pattern"].includes(tool) && <>
      <button type="button" disabled={disabled || busy} onClick={() => run(async () => {
        setBusy(true);
        try {
          const results = [];
          for (const amount of alternatives) {
            const params = { ...value, [field]: amount };
            const images = await action("steps.preview", { step_id: stepId, params });
            if (images[0]) results.push({ amount, image: images[0], label: `${field}: ${amount}`, signature: JSON.stringify(value) });
          }
          setVariants(results);
        } finally { setBusy(false); }
      })}>Compare three {field} choices</button>
      <div style={{ display: "flex", gap: 8 }}>{variants.filter((variant) => variant.signature === JSON.stringify(value)).map((variant) => <button type="button" key={variant.label}
        disabled={disabled} onClick={() => { change({ ...value, [field]: variant.amount }); setVariants([]); }}>
        <img src={`data:image/png;base64,${variant.image}`} alt={variant.label} style={{ width: 100 }} />
        {variant.label}
      </button>)}</div>
    </>}
  </section>;
}
