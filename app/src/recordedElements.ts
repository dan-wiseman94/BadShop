import type { Session, Step } from "./types";

type Element = {
  id: string;
  step: Step;
  label: string;
  box: number[];
  slotIndex?: number;
  captionBox?: number[];
};
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
      const layout = step.data?.layout as { slots?: { box: unknown; caption_box?: unknown; name?: string }[] } | undefined;
      const slots = layout?.slots ?? [];
      const captions = Array.isArray(step.params.captions) ? step.params.captions : [];
      for (let slotIndex = slots.length - 1; slotIndex >= 0; slotIndex--) {
        const slot = slots[slotIndex];
        if (!bounds(slot.box)) continue;
        const name = slot.name || `Slot ${slotIndex + 1}`;
        const duplicateName = slots.some((other, index) => index !== slotIndex && other.name === slot.name);
        const caption = captions[slotIndex];
        const captionBox = typeof caption === "string" && caption.trim() && bounds(slot.caption_box)
          ? slot.caption_box : undefined;
        result.push({
          id: `${step.invocation_id ?? step.id}:slot:${slotIndex}`,
          step,
          label: duplicateName ? `Layout: ${name} (slot ${slotIndex + 1})` : `Layout: ${name}`,
          box: slot.box,
          slotIndex,
          captionBox,
        });
      }
      break;
    }
    if (!["paste", "text"].includes(step.tool)) break;
    const box = step.data?.element_bounds;
    if (bounds(box)) result.push({
      id: step.invocation_id ?? step.id,
      step,
      label: step.tool === "text" ? `Caption: ${String(step.params.text)}` : `Picture: step ${step.index}`,
      box,
    });
    const source: unknown = step.params[step.tool === "paste" ? "base" : "image"];
    id = typeof source === "string" ? source : null;
  }
  return result.reverse();
}
