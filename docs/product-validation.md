# Proving that BadShop is worth using

This is a runnable study and free-beta plan, not customer evidence. No participants,
retention, quality scores or provider costs are claimed by creating these materials.
The primary audience is people making shitposts for group chats and small communities.
Creators/community operators and small teams are secondary comparisons.

The release is free for now. Willingness to pay was requested as a professional-quality benchmark,
not a business model. Validate whether people find value and return voluntarily; do not make
pricing, billing or purchase conversion a release gate.

## Product hypothesis

“Turn your own pictures into a deliberately terrible joke, fix the punchline without rebuilding
the image, and share it in a few minutes.” The useful difference is the complete playful workflow,
source reuse and predictable editable pixels. A large tool catalog or AI chat box alone does not
establish value. The free app should be worth the user's time, deliver an image they want to share,
and make the next joke easier. Account and billing infrastructure are outside this release scope.

## Observe first use

Recruit 15 people initially: 10 hobbyists who already post image jokes, 3 creators/community
operators, and 2 people making informal internal/team content. Include people who are not friends
or contributors, a lower-powered computer, each intended OS, and keyboard/large-text users.
Keep source permissions clear; participants can use the bundled CC0 sample instead of private photos.
Use identical candidate builds and record installer hashes. Avoid coaching until a task has failed.

Suggested invitation, for the owner to send only after choosing recipients:

> I'm testing BadShop, a desktop app for making deliberately terrible photo jokes. I'm looking for
> people who already share image jokes, including people who may dislike the app. A session takes
> about 30 minutes. You'll make something, revise it and try sharing it. It isn't a sales call.
> You can use a bundled sample instead of personal pictures. May I send the study details?

At the start, explain what is recorded, who can see it, how long it will be kept, compensation if
any, and that stopping is allowed. Obtain separate permission for screen/audio recording and reuse
of outputs. Do not record private messages, accounts, credentials or recipients' identities.
Ask participants to choose an intended audience and a joke they might actually send.

Tasks, in order:

1. Install/open the candidate and make a first joke without help. Time from first usable window
   to first output, and separately include installation/download time.
2. Make one specific revision without changing the source subject or composition.
3. Keep the original and make another take. Return to the original.
4. Copy/export an image, check it at chat size, and paste into a private scratch destination.
   Sending to another person is optional and entirely the participant's action.
5. Save, close, reopen, and continue editing. Try one failure/recovery scenario using a synthetic
   unsupported file or canceled download, never the participant's only copy of important work.

After each task, record success without help, elapsed time, clicks/decisions that caused hesitation,
errors, assistance, output file/hash, and what the participant expected. Ask what they would change
or actually share, what they normally use, and whether this result was worth the effort. Separate
“funny to the interviewer” from useful to its intended audience. Ask whether they would choose
BadShop again over their current method and why.

Invite an optional 7-day follow-up: voluntary sessions, outputs created, outputs actually shared,
reasons for returning/not returning, and support needed. Use consented diaries or follow-up
interviews; this plan does not authorize hidden telemetry or contacting participants automatically.

## Creative benchmark

The canonical catalog now contains 36 briefs: the existing 12 plus 24 shitpost-focused cases.
Six original fixed cases retain their deterministic fixtures and existing checks.

```sh
uv run --project core --locked python -m badshop.evaluation --all-cases
uv run --project core --locked python -m badshop.evaluation --demo artifacts/verification/creative-baseline
uv run --project core --locked python -m badshop.evaluation runs.json --out comparison.html
uv run --project core --locked python -m badshop.evaluation runs.json --scorecard --out scorecard.json
```

The demo uses scripted calls and proves the comparison mechanism; it does not measure a real model.
For real trials, run all 36 once with the intended default workflow, then repeat the hardest 12
three times on each advertised provider. Keep the same source assets/hashes, input order, initial
saved project, seed, budgets, tool settings and provider version. Use `--cases` for the six original
fixed cases. Freeze source search candidates for art-direction comparisons; separately test live
discovery availability/relevance. Keep manual Quick ideas as a baseline rather than judging only AI.

For the extra briefs, use `app/public/samples/pigeon.png`; derive tall/wide framing and transparent
sticker inputs once, save their exact bytes and record hashes before comparing providers. For
revision cases, retain the unedited saved project and `start_after` step. Use only synthetic or
rights-cleared inputs; a participant's personal picture is not a reusable benchmark fixture by default.

For every run record: candidate revision, case ID, exact prompt, attachments/roles/hashes, provider,
model/CLI/runtime version, OS/hardware, settings/seed, wall time, tool calls, approvals, failures,
retries, final artifact IDs, correction count, spend or “not measured”, and file paths to evidence.
Save each project and use the existing manifest/report format in [creative-evaluation.md](creative-evaluation.md).
Do not silently omit failed runs or count a missing artifact as a completed joke.

Have at least two blinded human raters score 1–5 for subject recognition, joke readability at
320 px, concept distinctness and deliberate badness. Record preference and the concrete reason.
Mechanical pass, aesthetic rating and actual willingness to share are separate outcomes. Resolve
disagreement by preserving both ratings; do not select a flattering reviewer or output afterward.

Proposed product gates to agree before looking at results:

| Gate | Initial target | Why it matters |
| --- | --- | --- |
| First useful result | ≥80% of target hobbyists complete without coaching within 3 minutes after launch | Immediate payoff |
| Revision/share/save | ≥90% finish each task without assistance or lost work | Professional dependability |
| Creative output | ≥80% of intended-default cases judged shareable with at most one correction | Useful AI/manual promise |
| Revisions | No unrelated source/placement changes in caption-only cases | Trust in controllable editing |
| Safety/recovery | No data loss, secret exposure or unresolved high-severity defect | Non-negotiable release condition |
| Repeat use | Predeclare a 7-day target appropriate to the recruited posting frequency | Distinguishes a toy demo from recurring value |

These are product decisions, not universal industry thresholds or statistical proof. A small study
finds failure modes; report denominators and uncertainty, especially for the secondary cohorts.

## Free-beta rollout

After technical gates and observed first-use success, invite 20–30 additional target users to a
free beta. Keep the candidate build and supported-platform list explicit. This is a usability
and repeat-use study, not a pricing experiment. Broaden availability when the observed failure
rate and support burden are manageable.

Draft invitation, for the owner to complete and send after selecting recipients:

> BadShop is a free desktop shitpost workshop for your own pictures. Quick ideas and manual
> editing work without an AI account. This beta supports [tested platforms]. Optional external
> AI providers may charge separately; optional local models need downloads and suitable hardware.
> Known limitations: [candidate-specific list]. Feedback/support: [channel and scope].
> [Download, privacy and release-note links].

Record completed first jokes, actual sharing when users volunteer that information, repeat
creation, reasons for abandoning a task, failures and support minutes. Use consented interviews
or diaries; no hidden telemetry is authorized. Compare initial use with return use and report
sample sizes without inflated precision. Free downloads alone do not establish sustained value.

Before broad distribution, choose support ownership/capacity and estimate distribution, signing
and maintenance costs. Free software still needs reliable delivery and clear expectations. If
hobbyists do not return, investigate the workflow and creative payoff before adding team
administration, a marketplace or a hosted generation service. Monetization is outside the
current release plan and would require a separate future decision.

## Evidence register

Keep dated study consent separately from anonymized observations. Use pseudonymous participant IDs,
access restrictions and the agreed retention schedule. The release report must distinguish observed
sessions, scripted benchmarks and planned work. Current status: study/free-beta plan prepared;
real recruitment, observation, blinded ratings and retention evidence remain external work.
