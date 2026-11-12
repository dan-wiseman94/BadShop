# Review a BadShop diff for avoidable mistakes

Give the following prompt and the base-to-head diff to a human or AI reviewer with read access
to the checkout. Run the review separately from writing the change so the reviewer can trace
callers and inspect the assertions independently.

> Review this BadShop diff against its stated acceptance criteria. Trace the changed behavior
> through the normal UI, CLI, or RPC entry point. Look for duplicated behavior where an existing
> path should be reused, retries or broad catches that turn errors into apparent success, and
> tests that assert a toast or mock call without checking the promised file, pixels, state, or
> process cleanup. Check compatibility with older project data when persistence changes.
> Look for removed guards whose failure mode the tests would miss.
> What can this change delete? Does it introduce a second source of truth? Does each
> new abstraction reduce actual duplication or isolate a real boundary? Check that
> replacements remove obsolete paths and dependencies, and that compatibility code
> names its supported version/format and removal condition. Review the maintenance
> growth report; file size alone is not a finding.
> Inspect its safeguard-change section and the PR's rationale. Does an updated expected
> result hide a regression? Does removing an assertion, adding a skip, or expanding an
> analyzer exception lose failure coverage? Check the actual remaining test. Review
> resource reports against a comparable baseline when present; missing measurements
> are not zero. Identify unrelated cleanup and maintenance cost without a current caller.
>
> For each actionable finding, give a file and line, the input or sequence that triggers the
> problem, the wrong observable result, and the smallest test that would distinguish it.
> Read the surrounding code before claiming a duplicate or a swallowed failure. State which
> tests you actually ran. Omit style-only comments and unsupported guesses. If no issue meets
> that bar, say so.

Review findings are advisory. Verify a proposed finding against the code or a focused reproduction
before treating it as a defect. For a high-risk guard, use the targeted negative controls below.

## Prove a regression test detects a broken guard

For a new bug fix, run its test on both the broken and fixed revisions and retain both logs. For
these existing invariants, the opt-in probe runs the same test against the working source and
against a temporary source copy with exactly one guard removed.

```sh
uv run --project core --locked python scripts/prove_regression.py all --out artifacts/verification/guard-probes
```

Run `paste-size`, `document-ownership`, or `approval-dependency` individually when changing one
boundary. Success requires the working test to pass and the guard-removed test to fail on the
expected missing exception. A timeout, unrelated failure, or changed mutation site fails the
probe. The script preserves logs and a summary and discards its temporary source and app data.
