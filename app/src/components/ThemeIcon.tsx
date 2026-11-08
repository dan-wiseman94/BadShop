import { useId } from "react";
import { Download, FolderOpen, Images, MousePointer2, Plus, RotateCcw, Save, Settings2, X } from "lucide-react";
import { useUI } from "../store";

// Hand-drawn 16px silhouettes, plus print and gel treatments for the same actions.
// These decorate existing controls; labels, shortcuts and behavior stay with the caller.
const icons = {
  save: {
    modern: Save, command: ":w",
    silhouette: "M1 1h12l2 2v12H1Z",
    color: "M2 2h10v2h2v10H2Z",
    detail: "M4 2h6v4H4ZM4 9h8v5H4Z",
    ink: "M8 2h2v3H8ZM5 10h6v1H5ZM5 12h6v1H5Z",
    gel: "M4 3h13l3 3v15H4ZM8 3v6h8V3M8 21v-8h8v8M13 5v2",
    print: "M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3ZM12 6v16M6 8h3M6 11h3M6 14h3M15 8h3M15 11h3M15 14h3",
  },
  open: {
    modern: FolderOpen, command: "./",
    silhouette: "M0 3h6l2 2h7v3h1v3h-1v3H0Z",
    color: "M1 4h4l2 2h7v2H3l-2 4ZM4 9h11v2h-1v2H2Z",
    detail: "M1 4h4v1H1ZM4 9h10v1H4Z", ink: "",
    gel: "M3 7V4h6l3 3h8v4M3 7v13h16l3-10H6L3 20",
    print: "M2 7V4h6l3 3h10v3M2 7v13h17l3-10H6L2 20M5 16l2-4M8 17l1-3",
  },
  images: {
    modern: Images, command: "[]",
    silhouette: "M0 3h3V0h13v13h-3v3H0Z",
    color: "M1 4h2v9h9v2H1ZM4 1h11v11H4Z",
    detail: "M5 2h9v9H5Z",
    ink: "M5 9h1V7h2v1h1V6h2v2h1v1h2v2H5ZM11 3h2v2h-2Z",
    gel: "M7 3h14v14H7ZM3 7v14h14M7 14l4-5 3 3 3-3 4 5M16 6h1",
    print: "M3 4h18v16H3ZM5 6h14v12H5ZM5 15l5-6 4 5 2-2 3 4M15 8h1M3 22h18",
  },
  settings: {
    modern: Settings2, command: "#",
    silhouette: "M6 0h4v2h2V1h2v3h-1v2h3v4h-3v2h1v3h-2v-1h-2v2H6v-2H4v1H2v-3h1v-2H0V6h3V4H2V1h2v1h2Z",
    color: "M6 3h4v1h2v2h1v4h-1v2h-2v1H6v-1H4v-2H3V6h1V4h2Z",
    detail: "M6 5h4v1h1v4h-1v1H6v-1H5V6h1Z",
    ink: "M7 6h2v4H7ZM6 7h4v2H6Z",
    gel: "M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6",
    print: "M10 2h4l1 4 3-1 3 3-2 4 2 3-3 3-3-1-1 4h-4l-1-4-3 1-3-3 2-3-2-4 3-3 3 1ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 10v4M10 12h4",
  },
  export: {
    modern: Download, command: ">>",
    silhouette: "M6 0h4v6h4v2h-2v2h-2v2H6v-2H4V8H2V6h4ZM0 11h3v2h10v-2h3v5H0Z",
    color: "M7 1h2v6h3v1h-2v2H9v1H7v-1H6V8H4V7h3ZM1 12h1v2h12v-2h1v3H1Z",
    detail: "M7 1h1v6H7ZM1 14h14v1H1Z", ink: "",
    gel: "M12 3v12M7 10l5 5 5-5M4 14v7h16v-7",
    print: "M2 8h20v13H2ZM2 9l10 7L22 9M3 20l6-6M21 20l-6-6M9 3h10M16 1l3 2-3 2",
  },
  canvas: {
    modern: MousePointer2, command: "+",
    silhouette: "M2 0h2v2h2v2h2v2h2v2h2v2H8v1h1v2h1v3H7v-2H6v-2H5v-1H4v2H2Z",
    color: "M3 2h1v1h2v2h2v2h2v2H7v2h1v2h1v2H8v-2H7v-2H5V9H4v2H3Z",
    detail: "M3 2h1v7H3Z", ink: "",
    gel: "M5 2v18l5-5 4 7 3-2-4-7h8Z",
    print: "M4 21l4-12L19 2l3 3-7 11ZM4 21l9-9M11 10a2 2 0 1 0 4 0 2 2 0 0 0-4 0M1 23h13",
  },
  tools: {
    modern: Plus, command: "/>",
    silhouette: "M5 1h6v3h5v11H0V4h5ZM7 3v1h2V3Z",
    color: "M1 5h14v9H1Z",
    detail: "M1 5h14v2H1ZM6 7h4v3H6Z",
    ink: "M1 8h5v1H1ZM10 8h5v1h-5ZM7 8h2v1H7Z",
    gel: "M3 7h18v14H3ZM8 7V3h8v4M3 12h18M10 10v5h4v-5",
    print: "M8 14L21 3M9 17L21 21M8 16L18 4M5 13a4 4 0 1 0 0 8 4 4 0 0 0 0-8M5 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M8 9l4 5",
  },
  replay: {
    modern: RotateCcw, command: "^R",
    silhouette: "M3 0v3h2V2h6v1h2v2h2v6h-2v2h-2v2H5v-1H3v-3h3v1h4v-1h1v-1h1V6h-1V5H6v1H5v1h2v2H0V0Z",
    color: "M1 2h1v3h3V4h1V3h4v1h2v2h2v4h-1v2h-3v2H6v-1H4v-1h1v1h5v-1h1v-1h2V6h-2V4H6v1H5v1H3v1h3v1H1Z",
    detail: "", ink: "",
    gel: "M3 3v6h6M3 9a9 9 0 1 1 0 8",
    print: "M3 3v6h6M3 9a9 9 0 1 1 0 8M19 17l-2-1M18 19l-2-2M15 20l-1-2",
  },
  close: {
    modern: X, command: "X",
    silhouette: "M1 1h3v1h1v2h2v2h2V4h2V2h1V1h3v3h-1v1h-2v2h-2v2h2v2h2v1h1v3h-3v-1h-1v-2H9v-2H7v2H5v2H4v1H1v-3h1v-1h2V9h2V7H4V5H2V4H1Z",
    color: "M2 2h1v1h1v2h2v2h2v2H6v2H4v2H3v1H2v-1h1v-2h2V9h2V7H5V5H3V3H2ZM12 2h2v1h-1v2h-2v2H9V6h1V4h2ZM9 9h1v1h1v1h2v2h1v1h-2v-2h-2v-2H9Z",
    detail: "", ink: "",
    gel: "M7 7l10 10M17 7L7 17",
    print: "M5 5l14 14M19 5L5 19M4 5l1-1M18 19l1-1M4 19l1 1M18 5l1 1",
  },
};
export type ThemeIconName = keyof typeof icons;

export function ThemeIcon({ name, size = 18, theme }: { name: ThemeIconName; size?: number; theme?: string }) {
  const selected = useUI(state => state.theme);
  const skin = theme ?? selected;
  const id = useId();
  const icon = icons[name];
  const props = { width: size, height: size, "aria-hidden": true as const, focusable: false as const };
  if (!["classic", "terminal", "geocities", "y2k", "paper", "arcade"].includes(skin)) {
    const Modern = icon.modern;
    return <Modern {...props} />;
  }
  return <svg {...props} className="theme-icon" data-icon={name} data-icon-skin={skin} viewBox={skin === "paper" || skin === "y2k" ? "0 0 24 24" : "0 0 16 16"}>
    {skin === "terminal" ? <text x="8" y="12" textAnchor="middle">{icon.command}</text>
      : skin === "paper" ? <path className="icon-print" d={icon.print} />
      : skin === "y2k" ? <>
        <defs>
          <linearGradient id={id} x2="0" y2="1">
            <stop stopColor="#f8ffff" /><stop offset=".45" stopColor="#accbfa" />
            <stop offset=".5" stopColor="#526bba" /><stop offset="1" stopColor="#b9eeff" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="22" height="22" rx="6" fill={`url(#${id})`} stroke="#4e5a8a" />
        <path d="M5 3h14" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" />
        <path className="icon-gel" d={icon.gel} transform="translate(4 4) scale(.66)" />
      </> : <g shapeRendering="crispEdges">
        <path className="icon-outline" d={icon.silhouette} />
        <path className="icon-color" d={icon.color} />
        <path className="icon-detail" d={icon.detail} />
        <path className="icon-ink" d={icon.ink} />
      </g>}
  </svg>;
}
