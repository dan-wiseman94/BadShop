import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SpriteSheet, sheetCells } from "../src/components/SpriteSheet";
import { action } from "../src/data";
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

it("previews exact uneven geometry with margins and gaps", () => {
  const cells = sheetCells(17, 13, 2, 3, [1, 2, 2, 1], [2, 1]);
  expect(cells.map((cell) => cell.box)).toEqual([
    [1, 2, 5, 7],
    [7, 2, 10, 7],
    [12, 2, 15, 7],
    [1, 8, 5, 12],
    [7, 8, 10, 12],
    [12, 8, 15, 12],
  ]);
});

it("extracts only explicitly chosen sparse cells in row-major order and attaches them", async () => {
  const onAttach = vi.fn();
  vi.mocked(action).mockResolvedValueOnce({
    status: "done",
    outputs: ["tile0", "tile5"],
  } as never);
  render(<SpriteSheet onAttach={onAttach} />);
  fireEvent.change(screen.getByLabelText("Columns"), {
    target: { value: "3" },
  });
  for (const [label, value] of [
    ["Left margin", 1],
    ["Top margin", 2],
    ["Right margin", 2],
    ["Bottom margin", 1],
    ["Horizontal gap", 2],
    ["Vertical gap", 1],
  ]) {
    fireEvent.change(screen.getByLabelText(String(label)), {
      target: { value: String(value) },
    });
  }
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Cell 5, row 1, column 2" }),
  );
  fireEvent.keyDown(
    screen.getByRole("checkbox", { name: "Cell 0, row 0, column 0" }),
    { key: " " },
  );
  expect(onAttach).not.toHaveBeenCalled();
  expect(
    screen.getByRole("checkbox", { name: "Cell 5, row 1, column 2" }),
  ).toHaveAttribute("aria-checked", "true");
  fireEvent.click(
    screen.getByRole("button", { name: "Extract selected and attach" }),
  );
  await waitFor(() => expect(onAttach).toHaveBeenCalledTimes(2));
  expect(action).toHaveBeenCalledWith("tools.run", {
    tool: "slice_sheet",
    params: {
      image: "sheet",
      rows: 2,
      columns: 3,
      margins: [1, 2, 2, 1],
      gap: [2, 1],
      cells: [0, 5],
    },
  });
  expect(onAttach.mock.calls.map((call) => call[0])).toEqual([
    "tile0",
    "tile5",
  ]);
  expect(screen.getByRole("status")).toHaveTextContent(
    "2 cells extracted and attached to chat.",
  );
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

it("extracts all valid cells and surfaces tool errors without attaching", async () => {
  const onAttach = vi.fn();
  vi.mocked(action).mockResolvedValueOnce({
    status: "error",
    outputs: [],
    error: { message: "The image was removed." },
  } as never);
  render(<SpriteSheet onAttach={onAttach} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Extract all and attach" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The image was removed.",
  );
  expect(action).toHaveBeenCalledWith("tools.run", {
    tool: "slice_sheet",
    params: {
      image: "sheet",
      rows: 2,
      columns: 2,
      margins: [0, 0, 0, 0],
      gap: [0, 0],
      cells: [0, 1, 2, 3],
    },
  });
  expect(onAttach).not.toHaveBeenCalled();
});

it.each(["disconnected", "running"])("disables extraction while %s", (mode) => {
  if (mode === "disconnected") useUI.getState().set({ status: "disconnected" });
  else state.running = true;
  render(<SpriteSheet onAttach={vi.fn()} />);
  expect(
    screen.getByRole("button", { name: "Extract all and attach" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Sprite sheet image")).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: "Cell 0, row 0, column 0" }),
  ).toHaveAttribute("aria-disabled", "true");
});
