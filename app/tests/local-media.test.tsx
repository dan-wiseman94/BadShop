import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocalMedia } from "../src/components/LocalMedia";
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

it("does not offer source operations while disconnected", () => {
  useUI.getState().set({ status: "disconnected" });
  render(<LocalMedia onAttach={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Selected source file"), {
    target: { value: "/photos/movie.mp4" },
  });
  expect(screen.getByText("Preview source")).toBeDisabled();
  expect(screen.getByText("Choose file")).toBeDisabled();
});
