import { useState } from "react";
import { action, queries } from "../data";
import { useUI } from "../store";
import type { Params, Session, Step } from "../types";
import { Button } from "./Button";

export function ProposalPreview({ step, revision, params }: { step: Step; revision: number; params?: Params }) {
  const paramsKey = JSON.stringify(params);
  const [preview, setPreview] = useState<{ images: string[]; revision: number; paramsKey?: string } | null>(null);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const generation = useUI(state => state.documentGeneration);
  async function renderProposal() {
    if (!step.invocation_id || pending) return;
    setPending(true);
    setMessage("");
    setPreview(null);
    try {
      const result = await action("approval.preview", {
        step_id: step.id, invocation_id: step.invocation_id, expected_revision: revision, params,
      });
      const current = queries.getQueryData<Session>(["session.get"]);
      if (useUI.getState().documentGeneration === generation && current?.document_revision === result.revision &&
          current.pending_approvals.includes(step.id) && result.invocation_id === step.invocation_id)
        setPreview({ ...result, paramsKey });
    } catch (error) {
      const current = queries.getQueryData<Session>(["session.get"]);
      if (current?.pending_approvals.includes(step.id))
        setMessage(error instanceof Error ? error.message : "The proposal could not be previewed.");
    } finally {
      setPending(false);
    }
  }
  const images = preview?.revision === revision && preview.paramsKey === paramsKey ? preview.images : undefined;
  return <>
    <Button type="button" onClick={() => void renderProposal()} disabled={pending || !step.invocation_id}
      label={pending ? "Rendering proposal…" : params ? "Preview edited proposal" : "Preview proposal"} />
    {message && <p>{message}</p>}
    {!!images?.length && <figure>
      <figcaption>Proposed result for this operation</figcaption>
      {images.map((bytes, index) => <img key={index} className="proposal-preview"
        alt={`Proposed result ${index + 1}`} src={`data:image/${bytes.startsWith("R0lG") ? "gif" : bytes.startsWith("/9j/") ? "jpeg" : "png"};base64,${bytes}`} />)}
    </figure>}
    {images?.length === 0 && <p>This operation produces no image.</p>}
  </>;
}
