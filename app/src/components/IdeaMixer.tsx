import { useState } from "react";
import { useCoreQuery } from "../data";
import {
  emptyLocks,
  eraChoices,
  jokeChoices,
  mixIdeas,
  settingChoices,
} from "../ideaMixer";
import type { MixedIdea, MixerLocks } from "../ideaMixer";
import "../ideaMixer.css";

export function IdeaMixer({
  onDraft,
  onSearch,
}: {
  onDraft: (text: string) => void;
  onSearch: (query: string) => void;
}) {
  const { data: formats = [], error } = useCoreQuery("layouts.list");
  const [subject, setSubject] = useState("");
  const [locks, setLocks] = useState<MixerLocks>({ ...emptyLocks });
  const [seed, setSeed] = useState(
    () => crypto.getRandomValues(new Uint32Array(1))[0],
  );
  const [ideas, setIdeas] = useState<MixedIdea[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  const [repeated, setRepeated] = useState(false);
  const [total, setTotal] = useState(0);
  const groups = [
    { key: "joke", label: "Joke", choices: jokeChoices },
    { key: "setting", label: "Setting", choices: settingChoices },
    { key: "era", label: "Era", choices: eraChoices },
    { key: "format", label: "Format", choices: formats },
  ] as const;
  return (
    <div className="idea-mixer">
      <p>
        Choose a subject, lock any choices you like, and mix up to six different
        briefs. Adding a brief to chat keeps it editable before you send it.
      </p>
      {error && (
        <p role="alert" className="error-banner">
          Could not load formats. Reconnect to the core and try again.
        </p>
      )}
      <form
        className="studio-form"
        onSubmit={(event) => {
          event.preventDefault();
          const batch = mixIdeas(subject, locks, formats, seed, recent);
          setIdeas(batch.ideas);
          setTotal(batch.total);
          setRepeated(batch.repeated);
          setRecent((previous) =>
            [...previous, ...batch.ideas.map((idea) => idea.key)].slice(-48),
          );
          setSeed((previous) => (previous + 1) >>> 0);
        }}
      >
        <label className="wide">
          Idea subject
          <input
            value={subject}
            maxLength={300}
            placeholder="My cat, the world's least qualified manager"
            onChange={(event) => setSubject(event.target.value)}
          />
        </label>
        {groups.map((group) => (
          <label key={group.key}>
            {group.label}
            <select
              aria-label={`Lock ${group.label.toLowerCase()}`}
              value={locks[group.key]}
              onChange={(event) =>
                setLocks((previous) => ({
                  ...previous,
                  [group.key]: event.target.value,
                }))
              }
            >
              <option value="">Any — mix this choice</option>
              {group.choices.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.name}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button disabled={!formats.length}>
          {ideas.length ? "Mix six more ideas" : "Mix six ideas"}
        </button>
        <button type="button" onClick={() => setLocks({ ...emptyLocks })}>
          Unlock all choices
        </button>
      </form>
      {ideas.length > 0 && (
        <p role="status">
          {ideas.length} {ideas.length === 1 ? "brief" : "briefs"} from{" "}
          {total.toLocaleString()} possible{" "}
          {total === 1 ? "combination" : "combinations"}.{" "}
          {repeated
            ? "You've seen every combination with these locks; unlock a choice for more variety."
            : "Recent combinations are skipped while this mixer stays open."}
        </p>
      )}
      <div className="studio-grid idea-cards">
        {ideas.map((idea, index) => (
          <article className="studio-card" key={idea.key}>
            <strong>
              {index + 1}. {idea.joke.name}
            </strong>
            <span>{idea.subject}</span>
            <small>
              {idea.format.name} · {idea.setting.name} · {idea.era.name}
            </small>
            <p>
              {idea.joke.direction} {idea.setting.direction}
            </p>
            <details>
              <summary>Read the full brief</summary>
              <pre>{idea.prompt}</pre>
            </details>
            <div className="studio-row">
              <button onClick={() => onDraft(idea.prompt)}>
                Add brief to chat
              </button>
              <button onClick={() => onSearch(idea.search)}>
                Prepare a source search
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
