import { Button } from "./Button";
import { InputField, SelectField } from "./Fields";
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
  const update = (values: Record<string, unknown>) => run(() => action("settings.set", { values }));
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
      <InputField
        label="New sticker animation frame delay (ms)"
        type="number"
        min={20}
        max={2000}
        defaultValue={session?.creative?.animation_delay ?? 100}
        onBlur={(e) => {
          if (e.target.validity.valid)
            run(() => action("creative.set", { values: { animation_delay: Number(e.target.value) } }));
        }}
      />
      <label>
        <input
          type="checkbox"
          checked={settings.no_remote ?? false}
          onChange={(e) => update({ no_remote: e.target.checked })}
        />{" "}
        Local only (block downloads and cloud providers)
      </label>
      <p className="muted">
        Imported pixels and local tools remain available. Local chat requires a provider at localhost,
        127.0.0.1 or ::1. This setting controls BadShop network calls; external CLI tools are disabled in this
        mode.
      </p>
      <label>
        <input
          type="checkbox"
          checked={settings.remember_history ?? true}
          onChange={(e) => update({ remember_history: e.target.checked })}
        />{" "}
        Remember creative history
      </label>
      <Button onClick={() => run(() => action("novelty.clear"))} label="Clear creative history" />
      <SelectField
        label="Discovery rights filter"
        value={settings.rights_filter ?? "any"}
        onChange={(e) => update({ rights_filter: e.target.value })}
        options={[
          ["any", "All (including unknown rights)"] as const,
          ["known", "Has rights metadata"] as const,
          ["public-domain", "Public domain / CC0"] as const,
        ]}
      />
      <SelectField
        label="Discovery orientation"
        value={settings.source_orientation ?? "any"}
        onChange={(e) => update({ source_orientation: e.target.value })}
        options={["any", "landscape", "portrait", "square"]}
      />
      <p>
        Search sources (no selections means every configured source). This controls discovery searches; use
        Local only to block all remote requests.
      </p>
      <div className="retro-controls">
        <Button
          onClick={() =>
            update({
              source_allowlist: ["commons", "met", "chicago", "cleveland", "smithsonian"],
              rights_filter: "public-domain",
            })
          }
          label="Museum profile"
        />
        <Button
          onClick={() =>
            update({
              source_allowlist: ["commons", "openmoji"],
              rights_filter: "known",
            })
          }
          label="Icons & clip art profile"
        />
        <Button
          onClick={() =>
            update({
              source_allowlist: ["openverse", "pexels", "pixabay", "brave"],
              rights_filter: "any",
            })
          }
          label="Photos & web profile"
        />
        <Button
          onClick={() => update({ source_allowlist: [], rights_filter: "any" })}
          label="All configured sources"
        />
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
                  : (settings.source_allowlist?.filter((v) => v !== s.id) ?? []),
              })
            }
          />
          {s.name}
          {!s.configured && ` — set ${s.env_var}`}
        </label>
      ))}
      <h3>Source credentials</h3>
      <p>
        Saved keys use your OS keychain. Environment variables take precedence. Keys never enter projects or
        asset packs.
      </p>
      <SelectField
        label="Source key"
        bind={[source, setSource]}
        options={sources.filter((s) => s.requires_key).map((s) => [s.id, s.name] as const)}
      />
      <InputField label="API key" type="password" autoComplete="off" bind={[key, setKey]} />
      <Button
        disabled={!key}
        onClick={() =>
          run(async () => {
            await action("sources.key", { source, api_key: key });
            setKey("");
            setNotice("Saved to the OS keychain.");
          })
        }
        label="Save source key"
      />
      <Button
        onClick={() =>
          run(async () => {
            await action("sources.key", { source, api_key: "" });
            setKey("");
            setNotice("Saved key removed. Environment variables still apply.");
          })
        }
        label="Remove saved key"
      />
      {notice && <p role="status">{notice}</p>}
      <h3>Disposable source cache</h3>
      <p>
        {cache
          ? `${(cache.bytes / 1048576).toFixed(1)} MiB in ${cache.files} entries · ${cache.budget_mb} MiB maximum`
          : "Loading cache usage"}
      </p>
      <Button
        onClick={() =>
          run(async () => {
            await action("cache.clear");
            await refreshCache();
          })
        }
        label="Clear source previews"
      />
      <p className="muted">
        Clears cached search metadata. Imported images, projects, models and the junk drawer stay available.
      </p>
    </details>
  );
}
