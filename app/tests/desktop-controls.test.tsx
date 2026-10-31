import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { ToolForm } from "../src/components/ToolForm";
import { useUI } from "../src/store";
import type { Tool, Artifact } from "../src/types";
const images = Object.fromEntries(
  ["a", "b", "c"].map((id) => [
    id,
    {
      id,
      label: `Image ${id}`,
      width: 100,
      height: 100,
      format: "PNG",
      mime: "image/png",
    } as Artifact,
  ]),
);
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient();
  client.setQueryData(["session.get"], { id: "s", artifacts: images });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const tool: Tool = {
  name: "cutout",
  category: "cut",
  summary: "Cut",
  description: "",
  mutates: true,
  network: false,
  read_only: false,
  schema: {
    type: "object",
    required: ["image"],
    properties: {
      image: { type: "string", format: "badshop-image", title: "Image" },
      caption: { type: "string", title: "Caption" },
      box: {
        type: "array",
        format: "badshop-box",
        title: "Box",
        items: { type: "integer" },
        minItems: 4,
        maxItems: 4,
      },
    },
  },
};
beforeEach(() =>
  useUI
    .getState()
    .set({
      status: "starting",
      selectedArtifact: "b",
      pick: null,
      error: null,
    }),
);
it("binds coordinate selection to the form input rather than the current viewer image", () => {
  render(<ToolForm tool={tool} initial={{ image: "a" }} onSubmit={vi.fn()} />, {
    wrapper,
  });
  fireEvent.click(screen.getByRole("button", { name: "Pick on image" }));
  expect(useUI.getState().pick).toMatchObject({ artifactId: "a" });
});
it("refreshes remapped input references while preserving a caption being edited", () => {
  const { rerender } = render(
    <ToolForm
      tool={tool}
      initial={{ image: "a", caption: "Original" }}
      onSubmit={vi.fn()}
    />,
    { wrapper },
  );
  fireEvent.change(screen.getByLabelText("Caption"), {
    target: { value: "My draft" },
  });
  rerender(
    <ToolForm
      tool={tool}
      initial={{ image: "b", caption: "Original" }}
      onSubmit={vi.fn()}
    />,
  );
  expect(screen.getByLabelText(/Image/)).toHaveValue("b");
  expect(screen.getByLabelText("Caption")).toHaveValue("My draft");
});
it("preserves a conflicting edited input until the user explicitly chooses which parameters to use", () => {
  const { rerender } = render(
    <ToolForm tool={tool} initial={{ image: "a" }} onSubmit={vi.fn()} />,
    { wrapper },
  );
  fireEvent.change(screen.getByLabelText(/Image/), { target: { value: "c" } });
  rerender(
    <ToolForm tool={tool} initial={{ image: "b" }} onSubmit={vi.fn()} />,
  );
  expect(screen.getByLabelText(/Image/)).toHaveValue("c");
  expect(screen.getByRole("alert")).toHaveTextContent("changed during replay");
  expect(screen.getByRole("button", { name: "Run tool" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Use current parameters" }),
  );
  expect(screen.getByLabelText(/Image/)).toHaveValue("b");
  expect(screen.getByRole("button", { name: "Run tool" })).toBeEnabled();
});
