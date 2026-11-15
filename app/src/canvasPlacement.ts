import { createContext, type RefObject } from "react";
import type { Params } from "./types";

export type CanvasPlacement = {
  stepId: string;
  draft: Params;
  moveBy: (x: number, y: number) => void;
};

export const CanvasPlacementContext = createContext<RefObject<CanvasPlacement | null> | null>(null);
