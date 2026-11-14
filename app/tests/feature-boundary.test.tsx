import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FeatureBoundary } from "../src/components/FeatureBoundary";

it("keeps sibling drafts and save controls usable, and retries only the failed panel", () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  let broken = false;
  function Panel() {
    if (broken) throw new Error("render failure");
    return <p>Canvas ready</p>;
  }
  const saved = vi.fn();
  function Workspace() {
    return <><input aria-label="Draft" defaultValue="" /><button onClick={saved}>Save project</button>
      <FeatureBoundary name="Canvas"><Panel /></FeatureBoundary></>;
  }
  try {
    const view = render(<Workspace />);
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep this idea" } });
    broken = true;
    view.rerender(<Workspace />);
    expect(screen.getByRole("alert")).toHaveTextContent("Canvas could not be displayed");
    expect(screen.getByRole("button", { name: "Retry canvas" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Save project" }));
    expect(saved).toHaveBeenCalledTimes(1);
    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry canvas" }));
    expect(screen.getByText("Canvas ready")).toBeVisible();
    expect(screen.getByLabelText("Draft")).toHaveValue("Keep this idea");
    expect(saved).toHaveBeenCalledTimes(1);
  } finally { errors.mockRestore(); }
});
