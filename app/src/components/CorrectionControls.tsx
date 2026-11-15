import { useEffect, useId, useRef, useState } from "react";
import { action, imageUrl, run, useArtifact, useCoreQuery, useSession } from "../data";
import type { Params } from "../types";
import { CutoutRepair } from "./CutoutRepair";
import { AnimationEditor } from "./AnimationEditor";
import { ImagePicker } from "./ImagePicker";
import { useUI } from "../store";

function LayoutSlotControls({ value, change, disabled, slotIndex, stepIndex, focusText }: {
  value: Params;
  change: (value: Params) => void;
  disabled: boolean;
  slotIndex: number;
  stepIndex: number;
  focusText?: number;
}) {
  const pictureId = useId();
  const caption = useRef<HTMLTextAreaElement>(null);
  const { data: tools } = useCoreQuery("tools.list");
  const schema = tools?.find(tool => tool.name === "layout")?.schema.properties as {
    title?: { maxLength?: number };
    captions?: { items?: { maxLength?: number } };
  } | undefined;
  useEffect(() => {
    if (focusText !== undefined) caption.current?.focus();
  }, [focusText]);
  const images = Array.isArray(value.images) ? value.images as string[] : [];
  const slots = Array.isArray(value.image_slots) ? value.image_slots as number[] : images.map((_, index) => index);
  const imageIndex = slots.indexOf(slotIndex);
  const captions = Array.isArray(value.captions) ? value.captions as string[] : [];
  const replace = (id: string | undefined) => {
    let nextImages = [...images];
    let nextSlots = [...slots];
    if (imageIndex >= 0 && id) nextImages[imageIndex] = id;
    else if (id) {
      nextImages.push(id);
      nextSlots.push(slotIndex);
    } else {
      nextImages = nextImages.filter((_, index) => index !== imageIndex);
      nextSlots = nextSlots.filter((_, index) => index !== imageIndex);
    }
    const hasExplicitSlots = Array.isArray(value.image_slots) || nextSlots.some((slot, index) => slot !== index);
    change({ ...value, images: nextImages, image_slots: hasExplicitSlots ? nextSlots : undefined });
  };
  return <section aria-label="Layout slot controls">
    <label>Headline<textarea disabled={disabled} maxLength={schema?.title?.maxLength}
      value={String(value.title ?? "")} onChange={event => change({ ...value, title: event.target.value })} /></label>
    <label>Caption<textarea ref={caption} disabled={disabled} maxLength={schema?.captions?.items?.maxLength}
      value={captions[slotIndex] ?? ""} onChange={event => {
        const next = Array.from({ length: Math.max(slotIndex + 1, captions.length) }, (_, index) => captions[index] ?? "");
        next[slotIndex] = event.target.value;
        change({ ...value, captions: next });
      }} /></label>
    <label htmlFor={pictureId}>Replace picture</label>
    <ImagePicker id={pictureId} disabled={disabled} value={images[imageIndex]} onChange={replace} beforeStepIndex={stepIndex} />
    <p>The layout fixes this slot’s position and size.</p>
  </section>;
}

export function CorrectionControls({ tool, stepId, value, change, disabled }: {
  tool: string; stepId?: string; value: Params; change: (value: Params, previewDelay?: number) => void; disabled: boolean;
}) {
  const reference = String(value.base ?? value.image ?? "");
  const { data } = useArtifact(reference || null);
  const { data: piece } = useArtifact(tool === "paste" && typeof value.piece === "string" ? value.piece : null);
  const selected = useUI(state => state.selectedElement?.stepId === stepId ? state.selectedElement : null);
  const { data: session } = useSession();
  const step = session?.steps.find(item => item.id === stepId);
  const caption = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (selected?.focusText !== undefined) caption.current?.focus();
  }, [selected?.focusText]);
  const drag = useRef<{ pointerId: number; resize: boolean; patch?: Params } | null>(null);
  const [dragPatch, setDragPatch] = useState<Params | null>(null);
  const [variants, setVariants] = useState<{ amount: number; image: string; label: string; signature: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const update = (patch: Params, previewDelay?: number) => { change({ ...value, ...patch }, previewDelay); setVariants([]); };
  const box = Array.isArray(value.fit_box) ? value.fit_box as number[] : null;
  const fittedScale = box && piece ? Math.max(Math.abs(box[2] - box[0]) / piece.meta.width,
    Math.abs(box[3] - box[1]) / piece.meta.height) * Number(value.scale ?? 1) : null;
  const width = fittedScale && piece ? Math.max(1, Math.round(piece.meta.width * fittedScale)) : Number(value.width ?? piece?.meta.width ?? 100);
  const height = fittedScale && piece ? Math.max(1, Math.round(piece.meta.height * fittedScale))
    : Number(value.height ?? (piece ? piece.meta.height * width / piece.meta.width : width));
  const recordedBox = tool === "text" && !value.tail && step?.params.image === value.image
    && Array.isArray(step?.data?.element_bounds) ? step.data.element_bounds as number[] : null;
  const recordedCenter = recordedBox?.length === 4 && recordedBox.every(Number.isFinite)
    ? [Math.floor((recordedBox[0] + recordedBox[2]) / 2), Math.floor((recordedBox[1] + recordedBox[3]) / 2)]
    : [0, 0];
  const at = box ? [Math.min(box[0], box[2]) + Math.floor(Math.abs(box[2] - box[0]) / 2),
    Math.min(box[1], box[3]) + Math.floor(Math.abs(box[3] - box[1]) / 2)]
    : Array.isArray(value.at) ? value.at as number[] : recordedCenter;
  const anchor = box ? "center" : String(value.anchor ?? "topleft");
  const placement = (position: number[]) => ({ at: position, fit_box: undefined,
    ...(tool === "paste" ? { width, height, anchor } : {}) });
  const guideAt = (dragPatch?.at as number[] | undefined) ?? at;
  const guideWidth = Number(dragPatch?.width ?? width);
  const guideHeight = drag.current?.resize && dragPatch && piece ? piece.meta.height * guideWidth / piece.meta.width : height;
  const endDrag = () => {
    drag.current = null;
    setDragPatch(null);
  };
  const canPlace = (tool === "paste" && !value.repeat) || tool === "text";
  const field = tool === "paste" ? "rotate" : tool === "text" ? "size" : "seed";
  const alternatives = field === "rotate" ? [-15, 0, 15] : field === "size" ? [24, 40, 64] : [1, 2, 3];
  const point = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [Math.round((event.clientX - rect.left) * (data?.meta.width ?? 1) / rect.width),
      Math.round((event.clientY - rect.top) * (data?.meta.height ?? 1) / rect.height)];
  };
  if (tool === "layout" && selected?.slotIndex !== undefined && step) {
    return <LayoutSlotControls value={value} change={change} disabled={disabled}
      slotIndex={selected.slotIndex} stepIndex={step.index} focusText={selected.focusText} />;
  }
  return <section aria-label="Quick corrections">
    {tool === "text" && <label>Font source<select disabled={disabled} value={value.font === "bundled" ? "bundled" : "local"}
      onChange={event => update({ font: event.target.value === "bundled" ? "bundled" : undefined })}>
      <option value="bundled">Portable bundled font (Latin-1)</option><option value="local">Style default / local font</option>
    </select><small>The bundled font replays without system fonts or downloads. Local font files must exist on the other machine.</small></label>}
    {tool === "animation_edit" && <AnimationEditor value={value} change={change} disabled={disabled} />}
    {tool === "cutout" && <CutoutRepair value={value} change={change} disabled={disabled} />}
    {tool === "text" && <label>Exact caption
      <textarea ref={caption} disabled={disabled} value={String(value.text ?? "")}
        onChange={(event) => update({ text: event.target.value })} />
      <button type="button" disabled={disabled} onClick={() => update({ size: undefined, fit_exact: true })}>Fit these words automatically</button>
    </label>}
    {canPlace && data && <>
      <p>Drag to move. Arrow keys nudge by one pixel, or ten with Shift. Escape cancels a drag.</p>
      {piece && !!Number(value.rotate) && <small>Set Rotation to zero to use the resize handle.</small>}
      <div role="group" aria-label="Placement controls" tabIndex={disabled ? -1 : 0}
        style={{ position: "relative", maxWidth: 400, touchAction: "none", cursor: "crosshair" }}
        onKeyDown={(event) => {
          if (event.key === "Escape" && drag.current) {
            event.preventDefault();
            event.stopPropagation();
            const pointerId = drag.current.pointerId;
            endDrag();
            if (event.currentTarget.hasPointerCapture(pointerId)) event.currentTarget.releasePointerCapture(pointerId);
            return;
          }
          if (disabled || drag.current || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
          event.preventDefault();
          const distance = event.shiftKey ? 10 : 1;
          update(placement([at[0] + (event.key === "ArrowLeft" ? -distance : event.key === "ArrowRight" ? distance : 0),
            at[1] + (event.key === "ArrowUp" ? -distance : event.key === "ArrowDown" ? distance : 0)]), 150);
        }}
        onPointerDown={(event) => {
          if (disabled || drag.current || event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.focus({ preventScroll: true });
          event.currentTarget.setPointerCapture(event.pointerId);
          const resize = (event.target as HTMLElement).dataset.resize === "true";
          const patch = resize ? undefined : placement(point(event));
          drag.current = { pointerId: event.pointerId, resize, patch };
          setDragPatch(patch ?? null);
        }}
        onPointerMove={(event) => {
          const gesture = drag.current;
          if (!gesture || gesture.pointerId !== event.pointerId || disabled) return;
          const position = point(event);
          gesture.patch = gesture.resize
            ? { width: Math.max(1, Math.min(1000, (position[0] - at[0]) * (anchor === "topleft" ? 1 : 2))),
                at, anchor, fit_box: undefined, height: undefined }
            : placement(position);
          setDragPatch(gesture.patch);
        }}
        onPointerUp={(event) => {
          const gesture = drag.current;
          if (!gesture || gesture.pointerId !== event.pointerId) return;
          if (!disabled && gesture.patch) update(gesture.patch);
          endDrag();
        }}
        onLostPointerCapture={(event) => { if (drag.current?.pointerId === event.pointerId) endDrag(); }}>
        <img src={imageUrl(data)} alt="Placement reference" draggable={false} style={{ width: "100%", display: "block" }} />
        {piece && !Number(value.rotate ?? 0) && <div style={{ position: "absolute", left: `${guideAt[0] / data.meta.width * 100}%`,
          top: `${guideAt[1] / data.meta.height * 100}%`, width: `${guideWidth / data.meta.width * 100}%`,
          height: `${guideHeight / data.meta.height * 100}%`, pointerEvents: "none",
          transform: anchor === "center" ? "translate(-50%, -50%)" : anchor === "bottom" ? "translate(-50%, -100%)" : undefined }}>
          <img src={imageUrl(piece)} alt="Replacement piece" draggable={false}
            style={{ width: "100%", height: "100%", display: "block", imageRendering: "pixelated",
              transform: `scaleX(${value.flip ? -1 : 1})` }} />
          <button type="button" data-resize="true" aria-label="Drag to resize piece" disabled={disabled}
            style={{ position: "absolute", right: 0, bottom: 0, pointerEvents: "auto", cursor: "nwse-resize" }}>↘</button>
        </div>}
        <span style={{ position: "absolute", left: `${guideAt[0] / data.meta.width * 100}%`,
          top: `${guideAt[1] / data.meta.height * 100}%`, color: "#ff00ff", transform: "translate(-50%, -50%)", pointerEvents: "none" }}>✛</span>
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
