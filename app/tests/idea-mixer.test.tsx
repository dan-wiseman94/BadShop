import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { IdeaMixer } from "../src/components/IdeaMixer";
import { emptyLocks, mixIdeas } from "../src/ideaMixer";

const formats = [
  "trading-card",
  "comic",
  "newspaper",
  "certificate",
  "yearbook",
  "inventory",
].map((id) => ({ id, name: id }));
vi.mock("../src/data", () => ({ useCoreQuery: () => ({ data: formats }) }));

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

it("passes the selected brief or source query without starting an agent turn", () => {
  const onDraft = vi.fn(),
    onSearch = vi.fn();
  render(<IdeaMixer onDraft={onDraft} onSearch={onSearch} />);
  fireEvent.change(screen.getByLabelText("Idea subject"), {
    target: { value: "my very tired dog" },
  });
  fireEvent.change(screen.getByLabelText("Lock format"), {
    target: { value: "comic" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Mix six ideas" }));
  expect(
    screen.getAllByRole("button", { name: "Add brief to chat" }),
  ).toHaveLength(6);
  fireEvent.click(
    screen.getAllByRole("button", { name: "Add brief to chat" })[0],
  );
  expect(onDraft).toHaveBeenCalledWith(
    expect.stringContaining("my very tired dog"),
  );
  expect(onDraft).toHaveBeenCalledWith(
    expect.stringContaining('layout template "comic"'),
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Prepare a source search" })[0],
  );
  expect(onSearch).toHaveBeenCalledWith(expect.any(String));
});
