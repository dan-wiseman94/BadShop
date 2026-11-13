import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { action, useSession } from "../data";
import { rpc } from "../rpc";
import { reveal } from "../native";
import { useOperation } from "../useOperation";
import { ArtifactThumb } from "./Viewer";

export function RemixShare({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const [credits, setCredits] = useState(false);
  const { data: session } = useSession();
  const revision = session?.document_revision ?? 0;
  const { busy, error, notice, setNotice, perform } = useOperation();
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const preview = useQuery({ queryKey: ["remix.inspect", id, revision], enabled: open && !disabled,
    queryFn: () => rpc.request("remix.inspect", { artifact_id: id, expected_revision: revision }), retry: false });
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Let someone remix this</summary>
    <p>Send an editable .badshop file. These pictures and their {preview.data?.step_count ?? "…"} edits will be included. Recipients can change the words and controls using Open project.</p>
    <p>Conversations, other directions, original files, filenames and embedded photo metadata are excluded. Visible faces and words remain. Animated images are re-encoded as GIFs.</p>
    <div className="retro-inputs">{preview.data?.artifact_ids.map(aid => <ArtifactThumb key={aid} id={aid} />)}</div>
    <label><input type="checkbox" checked={credits} onChange={e => setCredits(e.target.checked)} /> Include recorded source credits</label>
    {credits && <><p>Review these titles, creators and URLs before sharing:</p>{preview.data?.sources.map((source, i) => <p key={i}>{Object.values(source).filter(Boolean).map(String).join(" · ")}</p>)}</>}
    <button disabled={disabled || !preview.data || preview.isFetching} onClick={() => void perform(async () => {
      const result = await action("remix.export", { artifact_id: id, expected_revision: revision, include_credits: credits });
      setNotice(`Editable remix saved to ${result.path}`); await reveal(result.path);
    })}>Save editable remix</button>
    {notice && <p role="status">{notice}</p>}{(error || preview.error) && <p role="alert">{error ?? preview.error?.message}</p>}
  </details>;
}
