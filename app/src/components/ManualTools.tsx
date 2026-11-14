import { useState } from "react";
import { action, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import type { Params } from "../types";
import { ToolForm } from "./ToolForm";

const choices = [
  { label: "Edit GIF frames", name: "animation_edit", params: {} },
  { label: "Cut out / repair selection", name: "cutout", params: {} },
  { label: "Crop / resize / rotate / flip", name: "transform", params: {} },
  { label: "Text", name: "text", params: { preserve_case: true, preserve_line_breaks: true, fit_exact: true, font: "bundled" } },
  { label: "Compose subject on background", name: "paste", params: {} },
  { label: "Arrows & shapes", name: "draw", params: {} },
  { label: "Censor", name: "censor", params: {} },
] satisfies { label: string; name: string; params: Params }[];

export function ManualTools({ image }: { image: string }) {
  const [choice, setChoice] = useState<(typeof choices)[number] | null>(null);
  const { data: tools } = useCoreQuery("tools.list");
  const { data: session } = useSession();
  const tool = tools?.find((item) => item.name === choice?.name);
  return <details className="manual-tools">
    <summary>Manual tools</summary>
    <div role="group" aria-label="Basic manual tools">
      {choices.map((item) => <button key={item.label} type="button"
        disabled={session?.turn_running || !tools} onClick={() => setChoice(item)}>{item.label}</button>)}
    </div>
    {tool && choice && <div>
      <h3>{choice.label}</h3>
      <ToolForm key={`${image}-${choice.name}`} tool={tool}
        initial={choice.name === "paste" ? {
          base: session?.creative?.source_roles.background ?? image,
          piece: session?.creative?.source_roles.subject ?? image,
          at: [0, 0],
          width: Math.max(1, Math.round((session?.artifacts[session?.creative?.source_roles.background ?? image]?.width ?? 400) / 2)),
        } : { image: choice.name === "animation_edit" && session?.artifacts[image]?.original_id
          ? session.artifacts[image].original_id : image, ...choice.params }} disabled={session?.turn_running}
        submitLabel={`Apply ${choice.label.toLowerCase()}`}
        onSubmit={async (params) => {
          const step = await action("tools.run", { tool: tool.name, params });
          if (step.status === "error") throw new Error(step.error?.message ?? "Manual tool failed");
          useUI.getState().set({ selectedStep: step.id,
            selectedArtifact: step.outputs.length ? { stepId: step.id, outputIndex: 0 } : null });
          setChoice(null);
        }} />
      <button type="button" onClick={() => setChoice(null)}>Close manual tool</button>
    </div>}
  </details>;
}
