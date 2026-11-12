import { expect, it } from "vitest";
import { cliCommand } from "../src/components/Timeline";
import type { Step, Tool } from "../src/types";
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
