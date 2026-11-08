import { useEffect, useState } from "react";

export const themes = [
  {
    id: "system",
    name: "Follow system",
    description: "Match your desktop",
    era: "Your desktop",
  },
  {
    id: "dark",
    name: "Dark",
    description: "Charcoal, acid yellow, hard edges. The BadShop workbench.",
    era: "Cut · Paste · Repeat",
  },
  {
    id: "light",
    name: "Light",
    description: "Warm stock, black ink, yellow labels. Lights on in the shop.",
    era: "Cut · Paste · Repeat",
  },
  {
    id: "classic",
    name: "Classic Desktop",
    description: "Teal desktop, battleship gray, proper raised buttons.",
    era: "1995 · Personal computer",
  },
  {
    id: "terminal",
    name: "Terminal",
    description: "Green phosphor, command prompts, wireframe panels.",
    era: "1982 · After hours",
  },
  {
    id: "geocities",
    name: "GeoCities",
    description: "Starfield wallpaper, hot links, gratuitous yellow.",
    era: "1997 · My homepage",
  },
  {
    id: "y2k",
    name: "Y2K",
    description: "Liquid chrome, violet gel, the future on CD-ROM.",
    era: "2001 · Digital playground",
  },
  {
    id: "paper",
    name: "Paper",
    description: "Letterpress headlines, ruled columns, red printer’s ink.",
    era: "1932 · Evening edition",
  },
  {
    id: "arcade",
    name: "Arcade",
    description: "Electric marquees, chunky controls, one more credit.",
    era: "1988 · Insert coin",
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
