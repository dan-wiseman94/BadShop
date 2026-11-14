import { expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { cliArguments, cliCommand } from "../src/components/Timeline";
import type { Step, Tool } from "../src/types";
it("keeps literal captions intact in POSIX and PowerShell commands", () => {
  const text = "it's $HOME; `literal` & \"quoted\"";
  const step = { tool: "caption", params: { text } } as unknown as Step;
  expect(cliArguments(step)).toEqual(["badshop", "caption", `--text=${text}`]);
  expect(cliCommand(step, undefined, "powershell")).toBe(
    "badshop caption '--text=it''s $HOME; `literal` & \"quoted\"'",
  );
  expect(cliCommand(step, undefined, "posix")).toBe(
    "badshop caption '--text=it'\\''s $HOME; `literal` & \"quoted\"'",
  );
});
it("roundtrips copied arguments through the host shell", () => {
  const text = "space it's \"quoted\" $HOME `literal`; & |\nUnicode 🖼";
  const step = { tool: "caption", params: { text } } as unknown as Step;
  const windows = process.platform === "win32";
  const command = cliCommand(step, undefined, windows ? "powershell" : "posix");
  const output = windows
    ? execFileSync("pwsh.exe", ["-NoProfile", "-NonInteractive", "-Command",
        `function badshop { ConvertTo-Json -Compress -InputObject @($args) }; ${command}`], { encoding: "utf8" })
    : execFileSync("/bin/sh", ["-c",
        `badshop() { "$BADSHOP_TEST_NODE" -e 'process.stdout.write(JSON.stringify(process.argv.slice(1)))' "$@"; }; ${command}`],
        { encoding: "utf8", env: { ...process.env, BADSHOP_TEST_NODE: process.execPath } });
  expect(JSON.parse(output)).toEqual(cliArguments(step).slice(1));
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
