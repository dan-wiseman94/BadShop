import { useState } from "react";
import { action, useSession } from "../data";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";
import type { Params } from "../types";

type Pair = { donor: string; background: string; score: number; reasons: string[]; paste_params: Params };
export function ImagePairs({ onAttach }: { onAttach: (id: string) => void }) {
  const { data: session } = useSession();
  const [donors, setDonors] = useState<string[]>([]);
  const [backgrounds, setBackgrounds] = useState<string[]>([]);
  const [role, setRole] = useState("subject");
  const [side, setSide] = useState("center");
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [sheet, setSheet] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ready = useUI(s => s.status === "ready");
  const disabled = busy || !ready || !!session?.turn_running;
  const images = Object.values(session?.artifacts ?? {});
  async function work(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return <div>
    <p>Compare subject/background combinations before committing. Use prepared cutouts as donors for a hard-edged composite. Scores measure framing and fit; inspect expressions and the joke yourself.</p>
    {error && <p role="alert" className="error-banner">{error}</p>}
    <div className="studio-form">
      <label>Donor images (up to six)<select multiple size={6} value={donors} onChange={e => setDonors(Array.from(e.target.selectedOptions, o => o.value).slice(0, 6))}>{images.map(im => <option key={im.id} value={im.id}>{im.label}</option>)}</select></label>
      <label>Background images (up to six)<select multiple size={6} value={backgrounds} onChange={e => setBackgrounds(Array.from(e.target.selectedOptions, o => o.value).slice(0, 6))}>{images.map(im => <option key={im.id} value={im.id}>{im.label}</option>)}</select></label>
      <label>Role<select value={role} onChange={e => setRole(e.target.value)}><option value="subject">Subject</option><option value="head">Head swap</option><option value="object">Object / prop</option></select></label>
      <label>Placement<select value={side} onChange={e => setSide(e.target.value)}><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></label>
      <button disabled={disabled || !donors.length || !backgrounds.length} onClick={() => void work(async () => {
        const step = await action("tools.run", { tool: "pair_images", params: { donors, backgrounds, role, side, n: 6 } });
        if (step.status !== "done") throw new Error(step.error?.message ?? "Could not compare image pairs.");
        setPairs((step.data?.pairs ?? []) as Pair[]); setSheet(step.outputs[0] ?? null);
      })}>{busy ? "Working…" : "Compare image pairs"}</button>
    </div>
    {sheet && <div className="studio-sheet"><ArtifactThumb id={sheet} label="Image pair contact sheet" /></div>}
    <div className="studio-grid">{pairs.map((pair, i) => <article className="studio-card" key={`${pair.donor}-${pair.background}`}>
      <strong>Pair {i + 1}</strong><span>{session?.artifacts[pair.donor]?.label} + {session?.artifacts[pair.background]?.label}</span><small>{pair.reasons.join(" · ")}</small>
      <button disabled={disabled} onClick={() => void work(async () => { const step = await action("tools.run", { tool: "paste", params: pair.paste_params });
        if (step.status !== "done" || !step.outputs[0]) throw new Error(step.error?.message ?? "Could not compose this pair.");
        onAttach(step.outputs[0]); useUI.getState().set({ selectedArtifact: step.outputs[0], notice: "Pair composed as an editable paste step" });
      })}>Compose this pair</button>
    </article>)}</div>
  </div>;
}
