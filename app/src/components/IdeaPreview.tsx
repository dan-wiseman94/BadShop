import { useQuery } from "@tanstack/react-query";
import { rpc } from "../rpc";
import type { Params } from "../types";

export function IdeaPreview({ image, template, title, captions, slots, revision, enabled }: {
  image: string; template: string; title: string; captions: string[]; slots: number;
  revision: number; enabled: boolean;
}) {
  const params: Params = { template, title, images: Array(slots).fill(image), captions: Array.from({ length: slots }, (_, i) => captions[i] ?? "") };
  const { data, error, isFetching } = useQuery({
    queryKey: ["idea-preview", image, template, title, captions, slots, revision],
    queryFn: ({ signal }) => rpc.request("tools.preview", {
      tool: "layout", params, expected_revision: revision,
    }, signal),
    enabled: enabled && !!image && slots > 0,
    retry: false,
    staleTime: Infinity,
    gcTime: 60000,
  });
  return <>
    <img src={data?.[0] ?? `/samples/${template}.png`} alt={data ? "Preview with your picture" : "Example with the sample pigeon"} />
    {image && <small>{error ? "Preview unavailable; choose to retry" : isFetching ? "Trying your picture…" : data ? "Your picture" : "Sample preview"}</small>}
  </>;
}
