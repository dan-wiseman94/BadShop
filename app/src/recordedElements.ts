import type { Session, Step } from "./types";

type Element = { step: Step; label: string; box: number[] };
const bounds = (value: unknown): value is number[] => Array.isArray(value) && value.length === 4 &&
  value.every(item => typeof item === "number" && Number.isFinite(item)) && value[2] > value[0] && value[3] > value[1];

/** Follow composition edges with unchanged coordinates. Unknown transforms stop selection. */
export function recordedElements(session: Session | undefined, artifact: string | null): Element[] {
  const result: Element[] = [];
  const visited = new Set<string>();
  let id = artifact;
  while (id && !visited.has(id)) {
    visited.add(id);
    const step: Step | undefined = session?.steps.slice().reverse().find(item => item.status === "done" && item.outputs.includes(id!));
    if (!step || step.bypassed) break;
    if (step.tool === "layout") {
      const layout = step.data?.layout as { slots?: { box: unknown; name: string }[] } | undefined;
      for (const slot of layout?.slots ?? []) {
        if (bounds(slot.box)) result.push({ step, label: `Layout: ${slot.name}`, box: slot.box });
      }
      break;
    }
    if (!["paste", "text"].includes(step.tool)) break;
    const box = step.data?.element_bounds;
    if (bounds(box)) result.push({ step, label: step.tool === "text" ? `Caption: ${String(step.params.text)}` : `Picture: step ${step.index}`, box });
    const source: unknown = step.params[step.tool === "paste" ? "base" : "image"];
    id = typeof source === "string" ? source : null;
  }
  return result.reverse();
}
