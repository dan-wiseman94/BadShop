import { useCallback, useEffect, useRef, useState } from "react";
import { savePreference } from "./appearance";
import { action, queries } from "./data";
import { useUI } from "./store";
import type { MethodMap, Params, Session } from "./types";

type PreviewPlan = MethodMap["previews.plan"][1];
type Target = { step_id: string } | { tool: string };
type Request = {
  key: string;
  owner: string;
  epoch: number;
  options: MethodMap["previews.plan"][0];
};
type Result = { key: string; plan?: PreviewPlan; image?: string; error?: string };

function ownerKey(session: Session | undefined, generation: number) {
  return JSON.stringify([generation, session?.id, session?.context?.core_instance_id,
    session?.context?.document_incarnation, session?.context?.branch_id, session?.document_revision]);
}

function fingerprint(params: Params) {
  return JSON.stringify(params, (_key, value) => value && typeof value === "object" && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
    : value);
}

function previewSource(bytes: string | undefined) {
  if (!bytes) return undefined;
  const encoded = bytes.startsWith("data:") ? bytes.slice(bytes.indexOf(",") + 1) : bytes;
  const format = encoded.startsWith("R0lG") ? "gif" : encoded.startsWith("/9j/") ? "jpeg" : "png";
  return `data:image/${format};base64,${encoded}`;
}

export function useEditorPreview({ session, target, scope, params, active, dirty, delay = 300 }: {
  session: Session | undefined;
  target: Target;
  scope: "step" | "final";
  params: Params;
  active: boolean;
  dirty: boolean;
  delay?: number;
}) {
  const automatic = useUI(state => state.automaticPreview);
  const generation = useUI(state => state.documentGeneration);
  const connected = useUI(state => state.status === "ready");
  const owner = ownerKey(session, generation);
  const epoch = useRef(0);
  const available = session !== undefined && active && connected;
  const key = available ? JSON.stringify([owner, target, scope, fingerprint(params)]) : null;
  const live = useRef<Request | null>(null);
  live.current = key && session ? {
    key, owner, epoch: epoch.current,
    options: { ...target, scope, params, expected_revision: session.document_revision },
  } : null;
  const mounted = useRef(false);
  const inFlight = useRef<Request | null>(null);
  const pending = useRef<Request | null>(null);
  const lastStarted = useRef<string | null>(null);
  const paused = useRef(false);
  const [busy, setBusy] = useState(false);
  const [longRender, setLongRender] = useState(false);
  const [slow, setSlow] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      pending.current = null;
    };
  }, []);
  useEffect(() => {
    lastStarted.current = null;
    setResult(current => current?.key === key ? current : null);
  }, [key]);

  const start = useCallback(async function start(request: Request, manual = false) {
    const current = () => {
      const ui = useUI.getState();
      return mounted.current && ui.status === "ready" && request.epoch === epoch.current &&
        live.current?.key === request.key &&
        ownerKey(queries.getQueryData<Session>(["session.get"]), ui.documentGeneration) === request.owner;
    };
    if (!current()) return;
    if (!manual && (!useUI.getState().automaticPreview || paused.current || lastStarted.current === request.key))
      return;
    if (inFlight.current) {
      if (inFlight.current.key !== request.key || inFlight.current.epoch !== request.epoch)
        pending.current = request;
      return;
    }
    inFlight.current = request;
    lastStarted.current = request.key;
    setBusy(true);
    const showLongRender = setTimeout(() => {
      if (mounted.current) setLongRender(true);
    }, 1000);
    let started: number | undefined;
    try {
      const plan = await action("previews.plan", request.options);
      if (!current()) return;
      if (!plan.eligible) {
        setResult({ key: request.key, plan });
        return;
      }
      const { params, expected_revision } = request.options;
      const options = { params, expected_revision };
      started = performance.now();
      const images = request.options.step_id
        ? await action("steps.preview", { ...options, step_id: request.options.step_id, final_result: plan.scope === "final" })
        : await action("tools.preview", { ...options, tool: request.options.tool! });
      if (current()) setResult({ key: request.key, plan, image: previewSource(images[0]) });
    } catch (problem) {
      if (current()) setResult({ key: request.key, error: problem instanceof Error ? problem.message : String(problem) });
    } finally {
      clearTimeout(showLongRender);
      inFlight.current = null;
      const next = pending.current;
      pending.current = null;
      if (mounted.current) {
        if (started !== undefined && performance.now() - started > 2000 && request.epoch === epoch.current) {
          paused.current = true;
          setSlow(true);
        }
        setBusy(false);
        setLongRender(false);
        if (next) void start(next);
      }
    }
  }, []);

  useEffect(() => {
    const request = live.current;
    if (!request || !dirty || !automatic || slow) return;
    const timer = setTimeout(() => void start(request), delay);
    return () => clearTimeout(timer);
  }, [key, dirty, automatic, slow, delay, start]);

  const visible = key && result?.key === key ? result : null;
  return {
    available,
    automatic,
    busy,
    longRender,
    slow,
    result: visible,
    updating: busy || (available && dirty && automatic && !slow && !visible),
    setAutomatic(value: boolean) {
      useUI.getState().set({ automaticPreview: value });
      savePreference("automaticPreview", value ? "on" : "off");
      if (!value) pending.current = null;
    },
    update() {
      if (live.current && !inFlight.current) void start(live.current, true);
    },
    resume() {
      paused.current = false;
      lastStarted.current = null;
      setSlow(false);
    },
    clear() {
      epoch.current += 1;
      pending.current = null;
      lastStarted.current = null;
      setResult(null);
    },
    canApply() {
      return !inFlight.current;
    },
    currentOwner() {
      const ui = useUI.getState();
      return !session || (ui.status === "ready" &&
        ownerKey(queries.getQueryData<Session>(["session.get"]), ui.documentGeneration) === owner);
    },
  };
}
