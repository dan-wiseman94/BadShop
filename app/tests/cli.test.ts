import { expect, it } from "vitest";
import { cliCommand } from "../src/components/Timeline";
import type { Step, Tool } from "../src/types";
it("copies structured animation frames as JSON flags", () => {
  const step = { tool: "animation_edit", params: { frames: [{ index: 2, duration: 300 }] } } as unknown as Step;
  expect(cliCommand(step)).toBe(`badshop animation_edit '--frames={"index":2,"duration":300}'`);
});
it("copies polygons as JSON while keeping numeric focal pairs as separate arguments", () => {
  const polygon = { tool: "cutout", params: { keep_regions: [[[1, 2], [3, 4], [5, 6]]] } } as unknown as Step;
  expect(cliCommand(polygon)).toBe("badshop cutout '--keep-regions=[[1,2],[3,4],[5,6]]'");
  const focal = { tool: "layout", params: { focal_points: [[0.2, 0.7]] } } as unknown as Step;
  expect(cliCommand(focal)).toBe("badshop layout '--focal-points' '0.2' '0.7'");
});
it("copies disabled options whose CLI default is enabled", () => {
  const step = { tool: "palette", params: { image: "/tmp/image.png", dither: false } } as unknown as Step;
  const tool = { schema: { properties: { image: { type: "string" }, dither: { type: "boolean", default: true } } } } as unknown as Tool;
  expect(cliCommand(step, tool)).toContain("'--no-dither'");
});
it("copies nullable coordinate arrays as one nargs option and keeps image positional", () => {
  const step = {
    tool: "cutout",
    params: { image: "/tmp/image.png", box: [0, 10, 100, 110] },
  } as unknown as Step;
  const tool = {
    cli_positionals: ["image"],
    schema: {
      properties: {
        image: { type: "string" },
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
        },
      },
    },
  } as unknown as Tool;
  expect(cliCommand(step, tool)).toBe(
    "badshop cutout '/tmp/image.png' '--box' '0' '10' '100' '110'",
  );
});
