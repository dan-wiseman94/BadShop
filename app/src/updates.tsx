import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { native, openLink } from "./native";
import { readPreference, savePreference } from "./appearance";

type UpdateInfo = { currentVersion: string; version: string | null; notes: string | null; unavailable: string | null };
export function useUpdates(confirmInstall: () => Promise<boolean>, localOnly = false) {
  const [automatic, setAutomatic] = useState(() => readPreference("automaticUpdates", "true") === "true");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [phase, setPhase] = useState<"idle" | "checking" | "downloading" | "confirming" | "installing">("idle");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<{ downloaded: number; total?: number } | null>(null);
  const working = useRef(false);
  const check = useCallback(async () => {
    if (!native || working.current) return;
    working.current = true;
    setPhase("checking"); setError("");
    try { setInfo(await invoke<UpdateInfo>("update_check")); }
    catch (e) { setInfo(null); setError(`Could not check for updates: ${String(e)}`); }
    finally { working.current = false; setPhase("idle"); }
  }, []);
  useEffect(() => {
    if (!automatic || !native || localOnly) return;
    // Delay also prevents duplicate startup checks under React StrictMode.
    const startup = setTimeout(() => void check(), 5000);
    const interval = setInterval(() => void check(), 6 * 60 * 60 * 1000);
    return () => { clearTimeout(startup); clearInterval(interval); };
  }, [automatic, check, localOnly]);
  const install = async () => {
    if (!info?.version || working.current) return;
    working.current = true; setError(""); setProgress(null); setPhase("downloading");
    let off: (() => void) | undefined;
    try {
      off = await listen<{ downloaded: number; total?: number }>("update-progress", e => setProgress(e.payload));
      await invoke("update_download");
      setPhase("confirming");
      if (!(await confirmInstall())) return;
      setPhase("installing");
      await invoke("update_install");
    } catch (e) { setError(`Could not install update: ${String(e)}. You can retry.`); }
    finally { off?.(); working.current = false; setPhase("idle"); }
  };
  const cancel = async () => {
    try { await invoke("update_cancel"); }
    catch (e) { setError(`Could not cancel update: ${String(e)}`); }
  };
  return { automatic, info, phase, error, progress, check, install, cancel, localOnly,
    setAutomatic(value: boolean) { savePreference("automaticUpdates", String(value)); setAutomatic(value); },
  };
}

export function UpdateSettings({ updates: u }: { updates: ReturnType<typeof useUpdates> }) {
  return <section>
    <h3>App updates</h3>
    {u.info && <p>Installed version: {u.info.currentVersion}</p>}
    <label><input type="checkbox" checked={u.automatic} disabled={!native}
      onChange={e => u.setAutomatic(e.target.checked)} /> Automatically check for updates</label>
    <p className="muted">Checks on launch and every six hours when Local only is off. Updates install only when you choose.</p>
    {u.localOnly && <p>Local only is on. Turn it off to check for or download updates.</p>}
    <button disabled={!native || u.localOnly || u.phase !== "idle"} onClick={() => void u.check()}>
      {u.phase === "checking" ? "Checking…" : "Check for updates"}
    </button>
    {u.phase === "checking" && <button onClick={() => void u.cancel()}>Cancel update check</button>}
    <div role="status">
      {!native ? <p>Update checks are available in the desktop app.</p> : u.info?.unavailable ? <p>{u.info.unavailable}</p> : u.info?.version ? <>
        <p>Version {u.info.version} is available.</p>
        {u.info.notes && <p style={{ whiteSpace: "pre-wrap" }}>{u.info.notes}</p>}
        <button disabled={u.localOnly || u.phase !== "idle"} onClick={() => void u.install()}>Download &amp; install update</button>
        <p className="muted">You’ll be asked to save unsaved work. badshop will restart to finish updating.</p>
      </> : u.info && <p>You’re up to date.</p>}
    </div>
    {u.error && <p role="alert" className="error-text">{u.error}</p>}
    <button onClick={() => void openLink("https://github.com/dan-wiseman94/BadShop/releases/latest")}>View releases</button>
  </section>;
}

export function UpdateProgress({ updates: u }: { updates: ReturnType<typeof useUpdates> }) {
  if (u.phase !== "downloading" && u.phase !== "installing") return null;
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Updating badshop">
    <h2>{u.phase === "downloading" ? "Downloading update…" : "Installing update…"}</h2>
    <progress value={u.progress?.total ? u.progress.downloaded : undefined} max={u.progress?.total || undefined} />
    <p>Keep badshop open until this finishes.</p>
    {u.phase === "downloading" && <button onClick={() => void u.cancel()}>Cancel download</button>}
  </section></div>;
}
