import { useEffect, useState } from "react";
import {
  X,
  Plus,
  Trash2,
  Check,
  FolderOpen,
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
import { useUI } from "../store";
import { pickFolder } from "../native";
import { BIREFNET_MEMORY_NOTE } from "../constants";
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
  onSaved: (profile: Profile) => void;
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
  const [keyMode, setKeyMode] = useState(
    initial?.api_key_env ? "environment" : "keychain",
  );
  const [busy, setBusy] = useState(false);
  const [cliStatus, setCLIStatus] = useState("");
  const update = (patch: Partial<Profile>) =>
    setProfile({ ...profile, ...patch });
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
              ...(isCLI
                ? { cli: profile.cli ?? "claude", model: profile.model ?? "" }
                : {}),
              ...(keyMode === "environment"
                ? { api_key_env: profile.api_key_env }
                : {}),
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
              ...(!isCLI && keyMode === "keychain" && key
                ? { api_key: key }
                : {}),
            });
            setKey("");
            onSaved(saved);
          } finally {
            setBusy(false);
          }
        });
      }}
    >
      <label>
        Provider type
        <select
          value={profile.kind}
          onChange={(event) =>
            update({ kind: event.target.value as Profile["kind"] })
          }
        >
          {Object.entries(kindNames).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">{kindHints[profile.kind ?? "api"]}</p>
      <label>
        Profile name
        <input
          required
          value={profile.label ?? ""}
          placeholder="My art director"
          onChange={(e) => update({ label: e.target.value })}
        />
      </label>
      {isCLI ? (
        <>
          <label>
            Command line tool
            <select
              value={profile.cli ?? "claude"}
              onChange={(e) =>
                update({ cli: e.target.value as Profile["cli"] })
              }
            >
              <option value="claude">Claude Code</option>
              <option value="codex">Codex</option>
              <option value="gemini">Gemini CLI (experimental)</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() =>
              run(async () => {
                const detected = await action("providers.detect");
                const cli = detected.find(
                  (item) => item.cli === (profile.cli ?? "claude"),
                );
                if (cli?.available && cli.supported) {
                  update({ executable: cli.executable });
                  setCLIStatus(cli.version ?? "CLI detected");
                } else
                  setCLIStatus(
                    cli?.error ??
                      "CLI not found. Install it or enter its path below.",
                  );
              })
            }
          >
            <Terminal size={14} />
            Detect installed CLI
          </button>
          {cliStatus && <p className="field-description">{cliStatus}</p>}
          <label>
            Executable path (optional)
            <input
              value={profile.executable ?? ""}
              placeholder="Auto-detect from PATH"
              onChange={(e) => update({ executable: e.target.value || null })}
            />
          </label>
          <label>
            Model (optional)
            <input
              value={profile.model ?? ""}
              placeholder="Use the CLI’s default model"
              onChange={(e) => update({ model: e.target.value })}
            />
          </label>
          <p className="field-description">
            Sign in using the CLI in your terminal first. badshop supplies the
            tools and asks for approvals here.
          </p>
        </>
      ) : (
        <>
          <label>
            Model
            <input
              required
              value={profile.model ?? ""}
              placeholder={
                profile.kind === "local"
                  ? "ollama_chat/llava"
                  : "openai/gpt-4.1"
              }
              onChange={(e) => update({ model: e.target.value })}
            />
          </label>
          <label>
            API base URL {profile.kind === "api" ? "(optional)" : ""}
            <input
              type="url"
              required={profile.kind === "openai_compatible"}
              value={profile.api_base ?? ""}
              placeholder={
                profile.kind === "local"
                  ? "http://localhost:11434"
                  : "https://api.example.com/v1"
              }
              onChange={(e) => update({ api_base: e.target.value || null })}
            />
          </label>
          <label>
            Credential storage
            <select
              value={keyMode}
              onChange={(e) => setKeyMode(e.target.value)}
            >
              <option value="keychain">OS keychain</option>
              <option value="environment">Environment variable</option>
            </select>
          </label>
          {keyMode === "keychain" ? (
            <label>
              API key{" "}
              {initial?.api_key_ref
                ? "(leave blank to keep saved key)"
                : "(optional for local models)"}
              <input
                type="password"
                autoComplete="new-password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Stored in your system keychain"
              />
            </label>
          ) : (
            <label>
              Environment variable name
              <input
                required
                pattern="[A-Za-z_][A-Za-z0-9_]*"
                placeholder="OPENAI_API_KEY"
                value={profile.api_key_env ?? ""}
                onChange={(e) => update({ api_key_env: e.target.value })}
              />
            </label>
          )}
          <p className="field-description">
            If your keychain is locked or unavailable, unlock it or use an
            environment variable. Keys never enter saved sessions.
          </p>
          {profile.capability_overrides?.tool_calls === false && (
            <p className="field-description">
              This model will use the weaker JSON fallback for tools. Results
              may be poor.
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
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save provider"}
      </button>
    </form>
  );
}
export function AssetRow({
  asset,
  active = false,
}: {
  asset: Asset;
  active?: boolean;
}) {
  const [localBusy, setBusy] = useState(false);
  const manuallyCancellable = localBusy || active;
  const [error, setError] = useState("");
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
        <span>
          {asset.present ? "Downloaded" : `About ${asset.approx_mb} MB`}
        </span>
        {asset.name.includes("birefnet") && (
          <span className="model-memory-note">{BIREFNET_MEMORY_NOTE}</span>
        )}
        {busy && (
          <progress
            max={Number(progress?.total) || undefined}
            value={Number(progress?.done) || undefined}
          />
        )}{" "}
        {error && <span className="error-text">{error}</span>}
      </div>
      {asset.present ? (
        <Check size={18} />
      ) : (
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError("");
            void action("assets.download", { name: asset.name })
              .catch((e) => setError(e.message))
              .finally(() => setBusy(false));
          }}
        >
          {busy ? (
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
          )}
        </button>
      )}
      {manuallyCancellable && (
        <button
          onClick={() =>
            run(() => action("assets.cancel", { name: asset.name }))
          }
        >
          Cancel
        </button>
      )}
      {busy && !manuallyCancellable && session?.turn_running && (
        <button onClick={() => run(() => action("chat.stop"))}>
          Stop agent
        </button>
      )}
    </div>
  );
}
function Assets() {
  const [downloading, setDownloading] = useState<string | null>(null);
  const { data: assets, error } = useCoreQuery("assets.status");
  return (
    <div className="assets">
      <p className="muted">
        Downloaded once, used on your computer. Missing assets download when
        first needed.
      </p>
      {error && <p className="error-text">{error.message}</p>}
      <button
        disabled={downloading !== null}
        onClick={() =>
          run(async () => {
            try {
              for (const asset of assets ?? [])
                if (!asset.present) {
                  setDownloading(asset.name);
                  await action("assets.download", { name: asset.name });
                }
            } finally {
              setDownloading(null);
            }
          })
        }
      >
        <Download size={15} />
        Download all assets
      </button>
      {assets?.map((asset) => (
        <AssetRow
          key={asset.name}
          asset={asset}
          active={downloading === asset.name}
        />
      ))}
    </div>
  );
}
export function Settings() {
  const [tab, setTab] = useState("providers");
  const [edit, setEdit] = useState<Profile | null | undefined>(undefined);
  const [test, setTest] = useState<Record<string, string>>({});
  const [detected, setDetected] = useState<CLIDetection[] | null>(null);
  const { data: profiles } = useCoreQuery("providers.list");
  const { data: settings } = useCoreQuery("settings.get");
  const { data: session } = useSession();
  const theme = useUI((s) => s.theme);
  const update = (values: Partial<SettingsType>) =>
    run(() => action("settings.set", { values }));
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget)
          useUI.getState().set({ settingsOpen: false });
      }}
    >
      <section
        className="modal settings-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
      >
        <div className="modal-heading">
          <div>
            <h2>Settings</h2>
            <p>Your art director. Your rules.</p>
          </div>
          <button
            aria-label="Close settings"
            onClick={() => useUI.getState().set({ settingsOpen: false })}
          >
            <X size={20} />
          </button>
        </div>
        <div className="settings-body">
          <nav>
            {[
              ["providers", "Providers"],
              ["preferences", "Preferences"],
              ["assets", "Assets"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={id === tab ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="settings-content">
            {tab === "providers" && (
              <>
                {edit !== undefined ? (
                  <>
                    <button
                      className="back-link"
                      onClick={() => setEdit(undefined)}
                    >
                      Back to providers
                    </button>
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
                      <button onClick={() => setEdit(null)}>
                        <Plus size={14} />
                        Add provider
                      </button>
                    </div>
                    {profiles?.map((profile) => (
                      <div className="profile-row" key={profile.id}>
                        <div>
                          <strong>{profile.label}</strong>
                          <span>
                            {kindNames[profile.kind]} /{" "}
                            {profile.model || profile.cli}
                          </span>
                          {test[profile.id] && (
                            <small>{test[profile.id]}</small>
                          )}
                        </div>
                        <div>
                          <button
                            disabled={
                              session?.provider_profile_id === profile.id
                            }
                            onClick={() =>
                              run(() =>
                                action("providers.select", {
                                  profile_id: profile.id,
                                }),
                              )
                            }
                          >
                            {session?.provider_profile_id === profile.id ? (
                              <>
                                <Check size={13} />
                                Active
                              </>
                            ) : (
                              "Use"
                            )}
                          </button>
                          <button onClick={() => setEdit(profile)}>Edit</button>
                          <button
                            onClick={() =>
                              run(async () => {
                                setTest((prev) => ({
                                  ...prev,
                                  [profile.id]: "Testing…",
                                }));
                                const result = await action("providers.test", {
                                  profile_id: profile.id,
                                });
                                setTest((prev) => ({
                                  ...prev,
                                  [profile.id]:
                                    result.status === "ready"
                                      ? [
                                          "Capabilities checked.",
                                          ...(result.warnings ?? []),
                                        ].join(" ")
                                      : (result.error ??
                                        "Provider test failed."),
                                }));
                              })
                            }
                          >
                            Test
                          </button>
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
                      </div>
                    ))}
                    {!profiles?.length && (
                      <p className="muted">
                        Add a provider to start chatting. You can run tools
                        without one.
                      </p>
                    )}
                    <div className="cli-detection">
                      <h3>Installed CLI tools</h3>
                      <p className="muted">
                        Uses your existing subscription login. Gemini is
                        experimental.
                      </p>
                      <button
                        onClick={() =>
                          run(async () =>
                            setDetected(await action("providers.detect")),
                          )
                        }
                      >
                        <Terminal size={14} />
                        Detect CLI tools
                      </button>
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
                              <button
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
                              >
                                Add provider
                              </button>
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
                <label>
                  Default approval mode
                  <select
                    value={settings.approval_mode}
                    onChange={(e) =>
                      update({
                        approval_mode: e.target
                          .value as SettingsType["approval_mode"],
                      })
                    }
                  >
                    <option value="auto">Auto</option>
                    <option value="ask_changes">Ask for changes</option>
                    <option value="ask_all">Ask for everything</option>
                  </select>
                </label>
                <label className="switch-label">
                  Replay after editing a step
                  <input
                    type="checkbox"
                    checked={settings.auto_replay}
                    onChange={(e) => update({ auto_replay: e.target.checked })}
                  />
                </label>
                <label>
                  Maximum steps per turn
                  <input
                    type="number"
                    min="1"
                    max="500"
                    defaultValue={settings.step_budget}
                    onBlur={(e) => {
                      if (e.target.validity.valid && e.target.value)
                        update({ step_budget: Number(e.target.value) });
                    }}
                  />
                </label>
                <label>
                  Output folder
                  <div className="folder-field">
                    <input
                      value={settings.output_dir ?? ""}
                      placeholder="~/Pictures/badshop"
                      onChange={(e) =>
                        queries.setQueryData(["settings.get"], {
                          ...settings,
                          output_dir: e.target.value || null,
                        })
                      }
                      onBlur={(e) =>
                        update({ output_dir: e.target.value || null })
                      }
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
                      <FolderOpen size={16} />
                    </button>
                  </div>
                </label>
                <label>
                  Theme
                  <select
                    value={theme}
                    onChange={(e) => {
                      localStorage.setItem("badshop.theme", e.target.value);
                      useUI.getState().set({ theme: e.target.value });
                    }}
                  >
                    <option value="system">Follow system</option>
                    <option value="dark">Dark</option>
                    <option value="light">Light</option>
                  </select>
                </label>
                <details>
                  <summary>Tool limits</summary>
                  <label>
                    Timeout in seconds
                    <input
                      type="number"
                      min="1"
                      max="3600"
                      defaultValue={settings.tool_timeout_s}
                      onBlur={(e) => {
                        if (e.target.validity.valid)
                          update({ tool_timeout_s: Number(e.target.value) });
                      }}
                    />
                  </label>
                  <label>
                    Tool memory (MB)
                    <input
                      type="number"
                      min="256"
                      max="65536"
                      defaultValue={settings.tool_memory_mb}
                      onBlur={(e) => {
                        if (e.target.validity.valid)
                          update({ tool_memory_mb: Number(e.target.value) });
                      }}
                    />
                  </label>
                </details>
              </div>
            )}
            {tab === "assets" && <Assets />}
          </div>
        </div>
      </section>
    </div>
  );
}
export function Welcome({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(1);
  const [kind, setKind] = useState<Profile["kind"]>("api");
  const { data: assets } = useCoreQuery("assets.status");
  const { data: profiles } = useCoreQuery("providers.list");
  useEffect(() => {
    if (profiles?.length) setStep(3);
  }, [profiles?.length]);
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
          <span>Set up {step} of 3</span>
        </div>
        <h2>
          {step === 1
            ? "Meet your art director."
            : step === 2
              ? "Make the connection."
              : "Bring your own bad taste."}
        </h2>
        <p>
          {step === 1
            ? "Pick how you’d like to talk to a model. You can add more providers anytime."
            : step === 2
              ? "The model makes the decisions. badshop does the pixel work."
              : "Download the essentials now, or let badshop fetch them when needed."}
        </p>
        {step === 1 ? (
          <>
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
            <button className="primary" onClick={() => setStep(2)}>
              Continue
              <ArrowRight size={16} />
            </button>
          </>
        ) : step === 2 ? (
          <ProfileEditor
            kind={kind}
            onSaved={(profile) =>
              run(async () => {
                await action("providers.select", { profile_id: profile.id });
                setStep(3);
              })
            }
          />
        ) : (
          <>
            <div className="welcome-assets">
              {assets
                ?.filter(
                  (asset) =>
                    !asset.name.includes("rembg/") ||
                    asset.name === "rembg/u2net.onnx",
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
        <button className="back-link" onClick={onClose}>
          Set up later / use tools manually
        </button>
      </section>
    </div>
  );
}
