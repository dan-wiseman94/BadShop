import { action, run, useCoreQuery, useSession } from "../data";
import { useState } from "react";
export function SourceSettings() {
  const { data: session } = useSession();
  const [source, setSource] = useState("flickr");
  const [key, setKey] = useState("");
  const [notice, setNotice] = useState("");
  const { data: settings } = useCoreQuery("settings.get");
  const { data: sources = [] } = useCoreQuery("sources.status");
  const { data: cache, refetch: refreshCache } = useCoreQuery("cache.status");
  if (!settings) return null;
  const update = (values: Record<string, unknown>) =>
    run(() => action("settings.set", { values }));
  return (
    <details>
      <summary>Sources, privacy and creative history</summary>
      <label>
        <input
          type="checkbox"
          checked={session?.creative?.remember_history ?? true}
          onChange={(e) =>
            run(() =>
              action("creative.set", {
                values: { remember_history: e.target.checked },
              }),
            )
          }
        />{" "}
        Remember this project's creative history
      </label>
      <label>
        New sticker animation frame delay (ms)
        <input
          type="number"
          min={20}
          max={2000}
          defaultValue={session?.creative?.animation_delay ?? 100}
          onBlur={(e) => {
            if (e.target.validity.valid)
              run(() =>
                action("creative.set", {
                  values: { animation_delay: Number(e.target.value) },
                }),
              );
          }}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={settings.no_remote ?? false}
          onChange={(e) => update({ no_remote: e.target.checked })}
        />{" "}
        Local only (block downloads and cloud providers)
      </label>
      <p className="muted">
        Imported pixels and local tools remain available. Local chat requires a
        provider at localhost, 127.0.0.1 or ::1. This setting controls BadShop
        network calls; external CLI tools are disabled in this mode.
      </p>
      <label>
        <input
          type="checkbox"
          checked={settings.remember_history ?? true}
          onChange={(e) => update({ remember_history: e.target.checked })}
        />{" "}
        Remember creative history
      </label>
      <button onClick={() => run(() => action("novelty.clear"))}>
        Clear creative history
      </button>
      <label>
        Discovery rights filter
        <select
          value={settings.rights_filter ?? "any"}
          onChange={(e) => update({ rights_filter: e.target.value })}
        >
          <option value="any">All (including unknown rights)</option>
          <option value="known">Has rights metadata</option>
          <option value="public-domain">Public domain / CC0</option>
        </select>
      </label>
      <label>
        Discovery orientation
        <select
          value={settings.source_orientation ?? "any"}
          onChange={(e) => update({ source_orientation: e.target.value })}
        >
          {["any", "landscape", "portrait", "square"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </label>
      <p>
        Search sources (no selections means every configured source). This
        controls discovery searches; use Local only to block all remote
        requests.
      </p>
      <div className="retro-controls">
        <button
          onClick={() =>
            update({
              source_allowlist: [
                "commons",
                "met",
                "chicago",
                "cleveland",
                "smithsonian",
              ],
              rights_filter: "public-domain",
            })
          }
        >
          Museum profile
        </button>
        <button
          onClick={() =>
            update({
              source_allowlist: ["commons", "openmoji"],
              rights_filter: "known",
            })
          }
        >
          Icons & clip art profile
        </button>
        <button
          onClick={() =>
            update({
              source_allowlist: ["openverse", "pexels", "pixabay", "brave"],
              rights_filter: "any",
            })
          }
        >
          Photos & web profile
        </button>
        <button
          onClick={() => update({ source_allowlist: [], rights_filter: "any" })}
        >
          All configured sources
        </button>
      </div>
      {sources.map((s) => (
        <label key={s.id}>
          <input
            type="checkbox"
            checked={settings.source_allowlist?.includes(s.id) ?? false}
            onChange={(e) =>
              update({
                source_allowlist: e.target.checked
                  ? [...(settings.source_allowlist ?? []), s.id]
                  : (settings.source_allowlist?.filter((v) => v !== s.id) ??
                    []),
              })
            }
          />
          {s.name}
          {!s.configured && ` — set ${s.env_var}`}
        </label>
      ))}
      <h3>Source credentials</h3>
      <p>
        Saved keys use your OS keychain. Environment variables take precedence.
        Keys never enter projects or asset packs.
      </p>
      <label>
        Source key
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          {sources
            .filter((s) => s.requires_key)
            .map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        API key
        <input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>
      <button
        disabled={!key}
        onClick={() =>
          run(async () => {
            await action("sources.key", { source, api_key: key });
            setKey("");
            setNotice("Saved to the OS keychain.");
          })
        }
      >
        Save source key
      </button>
      <button
        onClick={() =>
          run(async () => {
            await action("sources.key", { source, api_key: "" });
            setKey("");
            setNotice("Saved key removed. Environment variables still apply.");
          })
        }
      >
        Remove saved key
      </button>
      {notice && <p role="status">{notice}</p>}
      <h3>Disposable source cache</h3>
      <p>
        {cache
          ? `${(cache.bytes / 1048576).toFixed(1)} MiB in ${cache.files} entries · ${cache.budget_mb} MiB maximum`
          : "Loading cache usage"}
      </p>
      <button
        onClick={() =>
          run(async () => {
            await action("cache.clear");
            await refreshCache();
          })
        }
      >
        Clear source previews
      </button>
      <p className="muted">
        Clears cached search metadata. Imported images, projects, models and the
        junk drawer stay available.
      </p>
    </details>
  );
}
