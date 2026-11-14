import { expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { cliClipboardText } from "../src/components/Timeline";
import type { Step, Tool } from "../src/types";

const commandTool = (name: string) => ({ name, schema: {} } as Tool);

it("copies Windows arguments as JSON with punctuation preserved verbatim", () => {
  const text = "it's \u2019 $HOME; `literal` & \"quoted\" %PATH% !HOME!\nsecond line";
  const step = { tool: "caption", params: { text } } as unknown as Step;
  expect(JSON.parse(cliClipboardText(step, commandTool("caption"), "argv"))).toEqual(
    ["badshop", "caption", `--text=${text}`],
  );
});

it("refuses to copy a project step without a matching CLI tool", () => {
  const step = { tool: "caption; printf injected", params: {} } as unknown as Step;
  expect(() => cliClipboardText(step, commandTool("caption"), "posix")).toThrow(
    "This step does not match a registered CLI tool.",
  );
});

it.skipIf(process.platform === "win32")("roundtrips copied arguments through POSIX sh", () => {
  const text = "space it's \"quoted\" $HOME `literal`; & |\nUnicode \u{1F408}";
  const step = { tool: "caption", params: { text } } as unknown as Step;
  const command = cliClipboardText(step, commandTool("caption"), "posix");
  const output = execFileSync("/bin/sh", ["-c",
    `badshop() { "$BADSHOP_TEST_NODE" -e 'process.stdout.write(JSON.stringify(process.argv.slice(1)))' "$@"; }; ${command}`],
    {
      encoding: "utf8",
      env: { ...process.env, BADSHOP_TEST_NODE: process.execPath },
    },
  );
  expect(JSON.parse(output)).toEqual(["caption", `--text=${text}`]);
});

it("copies structured animation frames as JSON flags", () => {
  const step = { tool: "animation_edit", params: { frames: [{ index: 2, duration: 300 }] } } as unknown as Step;
  expect(JSON.parse(cliClipboardText(step, commandTool("animation_edit"), "argv"))).toEqual(
    ["badshop", "animation_edit", '--frames={"index":2,"duration":300}'],
  );
});

it("copies polygons as JSON while keeping numeric focal pairs as separate arguments", () => {
  const polygon = { tool: "cutout", params: { keep_regions: [[[1, 2], [3, 4], [5, 6]]] } } as unknown as Step;
  expect(JSON.parse(cliClipboardText(polygon, commandTool("cutout"), "argv"))).toEqual(
    ["badshop", "cutout", "--keep-regions=[[1,2],[3,4],[5,6]]"],
  );
  const focal = { tool: "layout", params: { focal_points: [[0.2, 0.7]] } } as unknown as Step;
  expect(JSON.parse(cliClipboardText(focal, commandTool("layout"), "argv"))).toEqual(
    ["badshop", "layout", "--focal-points", "0.2", "0.7"],
  );
});
it("copies disabled options whose CLI default is enabled", () => {
  const step = { tool: "palette", params: { image: "/tmp/image.png", dither: false } } as unknown as Step;
  const tool = { name: "palette", schema: { properties: { image: { type: "string" }, dither: { type: "boolean", default: true } } } } as unknown as Tool;
  expect(JSON.parse(cliClipboardText(step, tool, "argv"))).toContain("--no-dither");
});
it("copies nullable coordinate arrays as one nargs option and keeps image positional", () => {
  const step = {
    tool: "cutout",
    params: { image: "/tmp/image.png", box: [0, 10, 100, 110] },
  } as unknown as Step;
  const tool = {
    name: "cutout",
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
  expect(JSON.parse(cliClipboardText(step, tool, "argv"))).toEqual(
    ["badshop", "cutout", "/tmp/image.png", "--box", "0", "10", "100", "110"],
  );
});
