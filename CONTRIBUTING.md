# Contributing to BadShop

Help people make a recognizable joke from their own pictures, share it, and return
to make another. BadShop keeps edits replayable and never uses image-generation
models to create pixels. Hard edges and deliberately rough results are the product.

## Contribute without writing code

- Make a small [character collection or recipe](docs/playful-workflows.md). Follow
  the [pack author guide](docs/pack-authoring.md) before sharing it.
- Report a moment where you could not finish an edit. Include the exact action,
  version and OS; see [support](docs/support.md). Remove private photos and secrets.
- Test keyboard navigation, readable captions and reduced window sizes. Describe
  the blocked task, not just a preference for a different style.
- Join an explicitly recruited [product study](docs/product-study.md). Participation
  is optional; the app does not collect a usage diary automatically.

Use [GitHub issues](https://github.com/dan-wiseman94/BadShop/issues) for proposals.
Avoid posting another person's likeness, a private conversation or copyrighted
material without the right to share it. Do not upload an unreviewed project archive.

## Contribute code

Read [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md) and
[development](docs/development.md). Use an isolated worktree. State a user action,
visible outcome, failure/recovery behavior and persistence check before implementing.
Reuse the existing engine/session/provider/UI owner; avoid a second execution path.

Keep one observable behavior per PR. Run the focused check and the actual affected
workflow; include retained evidence and its limits. Use the PR template's maintenance
cost and safeguard sections. Follow [independent diff review](docs/diff-review.md).
Do not add telemetry, dependencies, settings or extension points without a current
requirement. Signing and publication follow the [release process](docs/releasing.md).

For security reports, use [SECURITY.md](SECURITY.md) rather than a public issue.
