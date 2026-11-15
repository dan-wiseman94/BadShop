const challengeRound = /^Round [0-9a-f]{32} · /;

/** Keep challenge linkage out of human-facing direction labels. */
export function directionLabel(name: string) {
  return name.replace(challengeRound, "Round · ");
}

export function renamedDirection(previous: string, name: string) {
  return (previous.match(challengeRound)?.[0] ?? "") + name;
}
