import { useEffect, useState } from "react";

export const themes = [
  {
    id: "system",
    name: "Follow system",
    description: "Match your desktop",
    colors: ["#24252b", "#bbb0ed", "#e9e9ef"],
  },
  {
    id: "dark",
    name: "Dark",
    description: "The original workbench",
    colors: ["#24252b", "#bbb0ed", "#e9e9ef"],
  },
  {
    id: "light",
    name: "Light",
    description: "A bright workbench",
    colors: ["#eff0f5", "#7863b1", "#292b38"],
  },
  {
    id: "classic",
    name: "Classic Desktop",
    description: "Beveled buttons and blue title bars",
    colors: ["#008080", "#000080", "#c0c0c0"],
  },
  {
    id: "terminal",
    name: "Terminal",
    description: "Phosphor green, monospace, sharp edges",
    colors: ["#07130d", "#8fffa8", "#163622"],
  },
  {
    id: "geocities",
    name: "GeoCities",
    description: "Midnight blue, yellow links and pixel stars",
    colors: ["#080c38", "#ffff66", "#a0e8ff"],
  },
  {
    id: "y2k",
    name: "Y2K",
    description: "Silver panels and electric violet",
    colors: ["#dfe5f4", "#5132ac", "#00bfd6"],
  },
  {
    id: "paper",
    name: "Paper",
    description: "Cream paper, ink and editorial rules",
    colors: ["#f3ebd8", "#724d27", "#27231e"],
  },
  {
    id: "arcade",
    name: "Arcade",
    description: "Deep purple with neon cabinet trim",
    colors: ["#160f2a", "#f5a4ef", "#70e7ee"],
  },
] as const;
export type Density = "comfortable" | "compact";
export type Motion = "system" | "reduced" | "full";
export function readPreference(key: string, fallback: string): string {
  try {
    return localStorage.getItem(`badshop.${key}`) ?? fallback;
  } catch {
    return fallback;
  }
}
export function savePreference(key: string, value: string) {
  // Apply for this window even when the browser disables local storage.
  try {
    localStorage.setItem(`badshop.${key}`, value);
  } catch {
    /* session-only preference */
  }
}
export function validTheme(value: string) {
  return themes.some((t) => t.id === value) ? value : "system";
}
export function useReducedMotion(preference: Motion): boolean {
  const [system, setSystem] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setSystem(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);
  return preference === "reduced" || (preference === "system" && system);
}
