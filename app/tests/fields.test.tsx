import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SelectField } from "../src/components/Fields";

it("keeps a saved recipe selected when saving moves it to the end of the list", () => {
  const view = render(<SelectField label="Saved recipe" options={["", "A", "B"]} />);
  const select = screen.getByRole("combobox", { name: "Saved recipe" });
  fireEvent.change(select, { target: { value: "A" } });
  view.rerender(<SelectField label="Saved recipe" options={["", "B", "A"]} />);
  expect(select).toHaveValue("A");
});
