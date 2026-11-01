import { expect, it } from "vitest";
import { creativeRequest, creativeStyles } from "../src/creative";

it("leaves an ordinary message unchanged", () => {
  expect(creativeRequest("  just caption it  ", "", 1)).toBe("  just caption it  ");
});

it("carries the chosen style and independent compositions into the saved user request", () => {
  const request = creativeRequest("Make my dog the boss.", "museum-vandalism", 3);
  expect(request).toContain("Make my dog the boss.");
  expect(request).toContain("Museum vandalism");
  expect(request).toContain("three different premises");
  expect(request).toContain("clean base");
  expect(request).toContain("Take 1, Take 2, and Take 3");
});

it("has six distinct styles and ignores unknown directions", () => {
  expect(new Set(creativeStyles.map((style) => style.id)).size).toBe(6);
  expect(creativeRequest("hello", "made-up", 1)).toBe("hello");
});
