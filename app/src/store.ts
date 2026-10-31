import { create } from "zustand";
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
  settingsOpen: boolean;
  paletteOpen: boolean;
  pick: PickRequest | null;
  error: string | null;
  errorAction: "retry-turn" | null;
  notice: string | null;
  theme: string;
  set: (patch: Partial<UIState>) => void;
}
export const useUI = create<UIState>()((set) => ({
  status: "starting",
  selectedStep: null,
  selectedArtifact: null,
  settingsOpen: false,
  paletteOpen: false,
  pick: null,
  error: null,
  errorAction: null,
  notice: null,
  theme: localStorage.getItem("badshop.theme") ?? "system",
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
