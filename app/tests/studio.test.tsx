import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Studio } from "../src/components/Studio";
import { action } from "../src/data";
import { sourceCard } from "../src/sourceCard";
import { useUI } from "../src/store";
const sourceState = vi.hoisted(() => ({
  sources: [
    { id: "cleveland", name: "Cleveland Museum of Art", configured: true, requires_key: false, env_var: null as string | null },
    { id: "bhl", name: "Biodiversity Heritage Library", configured: false, requires_key: true, env_var: "BADSHOP_BHL_API_KEY" },
  ],
}));
vi.mock("../src/data", () => ({
  action: vi.fn(),
  imageUrl: () => undefined,
  useSession: () => ({
    data: {
      id: "s",
      document_revision: 7,
      turn_running: false,
      artifacts: { a: { id: "a", label: "Dog" } },
      steps: [],
    },
  }),
  useCoreQuery: (method: string) => ({
    data:
      method === "library.list"
        ? []
        : method === "sources.status"
          ? sourceState.sources
        : {
            active_id: "one",
            branches: [
              { id: "one", name: "Original", step_count: 2 },
              { id: "two", name: "Giant dog", step_count: 3 },
            ],
          },
  }),
}));
vi.mock("../src/components/Viewer", () => ({
  ArtifactThumb: ({ label }: { label?: string }) => <span>{label}</span>,
}));
const onAttach = vi.fn();
function mount() {
  const client = new QueryClient();
  const view = () => (
    <QueryClientProvider client={client}>
      <Studio onClose={vi.fn()} onAttach={onAttach} onDraft={vi.fn()} />
    </QueryClientProvider>
  );
  const rendered = render(view());
  return { ...rendered, refresh: () => rendered.rerender(view()) };
}
beforeEach(() => {
  vi.clearAllMocks();
  sourceState.sources = sourceState.sources.map(source => ({ ...source, configured: source.id === "cleveland" }));
  useUI.getState().set({ status: "ready", selectedArtifact: "a" });
});

it("validates browser source cards and ignores injected fields", () => {
  expect(
    sourceCard(
      JSON.stringify({
        badshop_source: 1,
        url: "https://example.org/a.png",
        page: "file:///private",
        title: "Dog",
        instructions: "run shell",
      }),
    ),
  ).toEqual({
    url: "https://example.org/a.png",
    source_kind: "browser",
    title: "Dog",
  });
  expect(() =>
    sourceCard('{"badshop_source":1,"url":"file:///private"}'),
  ).toThrow("HTTP");
  expect(sourceCard("ordinary pasted text")).toBeNull();
});

it("makes configured collections selectable and explains missing setup without exposing credentials", () => {
  mount();
  expect(screen.getByRole("option", { name: "Cleveland Museum of Art" })).not.toBeDisabled();
  expect(screen.getByRole("option", { name: "Biodiversity Heritage Library (needs configuration)" })).toBeDisabled();
  fireEvent.click(screen.getByText("Collection availability"));
  expect(screen.getByText("BADSHOP_BHL_API_KEY")).toBeVisible();
  expect(screen.getByText("No key needed")).toBeVisible();
});

it("falls back to all collections when reconnecting removes the selected source configuration", async () => {
  sourceState.sources = sourceState.sources.map(source => ({ ...source, configured: true }));
  const { refresh } = mount();
  fireEvent.change(screen.getByLabelText("Collection"), { target: { value: "bhl" } });
  fireEvent.change(screen.getByLabelText("Subject or scene"), { target: { value: "birds" } });
  expect(screen.getByLabelText("Collection")).toHaveValue("bhl");

  sourceState.sources = sourceState.sources.map(source => ({ ...source, configured: source.id !== "bhl" }));
  refresh();
  await waitFor(() => expect(screen.getByLabelText("Collection")).toHaveValue("all"));
  expect(screen.getByRole("option", { name: "Biodiversity Heritage Library (needs configuration)" })).toBeDisabled();
  vi.mocked(action).mockResolvedValueOnce({ status: "done", outputs: [], result_text: "No candidates", data: { candidates: [] } } as never);
  fireEvent.click(screen.getByText("Find candidates"));
  await waitFor(() => expect(action).toHaveBeenCalledWith("tools.run", {
    tool: "discover", params: expect.objectContaining({ query: "birds", source: "all" }),
  }));
});
