import { useState } from "react";
import { action, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import type { Params } from "../types";
import { ToolForm } from "./ToolForm";

const choices = [
  { label: "Crop / resize / rotate / flip", name: "transform", params: {} },
  { label: "Text", name: "text", params: {} },
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
        initial={{ image, ...choice.params }} disabled={session?.turn_running}
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
