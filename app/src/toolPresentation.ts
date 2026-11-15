import type { Tool } from "./types";

interface ToolPresentation {
  basic: readonly string[];
  aliases?: readonly string[];
}

// Field names refer to the generated schema; defaults and validation stay with that schema.
const presentation: Readonly<Record<string, ToolPresentation>> = {
  text: {
    basic: ["image", "text", "style", "font", "size", "color", "align", "overflow", "fit_exact", "bottom"],
    aliases: ["add words", "add caption", "write on picture"],
  },
  paste: {
    basic: ["base", "piece", "at", "anchor", "width", "fit_box", "rotate", "flip"],
    aliases: ["put picture on picture", "overlay image", "combine pictures"],
  },
  cutout: {
    basic: ["image", "box", "model", "no_ai", "oval", "keep_regions", "remove_regions"],
    aliases: ["remove background", "cut out subject", "isolate subject"],
  },
  transform: {
    basic: ["image", "crop", "width", "height", "rotate", "flip_horizontal", "flip_vertical"],
    aliases: ["resize", "rotate", "crop picture", "flip image", "change dimensions"],
  },
  deepfry: {
    basic: ["image", "level", "no_tint"],
    aliases: ["deep fry", "fry image"],
  },
  censor: {
    basic: ["image", "box", "style", "block"],
    aliases: ["pixelate", "blur face", "hide face"],
  },
  draw: { basic: ["image", "circle", "arrow", "line", "rect", "color", "width"] },
  eyes: { basic: ["image", "at", "angle", "size", "color"], aliases: ["laser eyes"] },
  filter: { basic: ["image", "names"] },
  flare: { basic: ["image", "at", "size"], aliases: ["lens flare"] },
  sparkle: { basic: ["image", "at", "repeat", "size", "color"] },
  warp: { basic: ["image", "at", "strength"], aliases: ["bulge", "pinch"] },
  watermark: { basic: ["image", "names", "text", "corner"] },
  animate: { basic: ["images", "effect", "frames", "delay", "amount", "at"], aliases: ["make gif"] },
};

export function advancedToolFields(name: string, schema: Tool["schema"]): Set<string> {
  const basic = presentation[name]?.basic;
  if (!basic) return new Set();
  return new Set(Object.keys(schema.properties ?? {}).filter(
    (field) => !basic.includes(field) && !schema.required?.includes(field),
  ));
}

function searchText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function searchTools(tools: readonly Tool[], query: string): Tool[] {
  const phrase = searchText(query);
  if (!phrase) return query.trim() ? [] : [...tools];
  const terms = phrase.split(" ");
  const rank = (tool: Tool) => {
    const name = searchText(tool.name);
    if (name === phrase) return 0;
    if (name.startsWith(phrase)) return 1;
    const aliases = (presentation[tool.name]?.aliases ?? []).map(searchText);
    if (aliases.some((alias) => alias.startsWith(phrase))) return 2;
    const fields = [name, searchText(tool.summary), searchText(tool.category), ...aliases];
    if (fields.some((field) => field.startsWith(phrase))) return 3;
    const words = fields.join(" ").split(" ");
    return terms.every((term) => words.some((word) => word.startsWith(term))) ? 4 : Infinity;
  };
  return tools
    .map((tool) => ({ tool, rank: rank(tool) }))
    .filter((result) => Number.isFinite(result.rank))
    .sort((a, b) => a.rank - b.rank)
    .map(({ tool }) => tool);
}
