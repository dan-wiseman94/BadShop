import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SpriteSheet } from "../src/components/SpriteSheet";
import { useUI } from "../src/store";

const state = vi.hoisted(() => ({
  running: false,
  artifacts: {
    sheet: { id: "sheet", label: "Sprites", width: 17, height: 13 },
    other: { id: "other", label: "Other sheet", width: 32, height: 32 },
  },
}));
vi.mock("../src/data", () => ({
  action: vi.fn(),
  useSession: () => ({
    data: {
      id: "project",
      turn_running: state.running,
      artifacts: state.artifacts,
    },
  }),
  useArtifact: () => ({ data: { mime: "image/png", data: "AA==" } }),
  imageUrl: () => "data:image/png;base64,AA==",
}));
vi.mock("../src/components/Viewer", () => ({
  ArtifactThumb: ({ label }: { label: string }) => <span>{label}</span>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.running = false;
  useUI.getState().set({ status: "ready", selectedArtifact: "sheet" });
});

it("clears selections when geometry or source changes", () => {
  render(<SpriteSheet onAttach={vi.fn()} />);
  const first = () =>
    screen.getByRole("checkbox", { name: "Cell 0, row 0, column 0" });
  fireEvent.click(first());
  fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "3" } });
  expect(first()).toHaveAttribute("aria-checked", "false");
  fireEvent.change(screen.getByLabelText("Rows"), {
    target: { value: "2" },
  });
  expect(first()).toHaveAttribute("aria-checked", "false");
  fireEvent.click(first());
  fireEvent.change(screen.getByLabelText("Sprite sheet image"), {
    target: { value: "other" },
  });
  expect(first()).toHaveAttribute("aria-checked", "false");
  fireEvent.change(screen.getByLabelText("Sprite sheet image"), {
    target: { value: "sheet" },
  });
  expect(first()).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("button", { name: "Extract selected and attach" }),
  ).toBeDisabled();
});

it("rejects impossible margins and limits extraction to 64 cells", () => {
  render(<SpriteSheet onAttach={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Left margin"), {
    target: { value: "17" },
  });
  expect(screen.getByRole("alert")).toHaveTextContent("at least one pixel");
  expect(
    screen.getByRole("button", { name: "Extract all and attach" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Left margin"), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText("Columns"), {
    target: { value: "8" },
  });
  expect(
    screen.getByRole("button", { name: "Extract all and attach" }),
  ).toBeDisabled();
  const cells = screen.getAllByRole("checkbox");
  cells.slice(0, 64).forEach((cell) => fireEvent.click(cell));
  expect(cells[64]).toHaveAttribute("aria-disabled", "true");
  fireEvent.click(cells[64]);
  expect(cells[64]).toHaveAttribute("aria-checked", "false");
  expect(screen.getByText(/^64 selected/)).toBeInTheDocument();
});
