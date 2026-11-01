import { useState } from "react";
import { action, useCoreQuery } from "../data";
export function RecentChoices() {
  const { data: choices = [], error: loadError } = useCoreQuery("novelty.recent");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  return <div><h3>Recent visual choices</h3><p>The novelty selector in chat uses recently chosen images, styles, and layouts. Explicitly supplied images always take priority. This local history stores visual choices, not full conversations.</p>
    {(error || loadError) && <p role="alert">{error || loadError?.message}</p>}
    {notice && <p role="status">{notice}</p>}
    <ul>{choices.map((choice, i) => <li key={`${choice.kind}-${choice.value}-${i}`}><strong>{choice.kind}</strong>: {choice.label || choice.value}</li>)}</ul>
    {!choices.length && <p>Your recent choices will appear after you use images in a composition.</p>}
    <button onClick={() => { setError(""); void action("novelty.clear").then(() => setNotice("Prior-session history cleared. The current session remains available as context.")).catch(e => setError(String(e.message || e))); }}>Forget prior-session choices</button>
  </div>;
}
