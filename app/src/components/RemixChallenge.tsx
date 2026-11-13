import { useState } from "react";
import { action, useCoreQuery, useSession } from "../data";
import { useOperation } from "../useOperation";
import { ArtifactThumb } from "./Viewer";

const prompts = ["Make the world's least useful superhero", "Turn a tiny problem into breaking news", "Invent an award nobody wants", "Give this character a disastrous day job"];
const prefix = "Challenge start: ";

export function RemixChallenge() {
  const { data: session } = useSession();
  const { data } = useCoreQuery("branches.list");
  const [prompt, setPrompt] = useState(prompts[0]);
  const [base, setBase] = useState("");
  const [player, setPlayer] = useState("");
  const [reveal, setReveal] = useState(false);
  const { busy, error, perform } = useOperation();
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const starts = data?.branches.filter(b => b.name.startsWith(prefix)) ?? [];
  const active = data?.branches.find(b => b.id === data.active_id);
  const currentStart = starts.find(b => b.id === active?.id || active?.name.startsWith(`Round ${b.id} · `));
  const baseId = base || currentStart?.id || starts.at(-1)?.id || "";
  const roundPrefix = `Round ${baseId} · `;
  const rounds = data?.branches.filter(b => b.name.startsWith(roundPrefix)) ?? [];
  return <section aria-label="Remix challenge"><p>Pass one computer around. Everyone starts from the same saved scene, makes their own take, then reveals it together. Save the project to keep every round.</p>
    <label>Challenge prompt<input maxLength={100} disabled={disabled} value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
    <button disabled={disabled} onClick={() => setPrompt(prompts[(prompts.indexOf(prompt) + 1) % prompts.length])}>Another challenge prompt</button>
    <button disabled={disabled || !prompt.trim()} onClick={() => void perform(async () => {
      await action("branches.create", { name: prefix + prompt.trim(), expected_revision: session!.document_revision });
    })}>Keep this scene as a challenge start</button>
    {!!starts.length && <>
      <label>Saved challenge<select value={baseId} disabled={disabled} onChange={e => { setBase(e.target.value); setReveal(false); }}>
        {starts.map(b => <option key={b.id} value={b.id}>{b.name.slice(prefix.length)}</option>)}</select></label>
      <label>Player or round name<input maxLength={50} value={player} disabled={disabled} onChange={e => setPlayer(e.target.value)} /></label>
      <button disabled={disabled || !player.trim() || rounds.length >= 8} onClick={() => void perform(async () => {
        const start = await action("branches.switch", { id: baseId, expected_revision: session!.document_revision });
        await action("branches.create", { name: roundPrefix + player.trim(), expected_revision: start.document_revision });
      })}>Start this player's round</button>
      <p>Up to eight rounds per challenge. Edit normally in Quick ideas or All tools. Switching rounds keeps completed work.</p>
      <button disabled={disabled} onClick={() => setReveal(!reveal)}>{reveal ? "Hide the reveal" : "Reveal the takes"}</button>
      {reveal && <div className="quick-cards">{rounds.map(round => <article key={round.id}>
        {round.preview_id && <ArtifactThumb id={round.preview_id} />}<strong>{round.name.slice(roundPrefix.length)}</strong>
        <button disabled={disabled || round.id === data?.active_id} onClick={() => void perform(async () => {
          await action("branches.switch", { id: round.id, expected_revision: session!.document_revision });
        })}>Continue this take</button>
        <button disabled={disabled || round.name.endsWith(" ★")} onClick={() => void perform(async () => {
          await action("branches.rename", { id: round.id, name: round.name + " ★" });
        })}>Give this take a star</button>
      </article>)}</div>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
