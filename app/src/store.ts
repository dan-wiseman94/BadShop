import { create } from "zustand";
import type { Session, Step } from "./types";
import { readPreference, validTheme, type Density, type Motion } from "./appearance";
export type PickRequest = {
  kind: "point" | "box" | "segment";
  artifactId: string;
  label?: string;
  complete: (value: number[]) => void;
};
export type SelectedElement = { id: string; stepId: string; label: string; slotIndex?: number; focusText?: number };
interface UIState {
  status: "starting" | "connecting" | "ready" | "disconnected" | "failed";
  logPath?: string;
  selectedStep: string | null;
  selectedElement: SelectedElement | null;
  selectedArtifact: string | { invocationId: string; outputKey: string } | null;
  viewerBefore: boolean;
  viewerZoom: "fit" | number;
  documentGeneration: number;
  chatDraft: string;
  setChatDraft: (value: string | ((previous: string) => string)) => void;
  settingsOpen: boolean;
  settingsAssets: boolean;
  paletteOpen: boolean;
  automaticPreview: boolean;
  canvasDraft: { key: string; source: string; scope: "step" | "final"; revision: number } | null;
  pick: PickRequest | null;
  error: string | null;
  errorAction: "retry-turn" | null;
  errorOperationId: string | null;
  notice: string | null;
  theme: string;
  density: Density;
  textScale: number;
  motion: Motion;
  set: (patch: Partial<UIState>) => void;
}
export const useUI = create<UIState>()((set) => ({
  status: "starting",
  selectedStep: null,
  selectedElement: null,
  selectedArtifact: null,
  viewerBefore: false,
  viewerZoom: "fit",
  documentGeneration: 0,
  chatDraft: "",
  setChatDraft: (value) => set(state => ({ chatDraft: typeof value === "function" ? value(state.chatDraft) : value })),
  settingsOpen: false,
  settingsAssets: false,
  paletteOpen: false,
  canvasDraft: null,
  automaticPreview: readPreference("automaticPreview", "on") !== "off",
  pick: null,
  error: null,
  errorAction: null,
  errorOperationId: null,
  notice: null,
  theme: validTheme(readPreference("theme", "system")),
  density: readPreference("density", "comfortable") === "compact" ? "compact" : "comfortable",
  textScale: [100, 115, 130, 150, 175, 200].includes(Number(readPreference("textScale", "100"))) ? Number(readPreference("textScale", "100")) : 100,
  motion: ["reduced", "full"].includes(readPreference("motion", "system")) ? readPreference("motion", "system") as Motion : "system",
  set: (patch) => set({
    ...(patch.settingsOpen === false && { settingsAssets: false }),
    ...(("selectedArtifact" in patch || "selectedStep" in patch) && { viewerBefore: false, selectedElement: null, canvasDraft: null }),
    ...("documentGeneration" in patch && { canvasDraft: null, viewerZoom: "fit" as const, chatDraft: "" }),
    ...patch,
  }),
}));
export function outputSelection(step: Step, artifactId = step.outputs[0]): UIState['selectedArtifact'] {
  const outputKey = Object.entries(step.output_ports ?? {}).find(([, id]) => id === artifactId)?.[0];
  return outputKey && step.invocation_id ? { invocationId: step.invocation_id, outputKey } : artifactId ?? null;
}
// A missing named output stays unresolved; another port must never replace it silently.
export function useSelectedArtifact(steps: Step[] | undefined) {
  return useUI(({ selectedArtifact }) => {
    if (!selectedArtifact || typeof selectedArtifact === "string") return selectedArtifact;
    const step = steps?.find(item => item.invocation_id === selectedArtifact.invocationId);
    const output = step?.output_ports?.[selectedArtifact.outputKey];
    if (output) return output;
    // Pre-v6 files synthesized ordinal aliases. The first replay migrates the
    // port names using that same ordinal. Real named ports never fall back.
    const migrated = /^legacy:(\d+)$/.exec(selectedArtifact.outputKey);
    return migrated && step && !Object.keys(step.output_ports ?? {}).some(key => key.startsWith("legacy:"))
      ? step.outputs[Number(migrated[1])] ?? null : null;
  });
}
/** The canvas and manual controls must agree on the image currently being inspected. */
export function useCanvasArtifact(session: Session | undefined) {
  const selectedStep = useUI((state) => state.selectedStep);
  const selectedArtifact = useSelectedArtifact(session?.steps);
  const explicitSelection = useUI(state => state.selectedArtifact !== null);
  const before = useUI((state) => state.viewerBefore);
  const selected = session?.steps.find((step) => step.id === selectedStep);
  const artifacts = Object.values(session?.artifacts ?? {});
  const finalStep = session?.steps.slice().reverse().find(step => step.status === "done" && step.outputs.length);
  const lastSavedStep = session?.steps.slice().reverse().find(step =>
    step.status !== "rejected" && (step.outputs.length || step.previous_outputs?.length));
  const lastOutput = lastSavedStep?.outputs[0] ?? lastSavedStep?.previous_outputs?.[0];
  const afterId = explicitSelection ? selectedArtifact : selected?.outputs[0] ?? selected?.previous_outputs?.[0] ??
    lastOutput ?? artifacts.slice().reverse().find(artifact => artifact.original_id && !artifact.produced_by)?.id ??
    artifacts.find(artifact => !artifact.produced_by)?.id ?? null;
  const inputId = afterId && selected?.outputs.includes(afterId)
    ? Object.values(selected.params)
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .find((value): value is string => typeof value === "string" && !!session?.artifacts[value])
    : undefined;
  const producer = session?.steps.slice().reverse().find(step => !!afterId &&
    (step.outputs.includes(afterId) || step.previous_outputs?.includes(afterId)));
  const outputKey = Object.entries(producer?.output_ports ?? {}).find(([, id]) => id === afterId)?.[0];
  const interrupted = !!session?.steps.some(step => step.index >= (producer?.index ?? 0) &&
    (step.status === "stale" || step.status === "error"));
  const kind = before && inputId ? "before" : explicitSelection && !afterId ? "missing"
    : !afterId ? "empty" : !producer ? "source"
      : interrupted && (afterId === lastOutput || producer.status === "stale" || producer.status === "error") ? "last_saved"
      : afterId === finalStep?.outputs[0] && !interrupted ? "final" : "earlier";
  return { id: before && inputId ? inputId : afterId, inputId, kind, producer, outputKey, explicitSelection };
}
export function showError(
  error: unknown,
  errorAction: "retry-turn" | null = null,
) {
  useUI.getState().set({
    errorAction,
    errorOperationId: error instanceof Error && 'operationId' in error && typeof error.operationId === 'string'
      ? error.operationId : null,
    error:
      error instanceof Error
        ? error.message === "no model provider is set up yet"
          ? "Choose a model provider in Settings to start chatting."
          : error.message +
            ("hint" in error && error.hint ? ` ${error.hint}` : "")
        : String(error),
  });
}
