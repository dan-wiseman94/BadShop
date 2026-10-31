import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Coordinates,
  ToolForm,
  normalizeSchema,
  schemaUI,
} from "../src/components/ToolForm";
import { useUI } from "../src/store";
import type { FieldProps, RJSFSchema } from "@rjsf/utils";
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
describe("registry forms", () => {
  it("renders nullable image and coordinate formats without a raw union selector", () => {
    const normalized = normalizeSchema({
      type: "object",
      properties: {
        image: {
          anyOf: [
            { type: "string", format: "badshop-image" },
            { type: "null" },
          ],
          default: null,
        },
        box: {
          type: "array",
          format: "badshop-box",
          prefixItems: [
            { type: "integer" },
            { type: "integer" },
            { type: "integer" },
            { type: "integer" },
          ],
        },
      },
    } as RJSFSchema);
    expect(normalized.properties?.image).toEqual({
      type: "string",
      format: "badshop-image",
    });
    expect(schemaUI(normalized).box).toMatchObject({
      "ui:field": "Coordinates",
    });
    expect(schemaUI(normalized).image).toEqual({ "ui:widget": "ImagePicker" });
  });
  it("validates required parameters before submitting a tool", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    const tool: Tool = {
      name: "text",
      category: "text",
      summary: "Caption",
      description: "Caption",
      mutates: true,
      network: false,
      read_only: false,
      schema: {
        type: "object",
        required: ["caption"],
        properties: { caption: { type: "string", title: "Caption" } },
      },
    };
    render(<ToolForm tool={tool} onSubmit={submit} />, { wrapper });
    fireEvent.change(screen.getByLabelText(/Caption/), {
      target: { value: "STONKS" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tool" }));
    await vi.waitFor(() =>
      expect(submit).toHaveBeenCalledWith({ caption: "STONKS" }),
    );
  });
  it("connects segment coordinate selection to the viewer without swapping endpoints", () => {
    const changed = vi.fn();
    const props = {
      schema: { type: "array", title: "Arrow", format: "badshop-segment" },
      formData: [10, 20, 30, 40],
      onChange: changed,
      fieldPathId: { $id: "arrow", path: ["arrow"] },
      registry: {
        formContext: {
          coordinateImageId: "input",
          coordinateImageLabel: "Input image",
        },
      },
    } as unknown as FieldProps;
    render(<Coordinates {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Pick on image" }));
    expect(useUI.getState().pick?.kind).toBe("segment");
    useUI.getState().pick?.complete([80, 90, 10, 20]);
    expect(changed).toHaveBeenCalledWith([80, 90, 10, 20], ["arrow"]);
  });
});

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
