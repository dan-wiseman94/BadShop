import { useLibraryPage } from '../libraryPage';
import { Button } from "./Button";
import { ThemeIcon } from "./ThemeIcon";
import { useContext, useEffect, useRef, useState } from "react";
import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import { Grid2X2, ScanFace, ChevronDown, MousePointer2, Undo2, Redo2 } from "lucide-react";
import { action, imageUrl, queries, useArtifact, useCoreQuery, useSession, run } from "../data";
import { LibraryImage } from "./LibraryImage";
import { useOperation } from "../useOperation";
import { outputSelection, useCanvasArtifact, useUI, type SelectedElement } from "../store";
import { useStream } from '../stream';
import { useReducedMotion } from "../appearance";
import { openLink } from "../native";
import { Cast } from "./Cast";
import { CopyImage, ShareImage } from "./ShareImage";
import type { Artifact, Params, Session } from "../types";
import { directionLabel } from "../directions";
import { recordedElements } from "../recordedElements";
import { CanvasPlacementContext, type CanvasPlacement } from "../canvasPlacement";
import { useDocumentProjection } from '../documentProjection';
export function ArtifactThumb({ id, onClick, label }: { id: string; onClick?: () => void; label?: string }) {
  const { data } = useArtifact(id, true);
  return (
    <button type="button" className="artifact-thumb" onClick={onClick} title={label ?? data?.meta.label}
      draggable onDragStart={event => event.dataTransfer.setData("application/x-badshop-artifact", id)}>
      <img src={imageUrl(data)} alt={label ?? data?.meta.label ?? "Image"} />
    </button>
  );
}
function MaterialGallery({ artifacts }: { artifacts: Artifact[] }) {
  const scroll = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(0);
  const focusPending = useRef(false);
  const windowed = artifacts.length > 100;
  const virtual = useVirtualizer({ count: artifacts.length, horizontal: true,
    getScrollElement: () => scroll.current, estimateSize: () => 55, overscan: 4,
    getItemKey: index => artifacts[index].id, enabled: windowed,
    rangeExtractor: range => [...new Set([...defaultRangeExtractor(range), Math.min(focused, artifacts.length - 1)])]
      .filter(index => index >= 0).sort((a, b) => a - b),
  });
  const rows = windowed ? virtual.getVirtualItems() : artifacts.map((artifact, index) => ({ key: artifact.id, index, start: 0 }));
  useEffect(() => {
    if (focusPending.current) {
      scroll.current?.querySelector<HTMLButtonElement>(`[data-material-index="${focused}"] button`)?.focus({ preventScroll: true });
      focusPending.current = false;
    }
  }, [focused, rows]);
  return <div className="artifact-list" ref={scroll} aria-label="Project materials" onKeyDown={event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !artifacts.length) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? artifacts.length - 1
      : Math.max(0, Math.min(artifacts.length - 1, focused + (event.key === 'ArrowRight' ? 1 : -1)));
    focusPending.current = true;
    setFocused(next);
    if (windowed) virtual.scrollToIndex(next, { align: 'auto' });
  }}>
    <div style={windowed ? { position: 'relative', width: virtual.getTotalSize(), height: 55, flexShrink: 0 }
      : { display: 'flex', gap: 7 }}>
      {rows.map(row => { const artifact = artifacts[row.index]; return <div key={artifact.id}
        data-material-index={row.index} onFocus={() => setFocused(row.index)}
        style={windowed ? { position: 'absolute', left: row.start, top: 0 } : undefined}>
        <ArtifactThumb id={artifact.id} label={`${artifact.label} (${row.index + 1} of ${artifacts.length})`}
          onClick={() => useUI.getState().set({ selectedArtifact: artifact.id, selectedStep: artifact.produced_by ?? null })} />
      </div>; })}
    </div>
    {!artifacts.length && <span className="muted text-xs">No matching materials.</span>}
  </div>;
}
function faceBoxes(data: Params | null | undefined): number[][] {
  if (!data) return [];
  const faces = data.faces;
  if (!Array.isArray(faces)) return [];
  return faces.flatMap((face) => {
    if (!face || typeof face !== "object") return [];
    const value = (face as Params).head ?? (face as Params).box;
    return Array.isArray(value) && value.length === 4 ? [value as number[]] : [];
  });
}
type ViewerProps = {
  onImport: () => void;
  onSelectElement?: (select: () => void, element: SelectedElement | null) => void;
  onOpenHistory?: () => void;
};

type PlacementDrag = {
  pointer: HTMLButtonElement;
  pointerId: number;
  x: number;
  y: number;
  scale: number;
  context: NonNullable<Session["context"]>;
  generation: number;
  elementId: string;
  placement: CanvasPlacement;
};

export function Viewer({ onImport, onSelectElement, onOpenHistory }: ViewerProps) {
  const { data: session } = useSession();
  const { visibleArtifacts } = useDocumentProjection(session);
  const [materialSearch, setMaterialSearch] = useState("");
  const { entries: library, controls: libraryPages } = useLibraryPage(materialSearch);
  const { busy: materialBusy, error: materialError, perform: materialAction } = useOperation();
  const selectedStep = useUI((s) => s.selectedStep);
  const selectedElement = useUI((s) => s.selectedElement);
  const { id: canvasId, inputId, kind, producer, outputKey } = useCanvasArtifact(session);
  const { data: takes } = useCoreQuery("branches.list");
  const take = directionLabel(takes?.branches.find(branch => branch.id === takes.active_id)?.name ?? "Original");
  const pick = useUI((s) => s.pick);
  const [grid, setGrid] = useState(false);
  const [boxes, setBoxes] = useState(false);
  const [selectElements, setSelectElements] = useState(true);
  const before = useUI((state) => state.viewerBefore);
  const setBefore = (viewerBefore: boolean) => useUI.getState().set({ viewerBefore });
  const [shareTarget, setShareTarget] = useState<{ id: string; label: string; frame: number } | null>(null);
  const [castOpen, setCastOpen] = useState(false);
  const [confirmedSaved, confirmSaved] = useState<{ id: string; revision: number } | null>(null);
  const shareDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (shareTarget) shareDialog.current?.showModal();
    else shareDialog.current?.close();
  }, [shareTarget]);
  const zoom = useUI((state) => state.viewerZoom);
  const setZoom = (viewerZoom: "fit" | number) => useUI.getState().set({ viewerZoom });
  const [size, setSize] = useState({ width: 600, height: 500 });
  const stage = useRef<HTMLDivElement>(null);
  const origin = useRef<number[] | null>(null);
  const ignoreSurfaceClick = useRef(false);
  const [selection, setSelection] = useState<number[] | null>(null);
  const placementOwner = useContext(CanvasPlacementContext);
  const placementDrag = useRef<PlacementDrag | null>(null);
  const [placementGuide, setPlacementGuide] = useState<[number, number] | null>(null);
  const generation = useUI(state => state.documentGeneration);
  const [cursor, setCursor] = useState<number[] | null>(null);
  const id = pick?.artifactId ?? canvasId;
  const currentDraft = useUI(state => state.canvasDraft);
  const draft = !pick && currentDraft?.revision === session?.document_revision ? currentDraft : null;
  const confirmed = confirmedSaved?.id === id && confirmedSaved?.revision === session?.document_revision;
  const canShare = !!id && !pick && !draft && kind !== "missing" && (kind !== "last_saved" || confirmed);
  const canvasLabel = draft ? `Draft preview · ${draft.scope === "final" ? "Includes later steps" : "This step only"}`
    : kind === "before" ? `Before step ${selectedStep ? session?.steps.find(step => step.id === selectedStep)?.index : ""}`
    : kind === "missing" ? "This output is no longer available"
    : kind === "last_saved" ? "Last successful image · Changes not fully applied"
    : kind === "final" ? `Final result · ${take}`
    : kind === "earlier" ? `Step ${producer?.index} output`
    : kind === "source" ? "Source picture" : "";
  const outputLabel = outputKey && Object.keys(producer?.output_ports ?? {}).length > 1 ? ` · ${outputKey}` : "";
  const openShare = () => { if (id && canShare) setShareTarget({ id, label: canvasLabel + outputLabel, frame: paused ? frame : 0 }); };

  const motion = useUI((s) => s.motion);
  const reduced = useReducedMotion(motion);
  const [playing, setPlaying] = useState<boolean | null>(null);
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    setPlaying(null);
    setFrame(0);
  }, [id, reduced]);
  const paused = playing === null ? reduced : !playing;
  const { data, error } = useArtifact(id, false, paused, frame);
  const meta = data?.meta;
  const elements = draft ? [] : recordedElements(session, canvasId);
  const selected = elements.find(element => element.id === selectedElement?.id);
  const selectElement = (elementId: string, focusText?: number) => {
    const element = elements.find(item => item.id === elementId);
    const next = element ? {
      id: element.id, stepId: element.step.id, label: element.label, slotIndex: element.slotIndex, focusText,
    } : null;
    const output = session?.steps.slice().reverse().find(step => step.outputs.includes(canvasId ?? ""));
    const selectedArtifact = output ? outputSelection(output, canvasId!) : canvasId;
    const generation = useUI.getState().documentGeneration;
    const select = () => {
      const ui = useUI.getState();
      const active = queries.getQueryData<Session>(["session.get"]);
      if (ui.documentGeneration === generation && !ui.pick && active?.context?.branch_id === session?.context?.branch_id)
        ui.set({ selectedElement: next, selectedStep: next?.stepId ?? null, selectedArtifact });
    };
    if (onSelectElement) onSelectElement(select, next);
    else select();
  };
  const clearSelection = () => {
    if (!pick && !ignoreSurfaceClick.current && selected) selectElement("");
  };
  const progress = useStream(state => state.text);
  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setSize({ width: rect.width, height: rect.height });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    origin.current = null;
    setSelection(null);
  }, [pick]);
  const scale = meta
    ? pick || zoom === "fit"
      ? Math.max(0.001, Math.min(Math.max(1, size.width - 24) / meta.width, Math.max(1, size.height - 24) / meta.height, 1))
      : zoom
    : 1;
  const cancelPlacement = () => {
    const drag = placementDrag.current;
    if (!drag) return;
    placementDrag.current = null;
    ignoreSurfaceClick.current = true;
    setPlacementGuide(null);
    if (drag.pointer.hasPointerCapture(drag.pointerId))
      drag.pointer.releasePointerCapture(drag.pointerId);
  };
  useEffect(cancelPlacement, [canvasId, generation, pick, scale, selectElements, selected?.id,
    session?.context?.branch_id, session?.context?.document_incarnation, session?.document_revision]);

  const beginPlacement = (event: React.PointerEvent<HTMLButtonElement>) => {
    const placement = placementOwner?.current;
    if (event.button !== 0 || placementDrag.current || !session?.context || pick ||
        (kind !== "final" && kind !== "earlier") || selected?.step.id !== placement?.stepId || !placement || !selected) return;
    const pointer = event.currentTarget;
    pointer.focus({ preventScroll: true });
    pointer.setPointerCapture(event.pointerId);
    placementDrag.current = {
      pointer, pointerId: event.pointerId, x: event.clientX, y: event.clientY, scale,
      context: session.context, generation, elementId: selected.id, placement,
    };
  };
  const placementOffset = (event: React.PointerEvent, drag: PlacementDrag): [number, number] =>
    [Math.round((event.clientX - drag.x) / drag.scale), Math.round((event.clientY - drag.y) / drag.scale)];
  const finishPlacement = (event: React.PointerEvent) => {
    const drag = placementDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const [x, y] = placementOffset(event, drag);
    if (!x && !y && !ignoreSurfaceClick.current) {
      placementDrag.current = null;
      return;
    }
    cancelPlacement();

    const ui = useUI.getState();
    const current = queries.getQueryData<Session>(["session.get"])?.context;
    const owner = placementOwner?.current;
    if (!current || ui.pick || ui.viewerBefore || ui.documentGeneration !== drag.generation ||
        ui.selectedElement?.id !== drag.elementId || ui.selectedStep !== drag.placement.stepId ||
        current.core_instance_id !== drag.context.core_instance_id || current.document_id !== drag.context.document_id ||
        current.document_incarnation !== drag.context.document_incarnation || current.branch_id !== drag.context.branch_id ||
        current.revision !== drag.context.revision || owner?.stepId !== drag.placement.stepId ||
        owner.draft !== drag.placement.draft) return;
    if (x || y) owner.moveBy(x, y);
  };
  const point = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!meta) return [0, 0];
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(meta.width, Math.round((event.clientX - rect.left) / scale))),
      Math.max(0, Math.min(meta.height, Math.round((event.clientY - rect.top) / scale))),
    ];
  };
  const detected =
    session?.steps
      .filter(
        (step) => step.tool === "find" && step.status === "done" && Object.values(step.params).includes(id),
      )
      .flatMap((step) => faceBoxes(step.data)) ?? [];
  return (
    <section className="viewer pane window" data-picking={!!pick} aria-label="Image viewer">
      <div className="pane-heading title-bar">
        <span className="flex items-center gap-2">
          <ThemeIcon name="canvas" size={16} />
          Canvas
        </span>
        <span className="muted">{meta ? `${meta.width} × ${meta.height}` : "No image selected"}</span>
      </div>
      {canvasLabel && !pick && <div className="canvas-view-state">
        <span>{canvasLabel}{!draft && outputLabel}</span>
        {draft && <button onClick={() => useUI.getState().set({ canvasDraft: null })}>Return to saved image</button>}
        {!draft && ["before", "earlier", "missing", "source"].includes(kind) && !!session?.steps.some(step => step.outputs.length) &&
          <button onClick={() => useUI.getState().set({ selectedStep: null, selectedArtifact: null })}>Return to final result</button>}
        {kind === "last_saved" && !confirmed && canvasId && session && <button onClick={() =>
          confirmSaved({ id: canvasId, revision: session.document_revision })}>Choose this saved image</button>}
        {producer && kind !== "before" && Object.keys(producer.output_ports ?? {}).length > 1 &&
          <label>Output <select value={outputKey ?? ""} onChange={event => useUI.getState().set({
            selectedArtifact: { invocationId: producer.invocation_id!, outputKey: event.target.value },
          })}>
            {Object.keys(producer.output_ports ?? {}).map(key => <option key={key} value={key}>{key}</option>)}
          </select></label>}
      </div>}
      {(meta || session?.manual_history?.undo || session?.manual_history?.redo) && <div className="viewer-tools">
        <button aria-label="Select elements" title="Select elements" aria-pressed={selectElements && !!elements.length && !pick} disabled={!elements.length || !!pick}
          onClick={() => setSelectElements(!selectElements)}><MousePointer2 size={16} /></button>
        <button aria-label="Undo" disabled={!session?.manual_history?.undo || session.turn_running || !!session.pending_approvals.length}
          title={session?.manual_history?.undo ? `Undo ${session.manual_history.undo}` : "No manual change to undo"}
          onClick={() => run(() => action("history.undo", { expected_revision: session?.document_revision }))}><Undo2 size={16} /></button>
        <button aria-label="Redo" disabled={!session?.manual_history?.redo || session.turn_running || !!session.pending_approvals.length}
          title={session?.manual_history?.redo ? `Redo ${session.manual_history.redo}` : "No manual change to redo"}
          onClick={() => run(() => action("history.redo", { expected_revision: session?.document_revision }))}><Redo2 size={16} /></button>
        {canShare && kind !== "before" && id && <CopyImage id={id} frame={paused ? frame : 0} animated={(meta?.frames ?? 1) > 1} />}
        {meta && <div className="segmented">
          <Button
            disabled={!inputId}
            aria-pressed={before}
            className={before ? "active" : ""}
            onClick={() => setBefore(true)}
            label="Before"
          />
          <Button aria-pressed={!before} className={!before ? "active" : ""} onClick={() => setBefore(false)} label="After" />
        </div>}
        {meta && <div className="viewer-toggles">
          {(meta?.frames ?? 1) > 1 && (
            <>
              <Button onClick={() => setPlaying(paused)} label={paused ? "Play preview" : "Pause preview"} />
              <button
                disabled={!paused}
                onClick={() => {
                  setPlaying(false);
                  setFrame((frame + 1) % Math.min(meta?.frames ?? 1, 1001));
                }}
              >
                Next frame ({frame + 1})
              </button>
            </>
          )}
          <button
            title="Coordinate grid"
            aria-label="Coordinate grid"
            aria-pressed={grid}
            onClick={() => setGrid(!grid)}
          >
            <Grid2X2 size={16} />
          </button>
          <button
            title="Face boxes"
            aria-label="Face boxes"
            aria-pressed={boxes}
            onClick={() => setBoxes(!boxes)}
          >
            <ScanFace size={17} />
          </button>
          <select
            aria-label="Zoom"
            value={zoom}
            onChange={(event) => setZoom(event.target.value === "fit" ? "fit" : Number(event.target.value))}
          >
            <option value="fit">Fit</option>
            <option value="0.5">50%</option>
            <option value="1">100%</option>
            <option value="2">200%</option>
            <option value="4">400%</option>
          </select>
        </div>}
      </div>}
      <div className={`viewer-stage ${pick ? "picking" : ""}`} ref={stage}
        onPointerDownCapture={() => { ignoreSurfaceClick.current = !!pick; }}
        onClick={event => { if (event.target === event.currentTarget) clearSelection(); }}>
        {draft ? <img className="canvas-draft-image" alt="Draft preview on canvas" src={draft.source} /> : meta ? (
          <div
            className="image-surface"
            style={{
              width: meta.width * scale,
              height: meta.height * scale,
              minWidth: meta.width * scale,
              minHeight: meta.height * scale,
            }}
            onPointerMove={(event) => {
              const p = point(event);
              setCursor(p);
              if (origin.current && pick && pick.kind !== "point") setSelection([...origin.current, ...p]);
              const drag = placementDrag.current;
              if (drag?.pointerId === event.pointerId) {
                const offset = placementOffset(event, drag);
                if (offset[0] || offset[1]) ignoreSurfaceClick.current = true;
                if (ignoreSurfaceClick.current) setPlacementGuide(offset);
              }
            }}
            onPointerLeave={() => setCursor(null)}
            onClick={clearSelection}
            onKeyDown={event => {
              if (event.key !== "Escape" || !placementDrag.current) return;
              event.preventDefault();
              event.stopPropagation();
              cancelPlacement();
            }}
            onPointerCancel={event => {
              if (placementDrag.current?.pointerId === event.pointerId) cancelPlacement();
              origin.current = null;
              setSelection(null);
            }}
            onLostPointerCapture={event => {
              if (placementDrag.current?.pointerId === event.pointerId) cancelPlacement();
            }}
            onPointerDown={(event) => {
              if (!pick) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              origin.current = point(event);
              if (pick.kind === "point") {
                pick.complete(origin.current);
                useUI.getState().set({ pick: null });
                origin.current = null;
              }
            }}
            onPointerUp={(event) => {
              finishPlacement(event);
              if (!pick || pick.kind === "point" || !origin.current) return;
              const end = point(event);
              const start = origin.current;
              pick.complete(
                pick.kind === "segment"
                  ? [...start, ...end]
                  : [
                      Math.min(start[0], end[0]),
                      Math.min(start[1], end[1]),
                      Math.max(start[0], end[0]),
                      Math.max(start[1], end[1]),
                    ],
              );
              origin.current = null;
              setSelection(null);
              useUI.getState().set({ pick: null });
            }}
          >
            <img className="canvas-image" src={imageUrl(data)} alt={meta.label} draggable={false} />
            {selectElements && !pick && elements.flatMap(element => {
              const hitAreas = [{ box: element.box, caption: element.step.tool === "text", label: element.label }];
              if (element.captionBox) hitAreas.push({
                box: element.captionBox, caption: true, label: `Caption for ${element.label}`,
              });
              return hitAreas.map(({ box, caption, label }) => {
                const [left, top, right, bottom] = box;
                const x = Math.max(0, left), y = Math.max(0, top);
                const width = Math.min(meta.width, right) - x, height = Math.min(meta.height, bottom) - y;
                return width > 0 && height > 0 && <button key={`${element.id}-${caption ? "caption" : "picture"}`}
                  type="button" className="recorded-element" aria-label={`Edit ${label}`} title={`Edit ${label}`}
                  aria-pressed={selected?.id === element.id}
                  tabIndex={-1}
                  style={{ left: x * scale, top: y * scale, width: width * scale, height: height * scale }}
                  onPointerDown={selected?.id === element.id && element.step.tool === "paste" ? beginPlacement : undefined}
                  onClick={event => {
                    event.stopPropagation();
                    if (!ignoreSurfaceClick.current && event.detail < 2) selectElement(element.id);
                  }}
                  onDoubleClick={caption ? event => selectElement(element.id, event.timeStamp) : undefined} />;
              });
            })}
            {(grid || boxes || selection || placementGuide) && (
              <svg className="image-overlay" viewBox={`0 0 ${meta.width} ${meta.height}`} aria-hidden="true">
                {grid && (
                  <>
                    {Array.from({ length: Math.floor(meta.width / 50) }, (_, i) => (
                      <g key={`x${i}`}>
                        <line x1={(i + 1) * 50} y1="0" x2={(i + 1) * 50} y2={meta.height} />
                        <text x={(i + 1) * 50 + 3} y="14">
                          {(i + 1) * 50}
                        </text>
                      </g>
                    ))}
                    {Array.from({ length: Math.floor(meta.height / 50) }, (_, i) => (
                      <g key={`y${i}`}>
                        <line x1="0" y1={(i + 1) * 50} x2={meta.width} y2={(i + 1) * 50} />
                        <text x="4" y={(i + 1) * 50 - 4}>
                          {(i + 1) * 50}
                        </text>
                      </g>
                    ))}
                  </>
                )}
                {boxes &&
                  detected.map((box, i) => (
                    <rect
                      className="face-box"
                      key={i}
                      x={box[0]}
                      y={box[1]}
                      width={box[2] - box[0]}
                      height={box[3] - box[1]}
                    />
                  ))}
                {placementGuide && selected && (
                  <rect className="selection-box canvas-placement-guide"
                    x={selected.box[0] + placementGuide[0]} y={selected.box[1] + placementGuide[1]}
                    width={selected.box[2] - selected.box[0]} height={selected.box[3] - selected.box[1]} />
                )}
                {selection && (
                  <rect
                    className="selection-box"
                    x={Math.min(selection[0], selection[2])}
                    y={Math.min(selection[1], selection[3])}
                    width={Math.abs(selection[2] - selection[0])}
                    height={Math.abs(selection[3] - selection[1])}
                  />
                )}
              </svg>
            )}
          </div>
        ) : (
          <div className="empty-stage">
            <div className="cut-paper">
              <ThemeIcon name="images" size={32} />
              <span>
                Your next terrible idea
                <br />
                goes here.
              </span>
            </div>
            <Button className="primary" onClick={onImport} label="Add images" icon="images" iconSize={16} />
            <p>Drop or paste an image to start.</p>
            {error && <p className="error-text">{error.message}</p>}
          </div>
        )}
      </div>
      {elements.length > 0 && <label>Elements in this image
        <select disabled={!!pick} value={selected?.id ?? ""} onChange={event => selectElement(event.target.value)}>
          <option value="">Choose an element</option>
          {elements.map(element => <option key={element.id} value={element.id}>{element.label}</option>)}
        </select>
      </label>}
      {meta && !pick && !elements.length && <p className="muted">
        This image has no selectable recorded elements. {onOpenHistory
          ? <><button type="button" onClick={onOpenHistory}>Open History</button> to edit its steps.</>
          : "Open History to edit its steps."}
      </p>}
      {canShare && id && <details className="manual-tools" onToggle={event => setCastOpen(event.currentTarget.open)}>
        <summary>Save character</summary>
        {castOpen && <Cast key={id} image={id} disabled={!!session?.turn_running} onUse={artifact =>
          useUI.getState().set({ selectedArtifact: artifact, selectedStep: null })} />}
      </details>}
      {id && <div role="group" aria-label="Selected material actions" className="manual-tools">
        {["subject", "background", "prop"].map(role => <button key={role} disabled={materialBusy || session?.turn_running}
          onClick={() => void materialAction(async () => {
            await action("creative.set", { values: { source_roles: { ...session?.creative?.source_roles, [role]: id } } });
            useUI.getState().set({ notice: `Selected picture is your ${role}.` });
          })}>Use as {role}</button>)}
        <button onClick={openShare} disabled={!canShare}>Share image</button>
        {meta?.original_id && (session?.artifacts[meta.original_id]?.frames ?? 1) > 1 &&
          <button onClick={() => useUI.getState().set({ selectedArtifact: meta.original_id! })}>Use animated original</button>}
      </div>}
      {!!session?.steps.some((step) => session.bypass_tools?.includes(step.tool)) &&
        <details className="manual-tools"><summary>Applied effects</summary>
          {session.steps.filter((step) => session.bypass_tools?.includes(step.tool)).map((step) =>
            <div key={step.id} className="manual-turn-controls">
              <button onClick={() => useUI.getState().set({ selectedStep: step.id,
                selectedArtifact: outputSelection(step) })}>
                {step.index}. {step.tool} {String(step.params.level ?? step.params.names ?? step.params.size ?? "")}
              </button>
              <label><input type="checkbox" checked={!step.bypassed} disabled={session.turn_running}
                onChange={(event) => run(() => action("steps.controls", { step_id: step.id, bypassed: !event.target.checked }))} />Enabled</label>
            </div>)}
        </details>}
      {pick && (
        <div className="pick-hint" role="status">
          <div>
            {pick.label && <strong>{pick.label}</strong>}
            <span>
              {pick.kind === "box"
                ? "Drag a box on the image"
                : pick.kind === "segment"
                  ? "Drag from the start to the end of the line"
                  : "Click a point on the image"}
            </span>
          </div>
          <Button onClick={() => useUI.getState().set({ pick: null })} label="Cancel" />
        </div>
      )}
      <div className="viewer-foot">
        <span>
          {cursor
            ? `x ${cursor[0]}  y ${cursor[1]}`
            : (meta?.label ?? "Working copies stay at 1000 px or smaller")}
        </span>
        <span>
          {meta
            ? `${meta.format} / ${Math.round(scale * 100)}%`
            : session?.turn_running
              ? progress
                ? "Agent is thinking…"
                : "Agent is working…"
              : "Hard edges. Questionable decisions."}
        </span>
      </div>
      {meta?.source && (
        <div className="source-bar">
          <span>
            {meta.source.creator ?? meta.source.kind} / {meta.source.license ?? "License not provided"}
          </span>
          {(meta.source.page || meta.source.url) && (
            <Button
              onClick={() => run(() => openLink(meta.source!.page ?? meta.source!.url!))}
              label="View source"
            />
          )}
        </div>
      )}
      <form
        id="export-canvas-image"
        className="artifact-strip"
        onSubmit={(event) => {
          event.preventDefault();
          openShare();
        }}
      >
        <div className="strip-title">
          Materials <ChevronDown size={12} />
        </div>
        <label>Find material<input value={materialSearch} onChange={e => setMaterialSearch(e.target.value)} placeholder="Picture or character name" /></label>
        <button type="button" onClick={onImport}>Add material</button>
        <MaterialGallery artifacts={visibleArtifacts.filter(a => a.label.toLowerCase().includes(materialSearch.toLowerCase()))} />
        {id && (
          <button type="submit" title="Export image" disabled={!canShare}>
            <ThemeIcon name="export" size={16} />
          </button>
        )}
      </form>
      <details className="material-library"><summary>Saved characters &amp; materials</summary>
        {libraryPages}
        <div className="artifact-list">
          {library.filter(entry => `${entry.name} ${entry.tags.join(" ")}`.toLowerCase().includes(materialSearch.toLowerCase())).map(entry =>
            <button type="button" key={entry.id} aria-label={entry.name} disabled={materialBusy || session?.turn_running}
              onClick={() => void materialAction(async () => {
                const generation = useUI.getState().documentGeneration;
                const result = await action("library.import", { id: entry.id });
                if (generation === useUI.getState().documentGeneration)
                  useUI.getState().set({ selectedArtifact: result.working.id, selectedStep: null });
              })}><LibraryImage entry={entry} /><span>{entry.name}</span></button>)}
        </div>
        {!library.length && <p>Save characters in Cast or pictures in the Junk drawer to reuse them here.</p>}
      </details>
      {materialError && <p role="alert">{materialError}</p>}
      <dialog ref={shareDialog} className="share-dialog" aria-label="Export image" onClose={() => setShareTarget(null)}>
        <button onClick={() => setShareTarget(null)} aria-label="Close export">Close</button>
        {shareTarget && <ShareImage key={shareTarget.id} {...shareTarget} />}
      </dialog>
    </section>
  );
}
