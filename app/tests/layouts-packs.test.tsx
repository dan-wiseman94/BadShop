import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LayoutsPacks } from "../src/components/LayoutsPacks";
import { action } from "../src/data";
import { useUI } from "../src/store";
vi.mock("../src/native", () => ({ packPath: () => window.prompt("Pack path") }));
vi.mock("../src/data", () => ({
  action: vi.fn(),
  queries: { invalidateQueries: vi.fn().mockResolvedValue(undefined) },
  useSession: () => ({
    data: {
      artifacts: { a: { id: "a", label: "Dog", width: 100, height: 100 } },
    },
  }),
  useCoreQuery: (method: string) => ({
    data:
      method === "layouts.list"
        ? [
            {
              id: "trading-card",
              name: "Trading card",
              width: 600,
              height: 840,
              max_images: 1,
              slots: [
                {
                  name: "Character",
                  box: [10, 10, 50, 50],
                  caption_box: [10, 50, 50, 80],
                  mask: "rectangle",
                },
              ],
            },
            {
              id: "comic",
              name: "Comic",
              width: 1000,
              height: 650,
              max_images: 2,
              slots: [
                {
                  name: "Image 1",
                  box: [10, 10, 450, 500],
                  caption_box: [10, 500, 450, 600],
                  mask: "rectangle",
                },
                {
                  name: "Image 2",
                  box: [500, 10, 900, 500],
                  caption_box: [500, 500, 900, 600],
                  mask: "rectangle",
                },
              ],
            },
          ]
        : method === "packs.list"
          ? [
              {
                id: "school-lab",
                name: "School computer lab",
                description: "Badges",
                count: 4,
              },
            ]
          : [{ id: "saved", name: "Saved dog" }],
  }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  useUI.getState().set({ status: "ready" });
});
it("keeps a sparse image assignment in its chosen slot", async () => {
  vi.mocked(action).mockResolvedValue({
    status: "done",
    outputs: ["result"],
  } as never);
  const attach = vi.fn();
  render(<LayoutsPacks onAttach={attach} />);
  fireEvent.change(screen.getByLabelText("Layout template"), {
    target: { value: "comic" },
  });
  fireEvent.change(screen.getByLabelText("Image for Image 2"), {
    target: { value: "a" },
  });
  fireEvent.change(screen.getByLabelText("Caption for Image 2"), {
    target: { value: "Boss" },
  });
  fireEvent.click(screen.getByText("Create layout"));
  await waitFor(() => expect(attach).toHaveBeenCalledWith("result"));
  expect(action).toHaveBeenCalledWith("tools.run", {
    tool: "layout",
    params: expect.objectContaining({
      images: ["a"],
      image_slots: [1],
      captions: ["", "Boss"],
    }),
  });
});
it("installs a builtin pack into the library and reports its actual size", async () => {
  vi.mocked(action).mockResolvedValue([{}, {}, {}, {}] as never);
  render(<LayoutsPacks onAttach={vi.fn()} />);
  fireEvent.click(screen.getByText("Install School computer lab"));
  expect(await screen.findByRole("status")).toHaveTextContent("4 assets added");
  expect(action).toHaveBeenCalledWith("packs.install", { id: "school-lab" });
});
it("exports only selected entries to the path chosen by the user", async () => {
  vi.spyOn(window, "prompt").mockReturnValue("/tmp/dogs.badpack");
  vi.mocked(action).mockResolvedValue({
    path: "/tmp/dogs.badpack",
    count: 1,
  } as never);
  render(<LayoutsPacks onAttach={vi.fn()} />);
  fireEvent.click(screen.getByLabelText("Saved dog"));
  fireEvent.click(screen.getByText("Export selected assets"));
  await waitFor(() =>
    expect(action).toHaveBeenCalledWith("packs.export", {
      ids: ["saved"],
      path: "/tmp/dogs.badpack",
    }),
  );
  vi.restoreAllMocks();
});
