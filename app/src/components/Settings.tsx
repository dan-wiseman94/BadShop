import { Button } from "./Button";
import { ThemeIcon } from "./ThemeIcon";
import { InputField, SelectField } from "./Fields";
import { useEffect, useState } from "react";
import {
  Plus,
  Trash2,
  Check,
  Download,
  RefreshCw,
  Terminal,
  KeyRound,
  Monitor,
  Globe,
  ArrowRight,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { action, queries, run, useCoreQuery, useSession } from "../data";
import type { DownloadActivities } from "../data";
import { useUI } from "../store";
import { themes, savePreference, type Density, type Motion } from "../appearance";
import { pickFolder } from "../native";
import { ErrorNotice } from "./ErrorNotice";
import { SourceSettings } from "./SourceSettings";
import { UpdateSettings, type useUpdates } from "../updates";
import { BIREFNET_MEMORY_NOTE, ON_DEVICE } from "../constants";
import type {
  Asset,
  CLIDetection,
  Params,
  Profile,
  Settings as SettingsType,
} from "../types";
const kindNames = {
  api: "Cloud API",
  local: "Local model",
  openai_compatible: "Custom endpoint",
  cli: "CLI subscription",
};
const kindHints = {
  api: "Connect with an API key from your model provider.",
  local: "Use a vision model running on your own computer.",
  openai_compatible: "Connect any OpenAI-compatible model server.",
  cli: "Use your existing Claude, Codex, or Gemini login.",
};
const icons = {
  api: KeyRound,
  local: Monitor,
  openai_compatible: Globe,
  cli: Terminal,
};
export function ProfileEditor({
  initial,
  kind,
  onSaved,
}: {
  initial?: Profile;
  kind?: Profile["kind"];
  onSaved: (profile: Profile) => void | Promise<void>;
}) {
  const [profile, setProfile] = useState<Partial<Profile>>(
    initial ?? {
      kind: kind ?? "api",
      label: "",
      model: "",
      capability_overrides: {},
    },
  );
  const [key, setKey] = useState("");
  const [keyMode, setKeyMode] = useState(initial?.api_key_env ? "environment" : "keychain");
  const [busy, setBusy] = useState(false);
  const [cliStatus, setCLIStatus] = useState("");
  const update = (patch: Partial<Profile>) => setProfile({ ...profile, ...patch });
  const isCLI = profile.kind === "cli";
  return (
    <form
      className="profile-editor"
      onSubmit={(event) => {
        event.preventDefault();
        run(async () => {
          setBusy(true);
          try {
            const value = {
              ...profile,
              ...(isCLI ? { cli: profile.cli ?? "claude", model: profile.model ?? "" } : {}),
              ...(keyMode === "environment" ? { api_key_env: profile.api_key_env } : {}),
            };
            if (isCLI) {
              delete value.api_base;
              delete value.api_key_env;
              delete value.api_key_ref;
              value.capability_overrides = {};
            } else {
              delete value.cli;
              delete value.executable;
            }
            if (keyMode === "keychain") delete value.api_key_env;
            const saved = await action("providers.save", {
              profile: value,
              ...(!isCLI && keyMode === "keychain" && key ? { api_key: key } : {}),
            });
            setKey("");
            setProfile(saved);
            await onSaved(saved);
          } finally {
            setBusy(false);
          }
        });
      }}
    >
      <SelectField
        label="Provider type"
        value={profile.kind}
        onChange={(event) => update({ kind: event.target.value as Profile["kind"] })}
        options={Object.entries(kindNames).map(([value, label]) => [value, label] as const)}
      />
      <p className="muted">{kindHints[profile.kind ?? "api"]}</p>
      <InputField
        label="Profile name"
        required
        value={profile.label ?? ""}
        placeholder="My art director"
        onChange={(e) => update({ label: e.target.value })}
      />
      {isCLI ? (
        <>
          <SelectField
            label="Command line tool"
            value={profile.cli ?? "claude"}
            onChange={(e) => update({ cli: e.target.value as Profile["cli"] })}
            options={[
              ["claude", "Claude Code"] as const,
              ["codex", "Codex"] as const,
              ["gemini", "Gemini CLI (experimental)"] as const,
            ]}
          />
          <Button
            type="button"
            onClick={() =>
              run(async () => {
                const detected = await action("providers.detect");
                const cli = detected.find((item) => item.cli === (profile.cli ?? "claude"));
                if (cli?.available && cli.supported) {
                  update({ executable: cli.executable });
                  setCLIStatus(cli.version ?? "CLI detected");
                } else setCLIStatus(cli?.error ?? "CLI not found. Install it or enter its path below.");
              })
            }
            label="Detect installed CLI"
            icon={Terminal}
            iconSize={14}
          />
          {cliStatus && <p className="field-description">{cliStatus}</p>}
          <InputField
            label="Executable path (optional)"
            value={profile.executable ?? ""}
            placeholder="Auto-detect from PATH"
            onChange={(e) => update({ executable: e.target.value || null })}
          />
          <InputField
            label="Model (optional)"
            value={profile.model ?? ""}
            placeholder="Use the CLI’s default model"
            onChange={(e) => update({ model: e.target.value })}
          />
          <p className="field-description">
            Sign in using the CLI in your terminal first. badshop supplies the tools and asks for approvals
            here.
          </p>
        </>
      ) : (
        <>
          <InputField
            label="Model"
            required
            value={profile.model ?? ""}
            placeholder={profile.kind === "local" ? "ollama_chat/llava" : "openai/gpt-4.1"}
            onChange={(e) => update({ model: e.target.value })}
          />
          <label>
            API base URL {profile.kind === "api" ? "(optional)" : ""}
            <input
              type="url"
              required={profile.kind === "openai_compatible"}
              value={profile.api_base ?? ""}
              placeholder={profile.kind === "local" ? "http://localhost:11434" : "https://api.example.com/v1"}
              onChange={(e) => update({ api_base: e.target.value || null, allow_insecure_http: false })}
            />
          </label>
          {profile.api_base?.startsWith("http://") && !/^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:\/|$)/i.test(profile.api_base) &&
            <label className="checkbox-row"><input type="checkbox" checked={profile.allow_insecure_http ?? false}
              onChange={e => update({ allow_insecure_http: e.target.checked })} />
              Allow unencrypted HTTP for this address. Images, prompts and credentials may be visible to others on the network.
            </label>}
          <SelectField
            label="Credential storage"
            bind={[keyMode, setKeyMode]}
            options={[["keychain", "OS keychain"] as const, ["environment", "Environment variable"] as const]}
          />
          {keyMode === "keychain" ? (
            <label>
              API key{" "}
              {initial?.api_key_ref ? "(leave blank to keep saved key)" : "(optional for local models)"}
              <input
                type="password"
                autoComplete="new-password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Stored in your system keychain"
              />
            </label>
          ) : (
            <InputField
              label="Environment variable name"
              required
              pattern="[A-Za-z_][A-Za-z0-9_]*"
              placeholder="OPENAI_API_KEY"
              value={profile.api_key_env ?? ""}
              onChange={(e) => update({ api_key_env: e.target.value })}
            />
          )}
          <p className="field-description">
            If your keychain is locked or unavailable, unlock it or use an environment variable. Keys never
            enter saved sessions.
          </p>
          {profile.capability_overrides?.tool_calls === false && (
            <p className="field-description">
              This model will use the weaker JSON fallback for tools. Results may be poor.
            </p>
          )}
          <fieldset className="capabilities">
            <legend>Model capabilities</legend>
            {[
              ["vision", "Supports images"],
              ["tool_calls", "Supports tool calls"],
            ].map(([name, label]) => (
              <label key={name}>
                {label}
                <select
                  value={
                    profile.capability_overrides?.[name] === undefined
                      ? "auto"
                      : String(profile.capability_overrides[name])
                  }
                  onChange={(event) => {
                    const next = { ...profile.capability_overrides };
                    if (event.target.value === "auto") delete next[name];
                    else next[name] = event.target.value === "true";
                    update({ capability_overrides: next });
                  }}
                >
                  <option value="auto">Detect automatically</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </label>
            ))}
          </fieldset>
        </>
      )}
      <Button className="primary" type="submit" disabled={busy} label={busy ? "Saving…" : "Save provider"} />
    </form>
  );
}
export function AssetRow({ asset, active = false }: { asset: Asset; active?: boolean }) {
  const { data: downloads } = useQuery<DownloadActivities>({
    queryKey: ["downloads"],
    queryFn: () => ({}),
    enabled: false,
  });
  const manuallyCancellable = active || (downloads?.[asset.name]?.pending ?? 0) > 0;
  const error = downloads?.[asset.name]?.error;
  const { data: progress } = useQuery<Params>({
    queryKey: ["progress", asset.name],
    queryFn: () => ({}),
    enabled: false,
  });
  const busy = manuallyCancellable || Boolean(progress?.active);
  const { data: session } = useSession();
  return (
    <div className="asset-row">
      <div>
        <strong>{asset.label}</strong>
        <span>{asset.present ? "Downloaded" : `About ${asset.approx_mb} MB`}</span>
        {asset.name.includes("birefnet") && <span className="model-memory-note">{BIREFNET_MEMORY_NOTE}</span>}
        {busy && (
          <progress max={Number(progress?.total) || undefined} value={Number(progress?.done) || undefined} />
        )}{" "}
        {error && <span className="error-text">{error}</span>}
      </div>
      {asset.present ? (
        <Check size={18} />
      ) : (
        <Button
          disabled={busy}
          onClick={() => run(() => action("assets.download", { name: asset.name }))}
          label={
            busy ? (
              "Downloading…"
            ) : error ? (
              <>
                <RefreshCw size={14} />
                Retry
              </>
            ) : (
              <>
                <Download size={14} />
                Download
              </>
            )
          }
        />
      )}
      {manuallyCancellable && (
        <Button onClick={() => run(() => action("assets.cancel", { name: asset.name }))} label="Cancel" />
      )}
      {busy && !manuallyCancellable && session?.turn_running && (
        <Button onClick={() => run(() => action("chat.stop"))} label="Stop agent" />
      )}
    </div>
  );
}
const isLocalVision = (asset: Asset) => asset.name.startsWith("local-vision/");

function LocalVisionDownload({ onLater }: { onLater?: () => void }) {
  const { data: assets, error } = useCoreQuery("assets.status");
  const { data: downloads } = useQuery<DownloadActivities>({
    queryKey: ["downloads"],
    queryFn: () => ({}),
    enabled: false,
  });
  const [downloading, setDownloading] = useState(false);
  const { data: session } = useSession();
  const supported = assets?.some(isLocalVision);
  const files = supported
    ? (assets ?? []).filter(
        (asset) => isLocalVision(asset) || asset.name === "face_detection_yunet_2023mar.onnx",
      )
    : [];
  const missing = files.filter((asset) => !asset.present);
  const active = files.find((asset) => (downloads?.[asset.name]?.pending ?? 0) > 0);
  const { data: progress } = useQuery<Params>({
    queryKey: ["progress", active?.name],
    queryFn: () => ({}),
    enabled: false,
  });
  const ready = files.length > 0 && !missing.length;
  const selected = session?.provider_profile_id === ON_DEVICE;
  const downloadMiB = missing.reduce((total, asset) => total + asset.approx_mb, 0);

  return (
    <div className="assets">
      <h3>On-device AI</h3>
      <p className="muted">
        Ask for basic photo edits like captions, filters, or laser eyes.
        Your photos stay on this computer. No account or key needed.
      </p>
      {error && <p className="error-text">{error.message}</p>}
      {assets && !supported ? (
        <p className="muted">On-device AI is unavailable on this computer.</p>
      ) : (
        <button
          disabled={!supported || downloading || !!active || !!session?.turn_running || (ready && selected)}
          onClick={() =>
            run(async () => {
              setDownloading(true);
              try {
                for (const asset of missing) {
                  await action("assets.download", { name: asset.name });
                }
                await action("providers.on_device");
                onLater?.();
              } finally {
                setDownloading(false);
              }
            })
          }
        >
          {active
            ? `Downloading ${active.label}…`
            : downloading
              ? "Setting up…"
              : ready
                ? selected ? "On-device AI is active" : "Use on-device AI"
                : `Download and use on-device AI${downloadMiB ? ` (about ${downloadMiB} MiB)` : ""}`}
        </button>
      )}
      {active && (
        <>
          <progress
            aria-label="On-device AI download progress"
            max={Number(progress?.total) || undefined}
            value={Number(progress?.done) || undefined}
          />
          <button onClick={() => run(() => action("assets.cancel", { name: active.name }))}>
            Cancel download
          </button>
        </>
      )}
      {onLater && (
        <>
          <button onClick={onLater} disabled={downloading || !!active}>
            {selected ? "Continue" : "Download later"}
          </button>
          <p className="muted">Available anytime in Settings → Assets.</p>
        </>
      )}
    </div>
  );
}

function Assets() {
  const [downloading, setDownloading] = useState<string | null>(null);
  const { data: downloads } = useQuery<DownloadActivities>({
    queryKey: ["downloads"],
    queryFn: () => ({}),
    enabled: false,
  });
  const { data: assets, error } = useCoreQuery("assets.status");
  return (
    <div className="assets">
      <p className="muted">
        Downloaded once, used on your computer. Missing assets download when first needed.
      </p>
      {error && <p className="error-text">{error.message}</p>}
      <Button
        disabled={
          downloading !== null || Object.values(downloads ?? {}).some((transfer) => transfer.pending > 0)
        }
        onClick={() =>
          run(async () => {
            try {
              for (const asset of assets ?? [])
                if (!isLocalVision(asset) && !asset.present) {
                  setDownloading(asset.name);
                  await action("assets.download", { name: asset.name });
                }
            } finally {
              setDownloading(null);
            }
          })
        }
        label="Download all editing assets"
        icon={Download}
        iconSize={15}
      />
      {assets?.filter((asset) => !isLocalVision(asset)).map((asset) => (
        <AssetRow key={asset.name} asset={asset} active={downloading === asset.name} />
      ))}
      <LocalVisionDownload />
    </div>
  );
}
export function Settings({ updates }: { updates: ReturnType<typeof useUpdates> }) {
  const [tab, setTab] = useState(updates.info?.version ? "updates" : "providers");
  const [edit, setEdit] = useState<Profile | null | undefined>(undefined);
  const [test, setTest] = useState<Record<string, { message: string; failed: boolean }>>({});
  const [checking, setChecking] = useState(false);
  const [detected, setDetected] = useState<CLIDetection[] | null>(null);
  const { data: profiles } = useCoreQuery("providers.list");
  const { data: settings } = useCoreQuery("settings.get");
  const { data: session } = useSession();
  const theme = useUI((s) => s.theme);
  const appearance = useUI();
  const update = (values: Partial<SettingsType>) => run(() => action("settings.set", { values }));
  const checkProvider = async (profile: Profile, probe = false) => {
    setChecking(true);
    setTest((previous) => ({
      ...previous,
      [profile.id]: {
        message: probe ? "Testing connection…" : "Checking setup…",
        failed: false,
      },
    }));
    try {
      const result = await action("providers.test", {
        profile_id: profile.id,
        ...(probe ? { probe: true } : {}),
      });
      setTest((previous) => ({
        ...previous,
        [profile.id]: {
          message:
            result.status === "ready"
              ? [
                  result.probed
                    ? "Connection succeeded."
                    : profile.kind === "cli"
                      ? "Installation checked."
                      : "Setup checked. No test request was sent.",
                  ...(result.warnings ?? []),
                ].join(" ")
              : (result.error ?? "Provider check failed."),
          failed: result.status !== "ready",
        },
      }));
    } catch (error) {
      setTest((previous) => ({
        ...previous,
        [profile.id]: {
          message: error instanceof Error ? error.message : String(error),
          failed: true,
        },
      }));
    } finally {
      setChecking(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) useUI.getState().set({ settingsOpen: false });
      }}
    >
      <section className="modal settings-modal" role="dialog" aria-modal="true" aria-label="Settings">
        <div className="modal-heading">
          <div>
            <h2>Settings</h2>
            <p>Your art director. Your rules.</p>
          </div>
          <button aria-label="Close settings" onClick={() => useUI.getState().set({ settingsOpen: false })}>
            <ThemeIcon name="close" size={20} />
          </button>
        </div>
        <ErrorNotice />
        <div className="settings-body">
          <nav>
            {[
              ["providers", "Providers"],
              ["preferences", "Preferences"],
              ["assets", "Assets"],
              ["updates", "Updates"],
            ].map(([id, label]) => (
              <Button
                key={id}
                className={id === tab ? "active" : ""}
                onClick={() => setTab(id)}
                label={label}
              />
            ))}
          </nav>
          <div className="settings-content">
            {tab === "updates" && <UpdateSettings updates={updates} />}
            {tab === "providers" && (
              <>
                {edit !== undefined ? (
                  <>
                    <Button
                      className="back-link"
                      onClick={() => setEdit(undefined)}
                      label="Back to providers"
                    />
                    <ProfileEditor
                      key={edit?.id ?? "new"}
                      initial={edit ?? undefined}
                      onSaved={() => setEdit(undefined)}
                    />
                  </>
                ) : (
                  <>
                    <div className="section-title">
                      <h3>Model providers</h3>
                      <Button onClick={() => setEdit(null)} label="Add provider" icon={Plus} iconSize={14} />
                    </div>
                    {profiles?.map((profile) => (
                      <div className="profile-row" key={profile.id}>
                        <div>
                          <strong>{profile.label}</strong>
                          <span>
                            {profile.id === ON_DEVICE
                              ? "Runs on this computer"
                              : `${kindNames[profile.kind]} / ${profile.model || profile.cli}`}
                          </span>
                          {test[profile.id] && (
                            <small
                              role={test[profile.id].failed ? "alert" : "status"}
                              className={test[profile.id].failed ? "error-text" : ""}
                            >
                              {test[profile.id].message}
                            </small>
                          )}
                        </div>
                        <div>
                          <Button
                            disabled={session?.provider_profile_id === profile.id}
                            onClick={() =>
                              run(() =>
                                action("providers.select", {
                                  profile_id: profile.id,
                                }),
                              )
                            }
                            label={
                              session?.provider_profile_id === profile.id ? (
                                <>
                                  <Check size={13} />
                                  Active
                                </>
                              ) : (
                                "Use"
                              )
                            }
                          />
                          {profile.id !== ON_DEVICE && <Button onClick={() => setEdit(profile)} label="Edit" />}
                          <Button
                            disabled={checking}
                            onClick={() => void checkProvider(profile)}
                            label={profile.kind === "cli" ? "Check installation" : "Check setup"}
                          />
                          {profile.kind !== "cli" && (
                            <Button
                              disabled={checking}
                              onClick={() => void checkProvider(profile, true)}
                              label="Test connection"
                            />
                          )}
                          <button
                            aria-label={`Delete ${profile.label}`}
                            onClick={() =>
                              run(() =>
                                action("providers.delete", {
                                  profile_id: profile.id,
                                }),
                              )
                            }
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                        {profile.kind !== "cli" && (
                          <small className="probe-notice">
                            Test connection sends a short test request; your provider may charge.
                          </small>
                        )}
                      </div>
                    ))}
                    {!profiles?.length && (
                      <p className="muted">
                        Add a provider to start chatting. You can run tools without one.
                      </p>
                    )}
                    <div className="cli-detection">
                      <h3>Installed CLI tools</h3>
                      <p className="muted">Uses your existing subscription login. Gemini is experimental.</p>
                      <Button
                        onClick={() => run(async () => setDetected(await action("providers.detect")))}
                        label="Detect CLI tools"
                        icon={Terminal}
                        iconSize={14}
                      />
                      {detected !== null && (
                        <div className="detected-clis">
                          {detected.map((cli) => (
                            <div key={cli.cli}>
                              <strong>
                                {cli.cli === "claude"
                                  ? "Claude Code"
                                  : cli.cli === "codex"
                                    ? "Codex"
                                    : "Gemini CLI"}
                              </strong>
                              <span>
                                {!cli.available
                                  ? "Not found"
                                  : !cli.supported
                                    ? "Update needed"
                                    : (cli.version ?? "Installed")}
                                {cli.experimental ? " / experimental" : ""}
                              </span>
                              {cli.executable && <code>{cli.executable}</code>}
                              {cli.error && <p>{cli.error}</p>}
                              <Button
                                disabled={!cli.available || !cli.supported}
                                onClick={() =>
                                  setEdit({
                                    id: crypto.randomUUID(),
                                    kind: "cli",
                                    cli: cli.cli,
                                    label:
                                      cli.cli === "claude"
                                        ? "Claude Code"
                                        : cli.cli === "codex"
                                          ? "Codex"
                                          : "Gemini CLI",
                                    executable: cli.executable,
                                    model: "",
                                    capability_overrides: {},
                                  })
                                }
                                label="Add provider"
                              />
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </>
            )}
            {tab === "preferences" && settings && (
              <div className="preferences">
                <SelectField
                  label="Default approval mode"
                  value={settings.approval_mode}
                  onChange={(e) => update({ approval_mode: e.target.value as SettingsType["approval_mode"] })}
                  options={[
                    ["auto", "Auto"] as const,
                    ["ask_changes", "Ask for changes"] as const,
                    ["ask_all", "Ask for everything"] as const,
                  ]}
                />
                <InputField
                  label="Replay after editing a step"
                  labelClassName="switch-label"
                  type="checkbox"
                  checked={settings.auto_replay}
                  onChange={(e) => update({ auto_replay: e.target.checked })}
                />
                <InputField
                  label="Maximum steps per turn"
                  type="number"
                  min="1"
                  max="500"
                  defaultValue={settings.step_budget}
                  onBlur={(e) => {
                    if (e.target.validity.valid && e.target.value)
                      update({ step_budget: Number(e.target.value) });
                  }}
                />
                <label>
                  Output folder
                  <div className="folder-field">
                    <input
                      value={settings.output_dir ?? ""}
                      placeholder="badshop folder in Pictures"
                      onChange={(e) =>
                        queries.setQueryData(["settings.get"], {
                          ...settings,
                          output_dir: e.target.value || null,
                        })
                      }
                      onBlur={(e) => update({ output_dir: e.target.value || null })}
                    />
                    <button
                      title="Choose output folder"
                      onClick={() =>
                        run(async () => {
                          const path = await pickFolder();
                          if (path)
                            await action("settings.set", {
                              values: { output_dir: path },
                            });
                        })
                      }
                    >
                      <ThemeIcon name="open" size={16} />
                    </button>
                  </div>
                </label>
                <SelectField
                  label="Theme"
                  value={theme}
                  onChange={(e) => {
                    savePreference("theme", e.target.value);
                    useUI.getState().set({ theme: e.target.value });
                  }}
                  options={themes.map((item) => [item.id, item.name] as const)}
                />
                <div className="theme-grid" aria-label="Interface skins">
                  {themes
                    .filter((item) => !["system", "dark", "light"].includes(item.id))
                    .map((item) => (
                      <button
                        type="button"
                        className="theme-card"
                        key={item.id}
                        aria-pressed={theme === item.id}
                        onClick={() => {
                          savePreference("theme", item.id);
                          appearance.set({ theme: item.id });
                        }}
                      >
                        <span className="theme-preview" data-skin={item.id} aria-hidden="true">
                          <span className="theme-preview-title">badshop <span>×</span></span>
                          <span className="theme-preview-body">
                            <span className="theme-preview-menu">
                              <i><ThemeIcon name="save" size={12} theme={item.id} /></i>
                              <i><ThemeIcon name="settings" size={12} theme={item.id} /></i>
                              <i><ThemeIcon name="images" size={12} theme={item.id} /></i>
                            </span>
                            <span className="theme-preview-canvas">Aa<span>✦</span></span>
                          </span>
                          <span className="theme-preview-status">{item.era}</span>
                        </span>
                        <strong>{item.name}</strong>
                        <small>{item.description}</small>
                      </button>
                    ))}
                </div>
                <SelectField
                  label="Interface density"
                  value={appearance.density}
                  onChange={(e) => {
                    savePreference("density", e.target.value);
                    appearance.set({ density: e.target.value as Density });
                  }}
                  options={[["comfortable", "Comfortable"] as const, ["compact", "Compact"] as const]}
                />
                <SelectField
                  label="Text size"
                  value={appearance.textScale}
                  onChange={(e) => {
                    savePreference("textScale", e.target.value);
                    appearance.set({ textScale: Number(e.target.value) });
                  }}
                >
                  {[100, 115, 130, 150, 175, 200].map((value) => (
                    <option key={value} value={value}>
                      {value}%
                    </option>
                  ))}
                </SelectField>
                <SelectField
                  label="Motion"
                  value={appearance.motion}
                  onChange={(e) => {
                    savePreference("motion", e.target.value);
                    appearance.set({ motion: e.target.value as Motion });
                  }}
                  options={[
                    ["system", "Follow system"] as const,
                    ["reduced", "Reduced motion"] as const,
                    ["full", "Full motion"] as const,
                  ]}
                />
                <details>
                  <summary>Tool limits</summary>
                  <InputField
                    label="Timeout in seconds"
                    type="number"
                    min="1"
                    max="3600"
                    defaultValue={settings.tool_timeout_s}
                    onBlur={(e) => {
                      if (e.target.validity.valid) update({ tool_timeout_s: Number(e.target.value) });
                    }}
                  />
                  <InputField
                    label="Tool memory (MB)"
                    type="number"
                    min="256"
                    max="65536"
                    defaultValue={settings.tool_memory_mb}
                    onBlur={(e) => {
                      if (e.target.validity.valid) update({ tool_memory_mb: Number(e.target.value) });
                    }}
                  />
                </details>
                <SourceSettings />
              </div>
            )}
            {tab === "assets" && <Assets />}
          </div>
        </div>
      </section>
    </div>
  );
}
export function Welcome({ onClose, onManual = onClose }: { onClose: () => void; onManual?: () => void }) {
  const [step, setStep] = useState(1);
  const [kind, setKind] = useState<Profile["kind"]>("api");
  const { data: assets } = useCoreQuery("assets.status");
  const { data: profiles } = useCoreQuery("providers.list");
  const { data: session } = useSession();
  const [choosing, setChoosing] = useState(false);
  useEffect(() => {
    if (
      session?.provider_profile_id &&
      profiles?.some((profile) => profile.id === session.provider_profile_id)
    )
      setStep(3);
  }, [session?.provider_profile_id, profiles]);
  const chooseProfile = async (profile: Profile) => {
    setChoosing(true);
    try {
      await action("providers.select", { profile_id: profile.id });
      setStep(3);
    } finally {
      setChoosing(false);
    }
  };
  return (
    <div className="modal-backdrop">
      <section
        className="modal welcome-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Welcome to badshop"
      >
        <div className="welcome-top">
          <div className="brand">
            badshop<span>✱</span>
          </div>
          {step > 1 && <span>AI setup {step} of 3</span>}
        </div>
        <h2>
          {step === 1
            ? "Make your first shitpost."
            : step === 2
              ? "Make the connection."
              : "Bring your own bad taste."}
        </h2>
        <p>
          {step === 1
            ? "Start with a quick idea and a free sample. Add your own punchline, then copy it straight into the group chat."
            : step === 2
              ? "The model makes the decisions. badshop does the pixel work."
              : "Download the essentials now, or let badshop fetch them when needed."}
        </p>
        <ErrorNotice />
        {step === 1 ? (
          <>
            <button className="primary" onClick={onClose}>Start with a quick idea<ArrowRight size={16} /></button>
            <button onClick={onManual}>
              Edit a photo without AI
              <ArrowRight size={16} />
            </button>
            {!!profiles?.length && (
              <div className="saved-provider-choice">
                <h3>Use a saved provider</h3>
                {profiles.map((profile) => (
                  <button
                    key={profile.id}
                    disabled={choosing}
                    aria-label={`Use ${profile.label}`}
                    onClick={() => run(() => chooseProfile(profile))}
                  >
                    <strong>{profile.label}</strong>
                    {profile.id !== ON_DEVICE && <span>{profile.model || profile.cli}</span>}
                    <ArrowRight size={15} />
                  </button>
                ))}
                <p>Or connect another provider below.</p>
              </div>
            )}
            <LocalVisionDownload onLater={onClose} />
            <h3>Connect an AI model</h3>
            <div className="kind-grid">
              {Object.entries(kindNames).map(([value, label]) => {
                const Icon = icons[value as Profile["kind"]];
                return (
                  <button
                    key={value}
                    className={kind === value ? "selected" : ""}
                    onClick={() => setKind(value as Profile["kind"])}
                  >
                    <Icon size={23} />
                    <strong>{label}</strong>
                    <span>{kindHints[value as Profile["kind"]]}</span>
                  </button>
                );
              })}
            </div>
            <button onClick={() => setStep(2)}>
              Continue with {kindNames[kind]}
              <ArrowRight size={16} />
            </button>
          </>
        ) : step === 2 ? (
          <ProfileEditor kind={kind} onSaved={chooseProfile} />
        ) : (
          <>
            <div className="welcome-assets">
              {assets
                ?.filter(
                  (asset) =>
                    !isLocalVision(asset) &&
                    (!asset.name.includes("rembg/") ||
                      asset.name === "rembg/u2net.onnx"),
                )
                .map((asset) => (
                  <AssetRow asset={asset} key={asset.name} />
                ))}
            </div>
            <button className="primary" onClick={onClose}>
              Start making badshops
              <ArrowRight size={16} />
            </button>
          </>
        )}
        {step === 2 && <Button className="back-link" onClick={onManual} label="Edit a photo without AI" />}
      </section>
    </div>
  );
}
