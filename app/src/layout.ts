import { useEffect, useState } from "react";

export const paneDefaults = { left: 318, right: 316 };
const minimum = { left: 260, right: 270 };
type Widths = typeof paneDefaults;

export function fitPanes(preferred: Widths, contentWidth: number): Widths {
  const budget = Math.max(530, contentWidth - 12 - 250);
  const left = Math.max(minimum.left, preferred.left);
  const right = Math.max(minimum.right, preferred.right);
  if (left + right <= budget) return { left, right };
  const extra = left + right - 530;
  const remaining = budget - 530;
  const fittedLeft =
    minimum.left + (extra ? ((left - minimum.left) * remaining) / extra : 0);
  return { left: fittedLeft, right: budget - fittedLeft };
}

export function usePaneLayout() {
  const [workbench, setWorkbench] = useState<HTMLElement | null>(null);
  const [contentWidth, setContentWidth] = useState(window.innerWidth - 32);
  const [preferred, setPreferred] = useState<Widths>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("badshop.panes") ?? "null");
      if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.right))
        return {
          left: Math.min(10000, Math.max(260, saved.left)),
          right: Math.min(10000, Math.max(270, saved.right)),
        };
    } catch {
      /* A missing or stale preference uses the default layout. */
    }
    return paneDefaults;
  });
  const widths = fitPanes(preferred, contentWidth);
  useEffect(() => {
    if (!workbench) return;
    const observer = new ResizeObserver(([entry]) =>
      setContentWidth(entry.contentRect.width),
    );
    observer.observe(workbench);
    return () => observer.disconnect();
  }, [workbench]);
  useEffect(() => {
    try {
      localStorage.setItem("badshop.panes", JSON.stringify(preferred));
    } catch {
      /* Layout remains usable when preference storage is unavailable. */
    }
  }, [preferred]);
  const resize = (side: keyof Widths, delta: number) => {
    const other = side === "left" ? "right" : "left";
    const maximum = contentWidth - 262 - widths[other];
    setPreferred({
      ...widths,
      [side]: Math.max(minimum[side], Math.min(maximum, widths[side] + delta)),
    });
  };
  return {
    workbench: setWorkbench,
    widths,
    resize,
    reset: () => setPreferred(paneDefaults),
    contentWidth,
  };
}
