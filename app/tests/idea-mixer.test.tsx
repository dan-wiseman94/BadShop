import { expect, it } from "vitest";
import { emptyLocks, mixIdeas } from "../src/ideaMixer";

const formats = [
  "trading-card",
  "comic",
  "newspaper",
  "certificate",
  "yearbook",
  "inventory",
].map((id) => ({ id, name: id }));

it("reproduces a batch while varying all unlocked choices within it", () => {
  const first = mixIdeas("my cat", emptyLocks, formats, 17);
  expect(first).toEqual(mixIdeas("my cat", emptyLocks, formats, 17));
  expect(first.ideas).toHaveLength(6);
  for (const dimension of ["joke", "setting", "era", "format"] as const)
    expect(new Set(first.ideas.map((idea) => idea[dimension].id)).size).toBe(6);
  const next = mixIdeas(
    "my cat",
    emptyLocks,
    formats,
    17,
    first.ideas.map((idea) => idea.key),
  );
  expect(
    next.ideas.every(
      (idea) => !first.ideas.some((previous) => previous.key === idea.key),
    ),
  ).toBe(true);
  expect(
    first.ideas.every(
      (idea) =>
        idea.prompt.includes("my cat") && idea.prompt.includes(idea.format.id),
    ),
  ).toBe(true);
});

it("honors locked choices and reports exhaustion rather than looping or duplicating a batch", () => {
  const locks = {
    joke: "bureaucracy",
    setting: "office",
    era: "forum",
    format: "comic",
  };
  const first = mixIdeas("", locks, formats, 0);
  expect(first.ideas).toHaveLength(1);
  expect(first.total).toBe(1);
  expect(first.ideas[0].prompt).toContain("the subject in my attached images");
  const second = mixIdeas("", locks, formats, 1, [first.ideas[0].key]);
  expect(second.repeated).toBe(true);
  expect(second.ideas).toEqual(first.ideas);
  expect(
    mixIdeas("", { ...locks, format: "removed-layout" }, formats, 1).ideas,
  ).toEqual([]);
});
