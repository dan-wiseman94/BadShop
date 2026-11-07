import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ToolForm } from "../src/components/ToolForm";
import type { Tool } from "../src/types";
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
it("leaves an untouched optional coordinate tuple absent from submitted parameters", async () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  const tool: Tool = {
    name: "optional",
    category: "cut",
    summary: "Optional box",
    description: "",
    mutates: true,
    network: false,
    read_only: false,
    schema: {
      type: "object",
      properties: {
        box: {
          anyOf: [
            {
              type: "array",
              format: "badshop-box",
              minItems: 4,
              maxItems: 4,
              items: [
                { type: "integer" },
                { type: "integer" },
                { type: "integer" },
                { type: "integer" },
              ],
            },
            { type: "null" },
          ],
          default: null,
        },
      },
    },
  };
  render(<ToolForm tool={tool} onSubmit={submit} />, { wrapper });
  fireEvent.click(screen.getByRole("button", { name: "Run tool" }));
  await vi.waitFor(() => expect(submit).toHaveBeenCalledWith({}));
});

it("submits a paste position without populating unused fit_box and region", async () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  const tuple = (format: string, length: number) => ({
    anyOf: [
      {
        type: "array",
        format,
        minItems: length,
        maxItems: length,
        items: Array.from({ length }, () => ({ type: "integer" })),
      },
      { type: "null" },
    ],
    default: null,
  });
  const tool = {
    name: "paste",
    category: "compose",
    summary: "Paste",
    description: "",
    mutates: true,
    network: false,
    read_only: false,
    schema: {
      type: "object",
      required: ["base", "piece"],
      properties: {
        base: { type: "string" },
        piece: { type: "string" },
        width: { type: "integer" },
        at: tuple("badshop-point", 2),
        fit_box: tuple("badshop-box", 4),
        region: tuple("badshop-box", 4),
      },
    },
  } as Tool;
  render(
    <ToolForm
      tool={tool}
      initial={{ base: "image1", piece: "image2", width: 100, at: [10, 20] }}
      onSubmit={submit}
    />,
    { wrapper },
  );
  fireEvent.click(screen.getByRole("button", { name: "Run tool" }));
  await vi.waitFor(() => expect(submit).toHaveBeenCalled());
  expect(JSON.parse(JSON.stringify(submit.mock.calls[0][0]))).toEqual({
    base: "image1",
    piece: "image2",
    width: 100,
    at: [10, 20],
  });
});
