import { useState } from "react";
import { action, useSession } from "../data";
import { useOperation } from "../useOperation";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";

export function CreationReplay() {
  const { data: session } = useSession();
  const [selected, setSelected] = useState<string[]>([]);
  const [delay, setDelay] = useState(600);
  const { busy, error, perform } = useOperation();
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const results = [...new Set(session?.steps.filter(s => s.status === "done").flatMap(s => s.outputs) ?? [])];
  const frames = results.filter(id => selected.includes(id));
  return <section aria-label="Creation replay"><p>Tell the story in 2–12 pictures. Select finished results; the GIF follows History order, fits every frame to the first picture, and loops. Source photos are never added automatically.</p>
    <fieldset disabled={disabled}><legend>Replay frames</legend><div className="retro-inputs">{results.map(id => <label key={id}>
      <input type="checkbox" aria-label={`Replay frame ${results.indexOf(id) + 1}`} checked={frames.includes(id)}
        disabled={!frames.includes(id) && frames.length >= 12} onChange={e => setSelected(e.target.checked ? [...frames, id] : frames.filter(a => a !== id))} /><ArtifactThumb id={id} />
    </label>)}</div></fieldset>
    <label>Milliseconds per frame<input type="number" min={100} max={2000} step={100} value={delay} onChange={e => setDelay(Number(e.target.value))} /></label>
    <button disabled={disabled || frames.length < 2 || delay < 100 || delay > 2000} onClick={() => void perform(async () => {
      const result = await action("tools.run", { tool: "animate", params: { images: frames, effect: "none", frames: frames.length, delay, hold: 0 } });
      if (result.status !== "done") throw new Error(result.error?.message ?? "Replay could not be made");
      useUI.getState().set({ selectedStep: result.id, selectedArtifact: result.outputs[0], notice: "Replay ready. Save the original image file to share its animation." });
    })}>Make creation replay GIF</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
