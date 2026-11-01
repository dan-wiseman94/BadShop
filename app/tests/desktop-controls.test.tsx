import { fireEvent, render, screen, within } from "@testing-library/react";
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
  useUI.getState().set({
    status: "starting",
    selectedArtifact: "b",
    pick: null,
    error: null,
  }),
);
it("keeps a palette form's labels bound to its own controls while step details remain mounted", async () => {
  const firstSubmit = vi.fn().mockResolvedValue(undefined);
  const paletteSubmit = vi.fn().mockResolvedValue(undefined);
  render(
    <>
      <ToolForm tool={tool} initial={{ image: "a" }} onSubmit={firstSubmit} />
      <section role="dialog" aria-label="Run a tool">
        <ToolForm
          tool={tool}
          initial={{ image: "b" }}
          onSubmit={paletteSubmit}
        />
      </section>
    </>,
    { wrapper },
  );
  const dialog = screen.getByRole("dialog", { name: "Run a tool" });
  const image = within(dialog).getByLabelText(/Image/);
  const caption = within(dialog).getByLabelText("Caption");
  expect(image).toHaveValue("b");
  for (const label of dialog.querySelectorAll<HTMLLabelElement>("label[for]"))
    expect(dialog.contains(label.control)).toBe(true);
  const fields = Array.from(
    document.querySelectorAll("input[id],select[id],textarea[id]"),
  );
  expect(new Set(fields.map((field) => field.id)).size).toBe(fields.length);
  const id = caption.id;
  fireEvent.change(caption, { target: { value: "A local draft" } });
  expect(within(dialog).getByLabelText("Caption")).toHaveAttribute("id", id);
  expect(within(dialog).getByLabelText("Caption")).toHaveValue("A local draft");
  fireEvent.click(within(dialog).getByRole("button", { name: "Run tool" }));
  await vi.waitFor(() =>
    expect(paletteSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ image: "b", caption: "A local draft" }),
    ),
  );
  expect(firstSubmit).not.toHaveBeenCalled();
  const firstImage = screen
    .getAllByLabelText(/Image/)
    .find((node) => !dialog.contains(node));
  expect(firstImage).toHaveValue("a");
  const firstCaption = screen
    .getAllByLabelText("Caption")
    .find((node) => !dialog.contains(node));
  expect(firstCaption).toHaveValue("");
});
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
