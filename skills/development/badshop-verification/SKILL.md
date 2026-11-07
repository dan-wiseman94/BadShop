---
name: badshop-verification
description: Verify BadShop development changes and release candidates using focused tests and relevant end-to-end workflows. Use for BadShop testing, regression diagnosis, or release validation, including the private Arch WSL setup on Windows.
---

# BadShop verification

Produce evidence for the behavior changed in the task. Use the repository's
verification harness and maintained documentation as the source of truth.

## Resolve the revision and acceptance criteria

- Locate the BadShop checkout from the current task, including an attached managed
  worktree. Confirm `verify.sh`, `core/pyproject.toml`, and `app/src-tauri/` exist.
  Repository paths below resolve from that checkout, not this skill's folder.
- Read `AGENTS.md`, `docs/superpowers/specs/2026-09-26-badshop-app-design.md`, and
  relevant sections of `docs/development.md`. Read `docs/releasing.md` for
  packaging or installer work. Current user instructions override these references.
- Reuse the task's isolated worktree or create one with the available managed
  worktree tool. Otherwise follow `docs/development.md`.
- Record source commit/status and the inherited baseline before editing. Carry
  over the tracked binary diff and relevant untracked files needed by the task
  without changing the original checkout. Give each worktree its own Python
  environment; never copy another checkout's editable install.
- Define acceptance through the user action, visible result, persistence,
  errors/cancellation, and owned-process cleanup where relevant. Use the
  acceptance matrix in `docs/development.md`.

## Check concurrent work

At task start, fetch with `git fetch origin main` and record
`git rev-parse origin/main` alongside the task HEAD and inherited changes.
Before handoff or integration, fetch again and compare origin/main with that
recorded starting commit. If it advanced, inspect the intervening commits and
diff for overlap with the task's code, tests, fixtures, and instructions; report
anything affecting the result. Do not automatically merge, rebase, reset, or
overwrite concurrent work. Reconcile relevant changes within the authorized task
and rerun only checks whose inputs changed. If either fetch fails, report that
the remote tip could not be verified; a cached ref is not a verified current tip.
When an older worktree has stale instructions, inspect the latest AGENTS.md and
development guidance without replacing unrelated working changes.

## Select the minimum relevant checks

Before running checks, state the named test case or affected test file and the
one end-to-end workflow selected, explaining what each proves. Use
`docs/development.md#pick-the-relevant-checks` for current Python, component,
and browser commands. Confirm test names in the revision under test.

- Start with the named regression or affected file. Add the real end-to-end
  journey exercising the changed behavior, especially across the UI/core boundary.
- Prefer a meaningful end-to-end regression over several mocked assertions.
  Check persisted data, output pixels/bytes, recovery, and cleanup as relevant;
  a toast or mocked call alone does not establish success.
- Keep focused unit checks for boundaries, security, concurrency, and algorithms
  that the end-to-end workflow cannot reliably isolate. Do not combine tests into
  loops or giant cases merely to reduce the reported count.
- Documentation-only changes need no application tests. Deleted tests need
  collection/lint checks, not unrelated application behavior.
- Native picker, clipboard, drag/drop, keyboard, keychain, window, or process
  lifetime changes need the actual affected platform interaction.
- Do not run `./verify.sh quick`, `browser`, `desktop`, `all`, entire unit suites,
  or rebuild installers by default. Broaden only for a changed shared
  dependency/fixture, a failure, an identified coverage gap, a release requirement,
  or an explicit user request. Explain that reason before running broader checks.
- Once relevant checks pass, stop unless a later edit changes their inputs.

When broader checks are justified, select the appropriate harness mode using
`docs/development.md`; use `docs/releasing.md` for required installer coverage.
`doctor` diagnoses prerequisites, not runtime correctness.

On this Windows PC, read [the private Arch WSL procedure](references/windows-wsl.md)
before Linux checks. Focused commands must also run in the task's isolated Linux
worktree through the private launcher. Local native desktop automation uses private
Xvfb; it does not run on the user's desktop.

## Run, diagnose, and retain evidence

- Let the harness create `artifacts/verification/<run>/`, or use its `--output`
  option. Retain `summary.json`, logs, screenshots, and traces. For focused commands
  outside the harness, retain command, revision, exit status and log in a separate
  evidence summary rather than modifying the harness's results.
- Use temporary app data and the private display. Keep tests away from the user's
  projects, settings, credentials, and desktop input. Clean up only processes and
  temporary state owned by this run; preserve evidence.
- Inspect the failed stage's log, address its cause, and rerun the failed focused check plus checks with newly affected inputs. A missing prerequisite, skip, timeout, or blocked build
  remains visible. Do not repeat expensive passing checks without a changed input
  or unresolved concern.
- If `DISPLAY` is absent on Linux, use private Xvfb through the harness. Follow the
  prerequisite guidance; do not attempt unattended sudo installs.
- Keep model downloads, network tests, and real provider requests separate from
  ordinary checks. Reuse existing explicit authorization for live checks when
  available; otherwise finish fixture-based work before requesting the missing
  provider/cost decision.

## Report the boundary of the result

State the tested revision and inherited changes, behavior exercised, commands and
actual outcomes, evidence paths, and remaining gaps. Browser prompt fallbacks do
not establish native-dialog behavior. Linux debug/launcher checks do not establish
installer coverage or Windows/macOS behavior. Scripted provider tests do not
establish live model compatibility or output quality.

## Repository workflow helpers

Read the current development guide for helper usage. scripts/task.py start
records the fetched remote baseline and acceptance criteria; finish reports
upstream/local-worktree overlap without integration. scripts/verify.py supports
focused python, component, and selected browser checks with evidence and rejects
empty selections. Omitting the mode displays help. scripts/wsl_task.py prepare transfers
the task to a reusable isolated Linux worktree and checks its import path; never
overwrite unexpected Linux edits.

On this Windows PC, when full runs are warranted and worker flags are supported,
use quick --core-workers 4 or browser --browser-workers 2. Run them apart from
CPU-heavy builds and use serial runs to diagnose timing failures. Keep task
worktrees warm for follow-up changes. These flags do not authorize broader tests.

This skill's canonical source is under skills/development/ in BadShop.
Use scripts/sync_skills.py to review/update installed copies without losing edits.
