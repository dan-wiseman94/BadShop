import { useState } from "react";
import { action, useSession } from "../data";
import { useOperation } from "../useOperation";
import { useUI } from "../store";
import { IdeaPreview } from "./IdeaPreview";
import { ArtifactThumb } from "./Viewer";
import type { Recipe } from "../types";

const collections = {
  "Worst workplace": { title: "Employee of the uncertainty", captions: ["This could have been an email.", "Circling back indefinitely.", "Promoted to meeting attendee.", "Per my previous panic.", "Available after my nap.", "Let's take this offline. Forever."] },
  "Extremely local news": { title: "Breaking: absolutely nothing", captions: ["Local witness refuses to elaborate.", "Experts confirm: probably fine.", "Area resident has had enough.", "Situation downgraded to mildly awkward.", "More on this after snacks.", "Historic event postponed until Monday."] },
  "Petty victories": { title: "Achievement unlocked", captions: ["Answered one email.", "Found the good spoon.", "Remembered why I entered the room.", "Declined an unnecessary meeting.", "Made it to the couch.", "Survived another group chat."] },
};
const formats = ["trading-card", "tabloid-cover", "achievement"];

export function CreativeCollections({ image, title, caption, disabled: blocked }: { image: string; title: string; caption: string; disabled: boolean }) {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [collection, setCollection] = useState<keyof typeof collections>("Worst workplace");
  const [keepWords, setKeepWords] = useState(false);
  const [reaction, setReaction] = useState(false);
  const [completed, setCompleted] = useState<string[]>([]);
  const { busy, error, notice, setNotice, perform } = useOperation();
  const disabled = blocked || busy || !!session?.turn_running || !!session?.batch_running;
  const theme = collections[collection];
  const drafts = Array.from({ length: reaction ? 6 : 3 }, (_, index) => ({
    template: reaction ? "desktop-error" : formats[index],
    title: keepWords ? title : theme.title,
    caption: keepWords ? caption : theme.captions[index],
  }));
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Make a scene: surprises &amp; reaction sets</summary>
    <p>One character, one world. Preview the alternatives, then make ordinary editable results. Choose a picture above first.</p>
    <label>Comedy collection<select disabled={disabled} value={collection} onChange={e => setCollection(e.target.value as keyof typeof collections)}>
      {Object.keys(collections).map(name => <option key={name}>{name}</option>)}</select></label>
    <label><input type="checkbox" disabled={disabled} checked={reaction} onChange={e => setReaction(e.target.checked)} /> Make six reactions for the group chat</label>
    <label><input type="checkbox" disabled={disabled || (!title && !caption)} checked={keepWords} onChange={e => setKeepWords(e.target.checked)} /> Keep my current headline and punchline exactly</label>
    <div className="quick-cards">{drafts.map((draft, i) => <article key={i}>
      {image && open && <IdeaPreview image={image} template={draft.template} title={draft.title} captions={[draft.caption]} slots={1}
        revision={session?.document_revision ?? 0} enabled={!disabled} />}
      <strong>{draft.title}</strong><p>{draft.caption}</p>
    </article>)}</div>
    <button disabled={disabled || !image} onClick={() => void perform(async () => {
      const recipe: Recipe = { version: 1, name: collection, steps: drafts.map(draft => ({ tool: "layout", params: {
        template: draft.template, images: ["$input"], title: draft.title, captions: [draft.caption],
      } })) };
      const result = await action("recipes.run", { recipe, inputs: [image] });
      setCompleted(result.completed);
      setNotice(`${result.completed.length} editable results${result.cancelled ? " · stopped" : ""}. ${result.errors.map(e => e.message).join("; ")}`);
    })}>{reaction ? "Make my reaction set" : "Make three alternate takes"}</button>
    <button disabled={!busy && !session?.batch_running} onClick={() => void action("recipes.stop").catch(e => setNotice(String(e)))}>Stop making the set</button>
    <div className="quick-cards">{completed.map(id => {
      const step = session?.steps.find(s => s.id === id);
      return step?.outputs[0] && <article key={id}>
        <ArtifactThumb id={step.outputs[0]} label="Edit or share this take" onClick={() => useUI.getState().set({ selectedStep: id, selectedArtifact: step.outputs[0] })} />
      </article>;
    })}</div>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </details>;
}
