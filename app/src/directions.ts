/** Keep challenge linkage out of human-facing direction labels. */
export function directionLabel(name: string) {
  return name.replace(/^Round [0-9a-f]{32} · /, "Round · ");
}
