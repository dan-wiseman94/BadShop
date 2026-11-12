import { create } from "zustand";
import type { Session, Step } from "./types";
import { readPreference, validTheme, type Density, type Motion } from "./appearance";
export type PickRequest = {
  kind: "point" | "box" | "segment";
  artifactId: string;
  label?: string;
  complete: (value: number[]) => void;
};
interface UIState {
  status: "starting" | "connecting" | "ready" | "disconnected" | "failed";
  logPath?: string;
  selectedStep: string | null;
  selectedArtifact: string | { stepId: string; outputIndex: number } | null;
  viewerBefore: boolean;
  viewerZoom: "fit" | number;
  documentGeneration: number;
  settingsOpen: boolean;
  paletteOpen: boolean;
  pick: PickRequest | null;
  error: string | null;
  errorAction: "retry-turn" | null;
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
  selectedArtifact: null,
  viewerBefore: false,
  viewerZoom: "fit",
  documentGeneration: 0,
  settingsOpen: false,
  paletteOpen: false,
  pick: null,
  error: null,
  errorAction: null,
  notice: null,
  theme: validTheme(readPreference("theme", "system")),
  density: readPreference("density", "comfortable") === "compact" ? "compact" : "comfortable",
  textScale: [100, 115, 130, 150, 175, 200].includes(Number(readPreference("textScale", "100"))) ? Number(readPreference("textScale", "100")) : 100,
  motion: ["reduced", "full"].includes(readPreference("motion", "system")) ? readPreference("motion", "system") as Motion : "system",
  set: (patch) => set({
    ...(("selectedArtifact" in patch || "selectedStep" in patch) && { viewerBefore: false }),
    ...("documentGeneration" in patch && { viewerZoom: "fit" as const }),
    ...patch,
  }),
}));
// A timeline output follows its slot when replay replaces the underlying bytes.
export function useSelectedArtifact(steps: Step[] | undefined) {
  return useUI(({ selectedArtifact }) => {
    if (!selectedArtifact || typeof selectedArtifact === "string") return selectedArtifact;
    const outputs = steps?.find((step) => step.id === selectedArtifact.stepId)?.outputs;
    return outputs?.[selectedArtifact.outputIndex] ?? outputs?.[0] ?? null;
  });
}
/** The canvas and manual controls must agree on the image currently being inspected. */
export function useCanvasArtifact(session: Session | undefined) {
  const selectedStep = useUI((state) => state.selectedStep);
  const selectedArtifact = useSelectedArtifact(session?.steps);
  const before = useUI((state) => state.viewerBefore);
  const selected = session?.steps.find((step) => step.id === selectedStep);
  const artifacts = Object.values(session?.artifacts ?? {});
  const afterId = selectedArtifact ?? selected?.outputs[0] ??
    session?.steps.slice().reverse().find((step) => step.outputs.length)?.outputs[0] ??
    artifacts.find((artifact) => artifact.original_id)?.id ?? artifacts[0]?.id ?? null;
  const inputId = afterId && selected?.outputs.includes(afterId)
    ? Object.values(selected.params)
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .find((value): value is string => typeof value === "string" && !!session?.artifacts[value])
    : undefined;
  return { id: before && inputId ? inputId : afterId, inputId };
}
export function showError(
  error: unknown,
  errorAction: "retry-turn" | null = null,
) {
  useUI.getState().set({
    errorAction,
    error:
      error instanceof Error
        ? error.message === "no model provider is set up yet"
          ? "Choose a model provider in Settings to start chatting."
          : error.message +
            ("hint" in error && error.hint ? ` ${error.hint}` : "")
        : String(error),
  });
}
