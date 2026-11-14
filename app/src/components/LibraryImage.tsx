import { useQuery } from "@tanstack/react-query";
import { imageUrl } from "../data";
import { rpc } from "../rpc";
import type { LibraryEntry } from "../types";

export function LibraryImage({ entry }: { entry: LibraryEntry }) {
  const { data, error } = useQuery({
    queryKey: ["library.thumbnail", entry.id],
    queryFn: ({ signal }) => rpc.request("library.thumbnail", { id: entry.id, max_px: 240 }, signal),
  });
  return error ? <span role="alert">Preview unavailable</span> : <img className="studio-thumb" src={imageUrl(data)} alt={entry.name} />;
}
