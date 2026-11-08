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

## Six fixed briefs

The full catalog now has 36 briefs, including 24 release cases focused on shitpost creation,
chat-size readability, narrow revisions, variants, transparency and offline recovery.
Use `--all-cases` to print the full catalog; `--cases` keeps the original six fixed fixtures.
See [product-validation.md](product-validation.md) for the study protocol, provider run matrix,
scoring, evidence requirements and paid-pilot draft. Additional briefs are prompts to run and rate,
not claims that models have passed them.

Print the representative prompt set:

```sh
uv run --project core python -m badshop.evaluation --cases
```

The six cases cover distinct takes, correct attachment selection, restraint, caption fit, a
headline-only revision, and a light deep fry. Generate the fixed input cards and a complete
offline example in a new directory:

```sh
uv run --project core python -m badshop.evaluation --demo artifacts/verification/creative-demo
```

Open `comparison.html` there to see intentionally faulty and corrected examples. The demo uses
scripted tool calls, synthetic input cards and ordinary saved projects. It also writes `runs.json`
and `scorecard.json`. For real model comparisons, reuse the demo's input cards and
`inputs/preserve-concept-seed.badshop` for the headline revision. Keep the provider/model, seed, step budget,
and other settings fixed between runs. Record source queries and candidates separately when
testing live discovery, because results can change independently of the model.

## Portable comparison report

Create a JSON manifest, with project paths relative to the manifest:

```json
[
  {"case_id": "museum", "phase": "before", "label": "Baseline", "project": "before.badshop", "artifact_id": "BASELINE_OUTPUT", "inputs": {"painting": "PAINTING_ID", "duck": "DUCK_ID"}},
  {"case_id": "museum", "phase": "after", "label": "Candidate", "project": "after.badshop", "artifact_id": "CANDIDATE_OUTPUT", "inputs": {"painting": "PAINTING_ID", "duck": "DUCK_ID"}}
]
```

Then build the report:

```sh
uv run --project core python -m badshop.evaluation runs.json --out comparison.html
uv run --project core python -m badshop.evaluation runs.json --scorecard --out scorecard.json
```

Use final artifact IDs from the step details or session data. `phase` puts the baseline and
candidate side by side. For a three-take run, add all three selected outputs to the same phase
with distinct labels. Older manifests without phases or inputs still work. Use `start_after`
for the last step before a revision request on the active timeline. Set `expect_export` only
when the brief or the assistant's claim calls for an export.

The HTML embeds the selected bytes and the same deterministic checks as the JSON. Checks
trace the selected output through completed steps and check supplied attachment roles. They
look for identical bytes within a phase, fully off-canvas single pastes, determinable caption
clipping, and fixed-brief violations. A recorded export confirms a successful step for that
artifact. Its current file presence remains unverified, and the report never opens recorded
export paths. Missing role IDs and unavailable geometry appear as unknown. Repeated calls,
repeated output hashes, and paste retries are advisory counts of recorded agent and CLI steps.
Use `start_after` to isolate those counts from earlier work.

Rate subject recognition, joke readability, distinctness of concept, and deliberate badness from
1 (fails) to 5 (strong). Record specific failures and select a preferred result. Download ratings
as JSON to keep them. The browser can also remember ratings when local storage is available.
Use `--force` to replace an existing report. The report generator makes no provider calls.
