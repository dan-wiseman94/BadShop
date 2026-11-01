import type { LayoutDefinition } from "./types";

type Choice = { id: string; name: string; direction: string; query?: string };
export const jokeChoices: Choice[] = [
  {
    id: "ordinary-hero",
    name: "Hero of a tiny achievement",
    direction:
      "Treat a trivial everyday accomplishment as a world-changing victory.",
  },
  {
    id: "status-reversal",
    name: "The wrong person is in charge",
    direction:
      "Put the subject in charge of something absurdly beyond their authority.",
  },
  {
    id: "bureaucracy",
    name: "Bureaucracy gone wrong",
    direction:
      "Invent a very official procedure for an extremely silly problem.",
  },
  {
    id: "oversized",
    name: "An inconveniently huge prop",
    direction:
      "Make one ordinary prop comically enormous; show the practical inconvenience.",
  },
  {
    id: "product",
    name: "A product nobody needed",
    direction:
      "Sell the subject or their least useful talent as an unnecessarily serious product.",
  },
  {
    id: "ominous",
    name: "Ominous everyday announcement",
    direction:
      "Present an ordinary inconvenience as a dramatic warning or breaking event.",
  },
  {
    id: "literal",
    name: "A saying taken literally",
    direction:
      "Choose a familiar saying about the subject and make its literal meaning visible.",
  },
  {
    id: "rivalry",
    name: "An extremely petty rivalry",
    direction:
      "Stage a high-stakes competition over something laughably insignificant.",
  },
];
export const settingChoices: Choice[] = [
  {
    id: "office",
    name: "Office meeting",
    direction: "A dull office meeting with an overly serious presentation.",
    query: "office conference room",
  },
  {
    id: "museum",
    name: "Museum gallery",
    direction:
      "A museum exhibition treating the subject as a priceless object.",
    query: "museum gallery interior",
  },
  {
    id: "shop",
    name: "Bargain shop",
    direction: "A cramped bargain shop with loud price signs.",
    query: "grocery shop storefront",
  },
  {
    id: "space",
    name: "Mission control",
    direction:
      "Mission control carrying out an unnecessarily elaborate operation.",
    query: "NASA mission control room",
  },
  {
    id: "kitchen",
    name: "Domestic kitchen",
    direction:
      "A domestic kitchen where a small task has become a major production.",
    query: "kitchen interior",
  },
  {
    id: "stadium",
    name: "Sports arena",
    direction:
      "A stadium presenting a very small achievement to an enormous audience.",
    query: "sports stadium crowd",
  },
  {
    id: "school",
    name: "School assembly",
    direction: "A school assembly with improvised awards and awkward ceremony.",
    query: "school auditorium stage",
  },
  {
    id: "garden",
    name: "Formal garden",
    direction: "A formal garden disrupted by an unsuitable visitor or object.",
    query: "formal garden landscape",
  },
];
export const eraChoices: Choice[] = [
  {
    id: "victorian",
    name: "Victorian print",
    direction:
      "Victorian illustrated notices, engraved borders and earnest captions.",
    query: "Victorian illustration",
  },
  {
    id: "silent-film",
    name: "Silent-film era",
    direction: "Silent-film publicity, theatrical poses and blunt intertitles.",
    query: "1920s photograph",
  },
  {
    id: "midcentury",
    name: "1950s advertising",
    direction:
      "1950s catalog advertising with confident promises and simple shapes.",
    query: "1950s advertisement",
  },
  {
    id: "cable",
    name: "1980s cable television",
    direction:
      "1980s local cable graphics, block lettering and overserious announcements.",
    query: "1980s photograph",
  },
  {
    id: "desktop",
    name: "1990s home computer",
    direction:
      "1990s home-computer graphics, chunky UI boxes and clip-art decorations.",
    query: "1990s computer",
  },
  {
    id: "forum",
    name: "2005 internet forum",
    direction:
      "2005 forum signatures, mismatched cutouts and emphatic short captions.",
    query: "digital camera photograph",
  },
];
export type MixerLocks = {
  joke: string;
  setting: string;
  era: string;
  format: string;
};
export const emptyLocks: MixerLocks = {
  joke: "",
  setting: "",
  era: "",
  format: "",
};
export type MixerFormat = Pick<LayoutDefinition, "id" | "name">;
export type MixedIdea = {
  key: string;
  joke: Choice;
  setting: Choice;
  era: Choice;
  format: MixerFormat;
  subject: string;
  prompt: string;
  search: string;
};

/** A finite pool guarantees termination even when every dimension is locked. */
export function mixIdeas(
  subject: string,
  locks: MixerLocks,
  formats: MixerFormat[],
  seed: number,
  recent: string[] = [],
) {
  const choose = <T extends { id: string }>(items: T[], id: string) =>
    id ? items.filter((item) => item.id === id) : items;
  let pool: Omit<MixedIdea, "subject" | "prompt" | "search">[] = [];
  for (const joke of choose(jokeChoices, locks.joke))
    for (const setting of choose(settingChoices, locks.setting))
      for (const era of choose(eraChoices, locks.era))
        for (const format of choose(formats, locks.format))
          pool.push({
            key: [joke.id, setting.id, era.id, format.id].join("/"),
            joke,
            setting,
            era,
            format,
          });
  const total = pool.length;
  const unseen = pool.filter((idea) => !recent.includes(idea.key));
  const repeated = total > 0 && unseen.length === 0;
  if (unseen.length) pool = unseen;
  let state = seed >>> 0 || 1;
  const random = () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 4294967296;
  };
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  const picks: typeof pool = [];
  const dimensions = ["joke", "setting", "era", "format"] as const;
  while (pool.length && picks.length < 6) {
    // Prefer distinct meanings, settings and layouts within the same batch.
    const scores = pool.map((idea) =>
      dimensions.reduce(
        (score, dimension) =>
          score +
          (locks[dimension] ||
          picks.some((pick) => pick[dimension].id === idea[dimension].id)
            ? 0
            : 1),
        0,
      ),
    );
    const best = scores.indexOf(Math.max(...scores));
    picks.push(pool.splice(best, 1)[0]);
  }
  const subjectText = subject.trim() || "the subject in my attached images";
  return {
    total,
    repeated,
    ideas: picks.map((idea) => ({
      ...idea,
      subject: subjectText,
      search: `${idea.setting.query} ${idea.era.query}`,
      prompt: [
        `Make a deliberately bad cut-and-paste image about ${subjectText}.`,
        `Joke: ${idea.joke.direction}`,
        `Setting: ${idea.setting.direction}`,
        `Era: ${idea.era.direction}`,
        `Format: ${idea.format.name}. Use the editable layout template "${idea.format.id}".`,
        "Keep the attached subject recognizable. Find supporting backgrounds or props only as needed; inspect source candidates before importing them.",
        `Possible source searches: "${idea.setting.query}" and "${idea.era.query}". These are search suggestions, not images already found.`,
        "Use a short caption that adds to the visual joke. Inspect the final image for readability and accidental obstruction.",
      ].join("\n"),
    })),
  };
}
