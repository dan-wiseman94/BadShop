import { useState } from "react";
import { imageUrl, useArtifact, useSession } from "../data";
import type { Params } from "../types";

type Frame = { index: number; duration?: number | null };
function FrameThumb({ image, frame }: { image: string; frame: number }) {
  const { data } = useArtifact(image, true, true, frame);
  return <img src={imageUrl(data)} alt={`Source frame ${frame + 1}`} style={{ width: 72, height: 60, objectFit: "contain", imageRendering: "pixelated" }} />;
}

export function AnimationEditor({ value, change, disabled }: {
  value: Params; change: (value: Params) => void; disabled: boolean;
}) {
  const { data: session } = useSession();
  const image = typeof value.image === "string" ? value.image : "";
  const count = session?.artifacts[image]?.frames ?? 1;
  const meta = session?.artifacts[image];
  const frames: Frame[] = Array.isArray(value.frames) ? value.frames as Frame[] : Array.from({ length: Math.min(count, 200) }, (_, index) => ({ index }));
  const [selected, setSelected] = useState(0);
  const [start, setStart] = useState(1);
  const [end, setEnd] = useState(count);
  const active = Math.min(selected, frames.length - 1);
  const page = Math.floor(active / 12);
  const update = (next: Frame[]) => { change({ ...value, frames: next }); setSelected(Math.min(active, next.length - 1)); };
  const move = (offset: number) => {
    const next = [...frames];
    [next[active], next[active + offset]] = [next[active + offset], next[active]];
    update(next); setSelected(active + offset);
  };
  if (count > 200 || (meta && meta.width * meta.height * count > 20_000_000))
    return <p role="alert">This animation exceeds 200 frames or 20 million decoded pixels. Import a shorter or smaller clip first.</p>;
  return <fieldset disabled={disabled} aria-label="Animation frame editor">
    <legend>Animation frames</legend>
    <p>{frames.length} output frames. Duration blank keeps source timing. GIF timings use 10 ms increments. Captions below use output frame ranges, starting at zero.</p>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {frames.slice(page * 12, page * 12 + 12).map((frame, offset) => {
        const index = page * 12 + offset;
        return <button type="button" key={index} aria-label={`Select output frame ${index + 1}`} aria-pressed={active === index}
          onClick={() => setSelected(index)}><FrameThumb image={image} frame={frame.index} /><br />{index + 1} ← {frame.index + 1}</button>;
      })}
    </div>
    <button type="button" disabled={page === 0} onClick={() => setSelected((page - 1) * 12)}>Previous frames</button>
    <button type="button" disabled={(page + 1) * 12 >= frames.length} onClick={() => setSelected((page + 1) * 12)}>Next frames</button>
    <label>Selected frame duration (ms)<input type="number" min={10} max={10000} step={10}
      value={frames[active]?.duration ?? ""} placeholder="Source timing"
      onChange={event => update(frames.map((frame, index) => index === active
        ? { ...frame, duration: event.target.value ? event.target.valueAsNumber : null } : frame))} /></label>
    <button type="button" disabled={active <= 0} onClick={() => move(-1)}>Move frame earlier</button>
    <button type="button" disabled={active >= frames.length - 1} onClick={() => move(1)}>Move frame later</button>
    <button type="button" disabled={frames.length >= 200} onClick={() => update([...frames.slice(0, active + 1), { ...frames[active] }, ...frames.slice(active + 1)])}>Duplicate frame</button>
    <button type="button" disabled={frames.length <= 1} onClick={() => update(frames.filter((_, index) => index !== active))}>Delete frame</button>
    <button type="button" onClick={() => update(frames.map((frame, index) => index === active ? { ...frame, duration: 1000 } : frame))}>Hold frame for 1 second</button>
    <button type="button" onClick={() => update([...frames].reverse())}>Reverse frames</button>
    <button type="button" disabled={frames.length < 3 || frames.length * 2 - 2 > 200}
      onClick={() => update([...frames, ...frames.slice(1, -1).reverse()])}>Ping-pong frames</button>
    <label>Trim first output frame<input type="number" min={1} max={frames.length} value={start} onChange={event => setStart(event.target.valueAsNumber)} /></label>
    <label>Trim last output frame<input type="number" min={start} max={frames.length} value={end} onChange={event => setEnd(event.target.valueAsNumber)} /></label>
    <button type="button" disabled={!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end > frames.length || end < start}
      onClick={() => { update(frames.slice(start - 1, end)); setStart(1); setEnd(end - start + 1); }}>Trim to range</button>
    <button type="button" onClick={() => { change({ ...value, frames: undefined, crop: undefined, captions: [], speed: 1, loop: undefined }); setSelected(0); setStart(1); setEnd(count); }}>Reset animation edits</button>
  </fieldset>;
}
