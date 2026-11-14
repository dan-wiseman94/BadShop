import { useLibraryPage } from '../libraryPage';
import { Button } from "./Button";
import { ManualTools } from "./ManualTools";
import { ThemeIcon } from "./ThemeIcon";
import { useEffect, useRef, useState } from "react";
import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import { Grid2X2, ScanFace, ChevronDown, MousePointer2, Undo2, Redo2 } from "lucide-react";
import { action, imageUrl, useArtifact, useSession, run } from "../data";
import { LibraryImage } from "./LibraryImage";
import { useOperation } from "../useOperation";
import { outputSelection, useCanvasArtifact, useUI } from "../store";
import { useStream } from '../stream';
import { useReducedMotion } from "../appearance";
import { openLink } from "../native";
import { CopyImage, ShareImage } from "./ShareImage";
import type { Artifact, Params } from "../types";
import { recordedElements } from "../recordedElements";
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
export function Viewer({ onImport }: { onImport: () => void }) {
  const { data: session } = useSession();
  const { visibleArtifacts } = useDocumentProjection(session);
  const [materialSearch, setMaterialSearch] = useState("");
  const { entries: library, controls: libraryPages } = useLibraryPage(materialSearch);
  const { busy: materialBusy, error: materialError, perform: materialAction } = useOperation();
  const selectedStep = useUI((s) => s.selectedStep);
  const { id: canvasId, inputId } = useCanvasArtifact(session);
  const pick = useUI((s) => s.pick);
  const [grid, setGrid] = useState(false);
  const [boxes, setBoxes] = useState(false);
  const [selectElements, setSelectElements] = useState(false);
  const before = useUI((state) => state.viewerBefore);
  const setBefore = (viewerBefore: boolean) => useUI.getState().set({ viewerBefore });
  const [sharing, setSharing] = useState(false);
  const shareDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (sharing) shareDialog.current?.showModal();
    else shareDialog.current?.close();
  }, [sharing]);
  const zoom = useUI((state) => state.viewerZoom);
  const setZoom = (viewerZoom: "fit" | number) => useUI.getState().set({ viewerZoom });
  const [size, setSize] = useState({ width: 600, height: 500 });
  const stage = useRef<HTMLDivElement>(null);
  const origin = useRef<number[] | null>(null);
  const [selection, setSelection] = useState<number[] | null>(null);
  const [cursor, setCursor] = useState<number[] | null>(null);
  const id = pick?.artifactId ?? canvasId;
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
  const elements = recordedElements(session, id);
  const selectElement = (stepId: string) => {
    const output = session?.steps.slice().reverse().find(step => step.outputs.includes(id ?? ""));
    useUI.getState().set({ selectedStep: stepId, selectedArtifact: output
      ? outputSelection(output, id!) : id });
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
    setSelection(null);
  }, [selectedStep]);
  const scale = meta
    ? pick || zoom === "fit"
      ? Math.max(0.001, Math.min(Math.max(1, size.width - 24) / meta.width, Math.max(1, size.height - 24) / meta.height, 1))
      : zoom
    : 1;
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
    <section className="viewer pane" data-picking={!!pick} aria-label="Image viewer">
      <div className="pane-heading">
        <span className="flex items-center gap-2">
          <ThemeIcon name="canvas" size={16} />
          Canvas
        </span>
        <span className="muted">{meta ? `${meta.width} × ${meta.height}` : "No image selected"}</span>
      </div>
      {(meta || session?.manual_history?.undo || session?.manual_history?.redo) && <div className="viewer-tools">
        <button aria-label="Select elements" title="Select elements" aria-pressed={selectElements} disabled={!elements.length || !!pick}
          onClick={() => setSelectElements(!selectElements)}><MousePointer2 size={16} /></button>
        <button aria-label="Undo" disabled={!session?.manual_history?.undo || session.turn_running || !!session.pending_approvals.length}
          title={session?.manual_history?.undo ? `Undo ${session.manual_history.undo}` : "No manual change to undo"}
          onClick={() => run(() => action("history.undo", { expected_revision: session?.document_revision }))}><Undo2 size={16} /></button>
        <button aria-label="Redo" disabled={!session?.manual_history?.redo || session.turn_running || !!session.pending_approvals.length}
          title={session?.manual_history?.redo ? `Redo ${session.manual_history.redo}` : "No manual change to redo"}
          onClick={() => run(() => action("history.redo", { expected_revision: session?.document_revision }))}><Redo2 size={16} /></button>
        {id && <CopyImage id={id} frame={paused ? frame : 0} animated={(meta?.frames ?? 1) > 1} />}
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
      <div className={`viewer-stage ${pick ? "picking" : ""}`} ref={stage}>
        {meta ? (
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
            }}
            onPointerLeave={() => setCursor(null)}
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
            {selectElements && !pick && elements.map((element, index) => {
              const [left, top, right, bottom] = element.box;
              const x = Math.max(0, left), y = Math.max(0, top);
              const width = Math.min(meta.width, right) - x, height = Math.min(meta.height, bottom) - y;
              return width > 0 && height > 0 && <button key={`${element.step.id}-${index}`}
                className="recorded-element" aria-label={`Edit ${element.label}`} title={`Edit ${element.label}`}
                aria-pressed={selectedStep === element.step.id}
                style={{ left: x * scale, top: y * scale, width: width * scale, height: height * scale }}
                onClick={() => selectElement(element.step.id)} />;
            })}
            {(grid || boxes || selection) && (
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
      {selectElements && !!elements.length && <label>Recorded elements (including overlaps)
        <select aria-label="Recorded element" value={elements.some(element => element.step.id === selectedStep) ? selectedStep! : ""}
          onChange={event => { if (event.target.value) selectElement(event.target.value); }}>
          <option value="">Choose an element</option>
          {elements.map((element, index) => <option key={`${element.step.id}-${index}`} value={element.step.id}>{element.label}</option>)}
        </select>
        <small>Outlines show recorded bounds. Cropped or transformed results can be edited from their timeline steps.</small>
      </label>}
      {id && <ManualTools key={id} image={id} />}
      {id && <div role="group" aria-label="Selected material actions" className="manual-tools">
        {["subject", "background", "prop"].map(role => <button key={role} disabled={materialBusy || session?.turn_running}
          onClick={() => void materialAction(async () => {
            await action("creative.set", { values: { source_roles: { ...session?.creative?.source_roles, [role]: id } } });
            useUI.getState().set({ notice: `Selected picture is your ${role}.` });
          })}>Use as {role}</button>)}
        <button onClick={() => setSharing(true)}>Finish this image</button>
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
          if (!id) return;
          setSharing(true);
        }}
      >
        <div className="strip-title">
          Materials <ChevronDown size={12} />
        </div>
        <label>Find material<input value={materialSearch} onChange={e => setMaterialSearch(e.target.value)} placeholder="Picture or character name" /></label>
        <button type="button" onClick={onImport}>Add material</button>
        <MaterialGallery artifacts={visibleArtifacts.filter(a => a.label.toLowerCase().includes(materialSearch.toLowerCase()))} />
        {id && (
          <button type="submit" title="Export image">
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
      <dialog ref={shareDialog} className="share-dialog" aria-label="Export image" onClose={() => setSharing(false)}>
        <button onClick={() => setSharing(false)} aria-label="Close export">Close</button>
        {sharing && id && <ShareImage key={id} id={id} />}
      </dialog>
    </section>
  );
}
