import { action, useCoreQuery, useSession } from "../data";
import { outputSelection, useUI } from "../store";
import type { Params } from "../types";
import { ToolForm } from "./ToolForm";

export const manualChoices = [
  { label: "Text", name: "text", params: { preserve_case: true, preserve_line_breaks: true, fit_exact: true, font: "bundled" } },
  { label: "Cutout", name: "cutout", params: {} },
  { label: "Compose", name: "paste", params: {} },
  { label: "Transform", name: "transform", params: {} },
  { label: "Edit GIF frames", name: "animation_edit", params: {} },
] satisfies { label: string; name: string; params: Params }[];

export function ManualTools({ image, choice, onClose }: {
  image: string | null;
  choice: (typeof manualChoices)[number];
  onClose: (applied?: boolean) => void;
}) {
  const { data: tools } = useCoreQuery("tools.list");
  const { data: session } = useSession();
  const tool = tools?.find(item => item.name === choice.name);
  const roles = session?.creative?.source_roles;
  const original = image ? session?.artifacts[image]?.original_id : null;
  const input = choice.name === "animation_edit" && original && (session?.artifacts[original]?.frames ?? 1) > 1
    ? original : image;
  const subject = roles?.subject && session?.artifacts[roles.subject] ? roles.subject : undefined;
  const background = roles?.background && session?.artifacts[roles.background] ? roles.background : undefined;
  const initial = choice.name === "paste" ? {
    base: background,
    piece: subject !== background ? subject : undefined,
    at: [0, 0],
    ...(background ? { width: Math.max(1, Math.round(session!.artifacts[background].width / 2)) } : {}),
  } : { ...(input && { image: input }), ...choice.params };
  return <section className="manual-tools task-pane pane" aria-label={choice.label}>
    <div className="pane-heading"><h2>{choice.label}</h2><button type="button" onClick={() => onClose()}>Close tool</button></div>
    {tool && <ToolForm key={choice.name} tool={tool} initial={initial} disabled={session?.turn_running || session?.batch_running}
      imageLabels={choice.name === "paste" ? { base: "Background", piece: "Subject" } : undefined}
      previewEnabled submitLabel={`Apply ${choice.label.toLowerCase()}`} onSubmit={async params => {
        const step = await action("tools.run", { tool: tool.name, params });
        if (step.status !== "done") throw new Error(step.error?.message ?? "Manual tool failed");
        useUI.getState().set({ selectedStep: step.id, selectedArtifact: outputSelection(step) });
        onClose(true);
      }} />}
  </section>;
}
