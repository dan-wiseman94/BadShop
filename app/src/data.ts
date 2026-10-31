import { QueryClient, useQuery } from "@tanstack/react-query";
import { rpc } from "./rpc";
import { useUI, showError } from "./store";
import { getConnection, onCoreStatus } from "./native";
import type {
  CoreEvent,
  MethodMap,
  Session,
  Message,
  Step,
  Artifact,
  Connection,
  Params,
} from "./types";
export const queries = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30000 },
  },
});
export function useCoreQuery<K extends keyof MethodMap>(method: K) {
  const ready = useUI((s) => s.status === "ready");
  return useQuery({
    queryKey: [method],
    queryFn: async ({ signal }) => {
      const value = await rpc.request(method, undefined, signal);
      return (
        method === "session.get"
          ? reconcileSessionSnapshot(
              value as Session,
              queries.getQueryData<Session>(["session.get"]),
            )
          : value
      ) as MethodMap[K][1];
    },
    enabled: ready,
  });
}
/** A snapshot can observe persistence before message.done reaches this socket. */
export function reconcileSessionSnapshot(
  snapshot: Session,
  previous?: Session,
): Session {
  if (previous?.id !== snapshot.id) return { ...snapshot, stream_text: "" };
  const knownAssistantIds = new Set(
    previous.messages
      .filter((message) => message.role === "assistant")
      .map((message) => message.id),
  );
  const completedReply = snapshot.messages.some(
    (message) =>
      message.role === "assistant" && !knownAssistantIds.has(message.id),
  );
  return {
    ...snapshot,
    stream_text: completedReply ? "" : (previous.stream_text ?? ""),
  };
}
export function useSession() {
  return useCoreQuery("session.get");
}
export async function action<K extends keyof MethodMap>(
  method: K,
  params?: MethodMap[K][0],
): Promise<MethodMap[K][1]> {
  let value: MethodMap[K][1];
  try {
    value = await rpc.request(method, params);
  } finally {
    if (method === "assets.download" && params && "name" in params) {
      queries.setQueryData<Params>(["progress", params.name], (old) =>
        old ? { ...old, active: false } : old,
      );
    }
  }
  await queries.invalidateQueries({ queryKey: ["session.get"] });
  if (method.startsWith("providers."))
    await queries.invalidateQueries({ queryKey: ["providers.list"] });
  if (method.startsWith("settings."))
    await queries.invalidateQueries({ queryKey: ["settings.get"] });
  if (method.startsWith("assets."))
    await queries.invalidateQueries({ queryKey: ["assets.status"] });
  return value;
}
export function run<T>(work: () => Promise<T>) {
  void work().catch(showError);
}
function applyEvent({ method, params }: CoreEvent) {
  if (method === "message.delta") {
    queries.setQueryData<Session>(["session.get"], (old) =>
      old
        ? {
            ...old,
            stream_text: (old.stream_text ?? "") + String(params.text ?? ""),
          }
        : old,
    );
    return;
  }
  if (method === "asset.progress") {
    queries.setQueryData(["progress", params.name], {
      ...params,
      active:
        params.total == null || Number(params.done) < Number(params.total),
    });
    if (params.total != null && Number(params.done) >= Number(params.total))
      void queries.invalidateQueries({ queryKey: ["assets.status"] });
    return;
  }
  if (method === "provider.event") {
    queries.setQueryData<Params[]>(["provider-events"], (old) => [
      ...(old ?? []).slice(-99),
      params,
    ]);
    return;
  }
  if (method === "core.log") {
    if (params.level === "error" || params.level === "warning")
      useUI.getState().set({ error: String(params.message) });
    return;
  }
  if (["step.finished", "step.failed", "turn.finished"].includes(method)) {
    queries.setQueriesData<Params>({ queryKey: ["progress"] }, (old) =>
      old ? { ...old, active: false } : old,
    );
  }
  queries.setQueryData<Session>(["session.get"], (old) => {
    if (!old) return old;
    let next = { ...old };
    if (method === "message.done") {
      const message = params.message as unknown as Message;
      next.messages = [
        ...old.messages.filter((m) => m.id !== message.id),
        message,
      ];
      next.stream_text = "";
    }
    if (params.step) {
      const step = params.step as unknown as Step;
      next.steps = [...old.steps.filter((s) => s.id !== step.id), step].sort(
        (a, b) => a.index - b.index,
      );
      const artifacts = params.artifacts as Artifact[] | undefined;
      if (artifacts)
        next.artifacts = {
          ...old.artifacts,
          ...Object.fromEntries(artifacts.map((a) => [a.id, a])),
        };
    }
    if (method === "step.deleted")
      next.steps = old.steps.filter((s) => s.id !== params.step_id);
    if (method === "step.stale")
      next.steps = old.steps.map((s) =>
        (params.step_ids as string[]).includes(s.id)
          ? { ...s, status: "stale" }
          : s,
      );
    if (method === "approval.needed" && params.step)
      next.pending_approvals = [
        ...new Set([
          ...old.pending_approvals,
          (params.step as unknown as Step).id,
        ]),
      ];
    if (method === "approval.resolved")
      next.pending_approvals = old.pending_approvals.filter(
        (id) => id !== params.step_id,
      );
    if (method === "turn.started") {
      next.turn_running = true;
      next.stream_text = "";
    }
    if (method === "turn.finished") {
      next.turn_running = false;
      next.stream_text = "";
      if (params.error) useUI.getState().set({ error: String(params.error) });
    }
    return next;
  });
  if (method !== "message.done")
    void queries.invalidateQueries({ queryKey: ["session.get"] });
}
export function startCore() {
  let disposed = false;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let generation = 0;
  let current: Connection | undefined;
  let failed = false;
  const schedule = () => {
    if (disposed || failed || reconnect) return;
    if (++attempt > 3) return;
    reconnect = setTimeout(() => {
      reconnect = undefined;
      void connect();
    }, 750 * attempt);
  };
  const connect = async (supplied?: Connection) => {
    const thisGeneration = ++generation;
    clearTimeout(reconnect);
    reconnect = undefined;
    try {
      const next = supplied ?? (await getConnection());
      if (disposed || thisGeneration !== generation) return;
      const restarted =
        !!current &&
        (current.port !== next.port || current.token !== next.token);
      if (!restarted && current && useUI.getState().status === "ready") return;
      useUI.getState().set({ logPath: next.log_path });
      await rpc.connect(next);
      if (disposed || thisGeneration !== generation) return;
      current = next;
      attempt = 0;
      failed = false;
      queries.setQueryData<Session>(["session.get"], (old) =>
        old ? { ...old, stream_text: "" } : old,
      );
      await queries.invalidateQueries();
      if (restarted) {
        const session = await rpc.request("session.get");
        if (session.restorable) await action("session.restore");
      }
    } catch (error) {
      if (disposed || thisGeneration !== generation) return;
      useUI.getState().set({ status: "disconnected" });
      schedule();
      if (attempt > 3) showError(error);
    }
  };
  const offStatus = rpc.onStatus((status) => {
    if (disposed || failed) return;
    useUI.getState().set({ status });
    if (status === "disconnected") schedule();
  });
  const offEvents = rpc.onEvent(applyEvent);
  const offNative = onCoreStatus((event) => {
    if (disposed) return;
    useUI.getState().set({ logPath: event.log_path });
    if (event.state === "ready" && event.port && event.token) {
      failed = false;
      void connect(event);
    } else if (event.state === "failed") {
      failed = true;
      ++generation;
      clearTimeout(reconnect);
      reconnect = undefined;
      rpc.disconnect();
      useUI.getState().set({ status: "failed" });
    } else {
      useUI.getState().set({ status: "starting" });
    }
  });
  void connect();
  return () => {
    disposed = true;
    ++generation;
    clearTimeout(reconnect);
    offStatus();
    offEvents();
    void offNative.then((fn) => fn());
    rpc.disconnect();
  };
}
export function useArtifact(id: string | null, thumb = false) {
  const ready = useUI((s) => s.status === "ready");
  return useQuery({
    queryKey: ["artifact", id, thumb],
    queryFn: ({ signal }) =>
      rpc.request(
        "artifacts.get",
        { id: id!, ...(thumb ? { max_px: 160 } : {}) },
        signal,
      ),
    enabled: ready && !!id,
    staleTime: Infinity,
  });
}
export function imageUrl(data: { mime: string; data: string } | undefined) {
  return data ? `data:${data.mime};base64,${data.data}` : undefined;
}
export async function importBlob(blob: Blob, name = "pasted.png") {
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
  return action("artifacts.import", { data, name });
}
