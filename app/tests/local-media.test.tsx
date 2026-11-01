import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocalMedia } from "../src/components/LocalMedia";
import { action } from "../src/data";
import { useUI } from "../src/store";
vi.mock("../src/data", () => ({
  action: vi.fn(),
  useSession: () => ({
    data: { provider_profile_id: "p", turn_running: false },
  }),
  useCoreQuery: () => ({
    data: [
      { id: "one", name: "Photos", count: 2 },
      { id: "two", name: "Screenshots", count: 1 },
    ],
  }),
}));
vi.mock("../src/native", () => ({
  chooseMediaFile: vi.fn(),
  chooseCollectionFolder: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  useUI.getState().set({ status: "ready" });
});
it("previews before importing and submits the selected region", async () => {
  const attach = vi.fn();
  vi.mocked(action).mockResolvedValueOnce({
    id: "preview",
    source_name: "page.png",
    kind: "document",
    warnings: [],
    sheet_data_url: "data:image/png;base64,AA==",
    candidates: [
      {
        id: "0",
        label: "Page 1",
        width: 80,
        height: 60,
        thumbnail_data_url: "data:image/png;base64,AA==",
      },
    ],
  } as never);
  render(<LocalMedia onAttach={attach} />);
  fireEvent.click(screen.getByRole("button", { name: "Pages / scans" }));
  fireEvent.change(screen.getByLabelText("Selected source file"), {
    target: { value: "/photos/page.png" },
  });
  fireEvent.click(screen.getByText("Preview source"));
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "Select Page 1" }),
  );
  expect(attach).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Crop left"), {
    target: { value: "5" },
  });
  fireEvent.change(screen.getByLabelText("Crop right"), {
    target: { value: "35" },
  });
  vi.mocked(action).mockResolvedValueOnce({
    artifacts: [{ id: "cropped" }],
    provenance: {},
  } as never);
  fireEvent.click(screen.getByText("Import selected region"));
  await waitFor(() => expect(attach).toHaveBeenCalledWith("cropped"));
  expect(action).toHaveBeenLastCalledWith("media.import", {
    preview_id: "preview",
    candidate_ids: ["0"],
    crop: [5, 0, 35, 60],
    animate: false,
    delay: 100,
  });
});
it("clears old results when switching collections", async () => {
  vi.mocked(action).mockResolvedValue([
    {
      id: "dog",
      name: "Dog",
      tags: [],
      description: "",
      thumbnail_data_url: "data:image/png;base64,AA==",
    },
  ] as never);
  render(<LocalMedia onAttach={vi.fn()} />);
  fireEvent.click(screen.getByText("My folders"));
  fireEvent.change(screen.getByLabelText("Indexed collection"), {
    target: { value: "one" },
  });
  fireEvent.click(screen.getByText("Search collection"));
  await screen.findByText("Use local image");
  fireEvent.change(screen.getByLabelText("Indexed collection"), {
    target: { value: "two" },
  });
  expect(screen.queryByText("Use local image")).not.toBeInTheDocument();
});
it("does not offer source operations while disconnected", () => {
  useUI.getState().set({ status: "disconnected" });
  render(<LocalMedia onAttach={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Selected source file"), {
    target: { value: "/photos/movie.mp4" },
  });
  expect(screen.getByText("Preview source")).toBeDisabled();
  expect(screen.getByText("Choose file")).toBeDisabled();
});
