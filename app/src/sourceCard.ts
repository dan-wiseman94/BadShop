import type { Params } from "./types";

/** Browser handoff carries provenance, never executable instructions or local paths. */
export function sourceCard(text: string): Params | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || !("badshop_source" in value))
    return null;
  const card = value as Record<string, unknown>;
  if (card.badshop_source !== 1)
    throw new Error("Unsupported badshop source card version.");
  if (typeof card.url !== "string" || !/^https?:\/\//i.test(card.url))
    throw new Error("The selected image needs an HTTP or HTTPS image address.");
  const result: Params = { url: card.url, source_kind: "browser" };
  for (const key of ["page", "title", "creator", "license"])
    if (typeof card[key] === "string" && card[key].length <= 4096)
      result[key] = card[key].slice(0, key === "page" ? 4096 : 500);
  if (result.page && !/^https?:\/\//i.test(String(result.page)))
    delete result.page;
  return result;
}
