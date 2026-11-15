import { QueryClient, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from 'react';
import type { BinaryArtifact } from './mediaWire';
import { useStream } from './stream';
import { rpc, RpcError } from "./rpc";
import { useUI, showError } from "./store";
import { getConnection, onCoreStatus } from "./native";
import { WIRE_SCHEMAS } from './wire.generated';
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
const MEDIA_CACHE_BYTES = 128 * 2 ** 20;
function reserveMedia(bytes: number, key: readonly unknown[]) {
  const cached = queries.getQueryCache().findAll({ queryKey: ['artifact'] })
    .filter(query => JSON.stringify(query.queryKey) !== JSON.stringify(key));
  let retained = cached.reduce((sum, query) => sum + ((query.state.data as BinaryArtifact | undefined)?.byteLength ?? 0), 0);
  for (const query of cached.sort((a, b) => a.state.dataUpdatedAt - b.state.dataUpdatedAt)) {
    if (retained + bytes <= MEDIA_CACHE_BYTES) break;
    if (!query.getObserversCount() && JSON.stringify(query.queryKey) !== JSON.stringify(key)) {
      retained -= (query.state.data as BinaryArtifact | undefined)?.byteLength ?? 0;
      queries.removeQueries({ queryKey: query.queryKey, exact: true });
    }
  }
  if (retained + bytes > MEDIA_CACHE_BYTES) throw new Error('Visible images exceed the 128 MiB view budget. Close an image pane or use a thumbnail.');
}
function showTurnOutcome(outcome: Params) {
  if (outcome.error)
    useUI.getState().set({ error: String(outcome.error),
      errorAction: outcome.reason === "provider_error" && outcome.retryable !== false ? "retry-turn" : null });
  else if (outcome.reason === "budget")
    useUI.getState().set({ error: "The agent reached the step limit for this turn. Send another message to continue, or raise Maximum steps per turn in Settings.", errorAction: null });
  else if (outcome.reason === "invalid_calls")
    useUI.getState().set({ error: "The agent stopped after repeated invalid tool calls. Check the failed steps, then send a clearer instruction or choose another model.", errorAction: null });
}
type QueryResult<K extends keyof MethodMap> = K extends "session.get" ? Session : MethodMap[K][1];
export function useCoreQuery<K extends keyof MethodMap>(method: K) {
  const ready = useUI((s) => s.status === "ready");
  return useQuery<QueryResult<K>>({
    queryKey: [method],
    queryFn: async ({ signal }) => {
      const value = await rpc.request(method, undefined, signal);
      if (method !== "session.get") return value as QueryResult<K>;
      const previous = queries.getQueryData<Session>(["session.get"]);
      const live = useStream.getState();
      const snapshot = reconcileSessionSnapshot(value as Session, previous
        ? { ...previous, stream_text: live.text, context: live.context ?? previous.context } : undefined);
      useStream.setState({ text: snapshot.stream_text ?? '', context: snapshot.context });
      const outcome = snapshot.last_turn_outcome;
      if (outcome && outcome.run_id !== previous?.last_turn_outcome?.run_id) showTurnOutcome(outcome);
      return { ...snapshot, stream_text: undefined } as QueryResult<K>;
    },
    enabled: ready,
  });
}
/** A snapshot can observe persistence before message.done reaches this socket. */
export function reconcileSessionSnapshot(
  snapshot: Session,
  previous?: Session,
): Session {
  if (previous?.context && snapshot.context &&
      previous.context.core_instance_id === snapshot.context.core_instance_id &&
      (snapshot.context.revision < previous.context.revision ||
       (snapshot.context.revision === previous.context.revision && snapshot.context.event_seq < previous.context.event_seq)))
    return previous;
  if (previous?.id !== snapshot.id || previous.context?.document_incarnation !== snapshot.context?.document_incarnation)
    return { ...snapshot, stream_text: snapshot.stream_text ?? "" };
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
    stream_text: !snapshot.turn_running ? "" : (snapshot.stream_text ?? (completedReply ? "" : previous.stream_text ?? "")),
  };
}
export function useSession() {
  return useCoreQuery("session.get");
}
export type DownloadActivities = Record<
  string,
  { pending: number; error?: string }
>;
function isPristineSession(session: Session) {
  return (
    !session.unsaved_changes &&
    !session.path &&
    session.name === "Untitled" &&
    !session.messages.length &&
    !session.steps.length &&
    !Object.keys(session.artifacts).length
  );
}
function acceptSessionReplacement(
  session: Session,
  preserveAutomaticDrafts = false,
) {
  const previous = queries.getQueryData<Session>(["session.get"]);
  const preserve =
    preserveAutomaticDrafts &&
    previous &&
    (previous.id === session.id ||
      (isPristineSession(previous) && isPristineSession(session)));
  const ui = useUI.getState();
  const selection = ui.selectedArtifact;
  const hasSelection = typeof selection === "string"
    ? !!session.artifacts[selection]
    : !!selection && session.steps.some((step) => step.invocation_id === selection.invocationId);
  queries.removeQueries({ queryKey: ["artifact"] });
  useStream.setState({ text: session.stream_text ?? '', context: session.context });
  queries.setQueryData<Session>(["session.get"], {
    ...session,
    stream_text: undefined,
  });
  ui.set({
    selectedStep:
      preserve && session.steps.some((step) => step.id === ui.selectedStep)
        ? ui.selectedStep
        : null,
    selectedArtifact: preserve && hasSelection ? selection : null,
    pick:
      preserve && ui.pick && session.artifacts[ui.pick.artifactId]
        ? ui.pick
        : null,
    ...(!preserve && {
      documentGeneration: ui.documentGeneration + 1,
      paletteOpen: false,
    }),
  });
}
export async function action<K extends keyof MethodMap>(
  method: K,
  params?: MethodMap[K][0],
  options?: { operationId: string },
): Promise<MethodMap[K][1]> {
  const documentGeneration = useUI.getState().documentGeneration;
  if (useUI.getState().status !== "ready")
    throw new Error(
      "Wait for the core to reconnect before running this action.",
    );
  const downloadName =
    method === "assets.download" && params && "name" in params
      ? String(params.name)
      : null;
  if (downloadName)
    queries.setQueryData<DownloadActivities>(["downloads"], (old) => ({
      ...old,
      [downloadName]: { pending: (old?.[downloadName]?.pending ?? 0) + 1 },
    }));
  let value: MethodMap[K][1];
  let downloadError: string | undefined;
  try {
    value = await rpc.request(method, params, undefined, queries.getQueryData<Session>(["session.get"])?.context,
      false, options?.operationId);
  } catch (error) {
    downloadError = error instanceof Error ? error.message : String(error);
    // A conflict is not permission to replay the command. Refresh the visible
    // document so the user can review its current state before trying again.
    if (error instanceof RpcError && error.code === -32002)
      await queries.invalidateQueries({ queryKey: ["session.get"] });
    throw error;
  } finally {
    if (downloadName) {
      const next = queries.setQueryData<DownloadActivities>(
        ["downloads"],
        (old) => ({
          ...old,
          [downloadName]: {
            pending: Math.max(0, (old?.[downloadName]?.pending ?? 1) - 1),
            ...(downloadError ? { error: downloadError } : {}),
          },
        }),
      );
      if (!next?.[downloadName]?.pending)
        queries.setQueryData<Params>(["progress", downloadName], (old) =>
          old ? { ...old, active: false } : old,
        );
    }
  }
  if (["session.new", "session.open", "session.restore", "branches.create", "branches.switch", "chat.undo", "history.undo", "history.redo"].includes(method)) {
    acceptSessionReplacement(value as Session);
  }
  const contract = WIRE_SCHEMAS.methods[method];
  if ((contract.scope === 'document' && contract.mutates) || method === 'providers.delete')
    await queries.invalidateQueries({ queryKey: ["session.get"] });
  if (method.startsWith("session.") || method.startsWith("projects."))
    await queries.invalidateQueries({ queryKey: ["projects.recent"] });
  if (method.startsWith("providers."))
    await queries.invalidateQueries({ queryKey: ["providers.list"] });
  if (method.startsWith("settings."))
    await queries.invalidateQueries({ queryKey: ["settings.get"] });
  if (method.startsWith("sources.") || method === "tools.run" || method.startsWith("session.") || method.startsWith("branches."))
    await queries.invalidateQueries({ queryKey: ["sources.status"] });
  if (method.startsWith("assets."))
    await queries.invalidateQueries({ queryKey: ["assets.status"] });
  if (method.startsWith("library.") || method.startsWith("packs.")) {
    await queries.invalidateQueries({ queryKey: ["library.page"] });
    await queries.invalidateQueries({ queryKey: ["library.list"] });
    queries.removeQueries({ queryKey: ["library.thumbnail"] });
  }
  if (method.startsWith("collections."))
    await queries.invalidateQueries({ queryKey: ["collections.list"] });
  if (method.startsWith("novelty."))
    await queries.invalidateQueries({ queryKey: ["novelty.recent"] });
  if (method.startsWith("branches.") || method.startsWith("session."))
    await queries.invalidateQueries({ queryKey: ["branches.list"] });
  if (method === "artifacts.import" && useUI.getState().documentGeneration !== documentGeneration)
    throw new Error("The session changed while importing the image. Import it again into the current session.");
  return value;
}
export function run<T>(work: () => Promise<T>) {
  void work().catch(showError);
}
export function applyCoreEvent({ method, params, context }: CoreEvent) {
  if (method === "core.resync") {
    void queries.invalidateQueries();
    return;
  }
  const current = queries.getQueryData<Session>(["session.get"]);
  const live = useStream.getState();
  if (context && current?.context) {
    const owner = current.context;
    if (owner.core_instance_id !== context.core_instance_id || context.revision < owner.revision ||
        context.event_seq <= owner.event_seq) return;
    if (live.context?.core_instance_id === context.core_instance_id &&
        live.context.document_incarnation === context.document_incarnation &&
        context.event_seq <= live.context.event_seq) return;
    if (owner.document_incarnation !== context.document_incarnation ||
        owner.document_id !== context.document_id || owner.branch_id !== context.branch_id) {
      // A core-owned AI checkpoint can change branches without a renderer action.
      void queries.invalidateQueries({ queryKey: ["session.get"] });
      return;
    }
    if (typeof params.run_id === "string" && current.run_id !== params.run_id) {
      void queries.invalidateQueries({ queryKey: ["session.get"] });
      return;
    }
    if (method !== 'message.delta') {
      queries.setQueryData<Session>(["session.get"], { ...current, context,
        document_revision: Math.max(current.document_revision, context.revision) });
      useStream.setState({ context });
    }
  }
  if (method === "message.delta") {
    if (current) useStream.setState({ text: live.text + String(params.text ?? ''), context });
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
      useUI
        .getState()
        .set({ error: String(params.message), errorAction: null });
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
      useStream.setState({ text: '' });
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
      useUI.getState().set({ error: null, errorAction: null });
      next.turn_running = true;
      useStream.setState({ text: '' });
    }
    if (method === "turn.finished") {
      next.turn_running = false;
      useStream.setState({ text: '' });
      showTurnOutcome(params);
    }
    return next;
  });
  if (method !== "message.done")
    void queries.invalidateQueries({ queryKey: ["session.get"] });
  if (["step.finished", "step.failed", "step.deleted"].includes(method))
    void queries.invalidateQueries({ queryKey: ["branches.list"] });
  if (method === "step.finished" || method === "step.deleted")
    void queries.invalidateQueries({ queryKey: ["sources.status"] });
}
export function startCore() {
  let disposed = false;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let generation = 0;
  let current: Connection | undefined;
  let failed = false;
  let recovering = false;
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
      recovering = restarted;
      useUI.getState().set({ logPath: next.log_path });
      await rpc.connect(next);
      if (disposed || thisGeneration !== generation) return;
      if (restarted) {
        // Keep the previous document and its drafts until recovery has an outcome.
        // Publishing the new core's empty startup session would discard attachments.
        const session = await rpc.request("session.get");
        const previous = queries.getQueryData<Session>(["session.get"]);
        if (!session.restorable && previous && !isPristineSession(previous))
          throw new Error(
            "The core restarted, but no autosaved session is available. Your previous session and drafts remain in this window. Restart the core or copy diagnostics before closing.",
          );
        const recovered = session.restorable
          ? await rpc.request("session.restore")
          : session;
        if (disposed || thisGeneration !== generation) return;
        acceptSessionReplacement(recovered, true);
      }
      current = next;
      attempt = 0;
      failed = false;
      recovering = false;
      useUI.getState().set({ status: "ready" });
      useStream.setState({ text: '', context: undefined });
      queries.setQueryData<Session>(["session.get"], (old) =>
        old ? { ...old, stream_text: "" } : old,
      );
      await queries.invalidateQueries();
    } catch (error) {
      if (disposed || thisGeneration !== generation) return;
      recovering = false;
      useUI.getState().set({ status: "disconnected" });
      schedule();
      if (attempt > 3) showError(error);
    }
  };
  const offStatus = rpc.onStatus((status) => {
    if (disposed || failed) return;
    if (status === "ready" && recovering) return;
    useUI.getState().set({ status });
    if (status === "disconnected") schedule();
  });
  const offEvents = rpc.onEvent(applyCoreEvent);
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
export function useArtifact(id: string | null, thumb = false, still = false, frame = 0) {
  const ready = useUI((s) => s.status === "ready");
  const meta = queries.getQueryData<Session>(['session.get'])?.artifacts[id!];
  const key = ["artifact", meta?.blob_id ?? id, thumb, still, frame, 'render-v1'];
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const renderFrame = () => rpc.media("artifacts.frame", { id: id!, frame, ...(thumb ? { max_px: 160 } : {}) }, signal);
      let payload = still || meta?.format === 'HEIF' ? await renderFrame()
        : await rpc.media('artifacts.get', { id: id!, ...(thumb ? { max_px: 160 } : {}) }, signal);
      if (payload.mime === 'image/heif') payload = await renderFrame();
      signal.throwIfAborted();
      reserveMedia(payload.byteLength, key);
      // Publish the reservation in the same synchronous turn. Concurrent query
      // completions must see these bytes before admitting their own payloads.
      queries.setQueryData(key, payload);
      return payload;
    },
    enabled: ready && !!id,
    staleTime: Infinity,
  });
  const [view, setView] = useState<{ blob: Blob; url: string }>();
  const blob = query.data?.blob;
  useEffect(() => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    setView({ blob, url });
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  const url = view?.blob === blob ? view?.url : undefined;
  return { ...query, data: query.data ? { ...query.data, meta: meta ?? query.data.meta, url } : undefined };
}
export function imageUrl(data: { mime: string; data?: string; url?: string } | undefined) {
  return data?.url ?? (data?.data !== undefined ? `data:${data.mime};base64,${data.data}` : undefined);
}
const MAX_PASTE_MIB = 47; // Matches MAX_PASTE_BYTES in the core and leaves room for the RPC envelope.

export async function readImportData(blob: Blob) {
  if (blob.size > MAX_PASTE_MIB * 2 ** 20) {
    throw new Error(
      `This file exceeds the ${MAX_PASTE_MIB} MiB upload limit. Use the desktop file picker or a smaller copy.`,
    );
  }
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function importBlob(blob: Blob, name = "pasted.png", source?: Artifact["source"]) {
  const generation = useUI.getState().documentGeneration;
  const data = await readImportData(blob);
  if (generation !== useUI.getState().documentGeneration)
    throw new Error("The session changed while reading the image. Import it again into the current session.");
  return action("artifacts.import", { data, name, ...(source ? { source } : {}) });
}
