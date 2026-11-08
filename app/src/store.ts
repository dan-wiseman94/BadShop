import { create } from "zustand";
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
  selectedArtifact: string | null;
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
  set: (patch) => set(patch),
}));
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
