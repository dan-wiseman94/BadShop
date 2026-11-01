# Comparing badshop results

The chat composer offers six composition styles and a **Three takes** action. A style changes
source selection, layout, typography, and restraint. Three takes requests different premises or
compositions, retains separate final artifacts, and asks the agent to identify each result. It
uses more tool steps than a single image; the usual provider and step limits still apply.
These controls send visible instructions in the user message, so saved sessions and CLI providers
retain the chosen direction. Models may still fail to follow the brief; the evaluation below
measures that rather than assuming success.

The canonical style catalog is `core/src/badshop/agent/creative_styles.json`, used by the desktop
and system prompt. Pixel work still goes through the existing deterministic tools. The art director is instructed to give every finished
take a visual check for recognizable subjects, a readable joke, caption fit, and accidental
occlusion, within the existing one-or-two-corrections budget. Rough seams are intentional.

## Fixed prompts

Print the representative prompt set:

```sh
uv run --project core python -m badshop.evaluation --cases
```

Each case lists the input photos to supply and what a reviewer should inspect. Keep the actual
input files, provider/model, seed, step budget, and other settings fixed between comparison runs.
For source-discovery changes, record queries and candidates separately: changing live catalogs
makes repeated retrieval different even when the engine is deterministic. Save each run as a
`.badshop` project. Use the final artifact ID from its step details or session data; do not select
a contact sheet or a grid view as the finished result.

## Portable comparison report

Create a JSON manifest, with project paths relative to the manifest:

```json
[
  {"case_id": "dog-boss", "label": "Before", "project": "before.badshop", "artifact_id": "YOUR_ARTIFACT_ID"},
  {"case_id": "dog-boss", "label": "After — take 1", "project": "after.badshop", "artifact_id": "ANOTHER_ARTIFACT_ID"}
]
```

Then build the report:

```sh
uv run --project core python -m badshop.evaluation runs.json --out comparison.html
```

Open the HTML file in a browser. It embeds the selected original artifact bytes, needs no server
or network access, groups results by prompt, and shows their dimensions and recorded step counts.
Rate subject recognition, joke readability, distinctness of concept, and deliberate badness from
1 (fails) to 5 (strong). Record specific failures and select a preferred result. Download ratings
as JSON to keep them; browser storage alone is not a durable archive. Use `--force` only to replace
an existing report. The command itself makes no paid provider calls and assigns no humor scores.
