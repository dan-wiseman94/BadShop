# badshop — project notes for Codex

- The design spec is `docs/superpowers/specs/2026-09-26-badshop-app-design.md`. Read it
  before doing anything; it records the decisions and why.
- `reference/badshop.py` is the proven engine (single-file CLI, PEP 723 deps). Its port
  lives in `core/src/badshop/` (src layout: `engine/`, `tools/`, `cli/`); do not rewrite
  its pixel logic. `reference/tool-catalog.md` lists every command and parameter; the
  tool registry must cover all of them.
- `reference/SKILL.md` is how an LLM currently art-directs the engine. Its workflow and
  style rules become the agent's system prompt.
- Non-negotiable product rule: no image-generation model ever touches pixels. Hard edges,
  nearest-neighbor scaling, no blending. Bad is the deliverable.
- The user's machine: Arch Linux, KDE Plasma 6 (Wayland), `uv` available, `sudo` needs a
  password (so no unattended system package installs).

## Development and verification

- Multiple agent sessions may be working on BadShop at the same time. Record the latest
  `origin/main` commit at the start of the task after fetching. Before handoff or
  integration, fetch again and compare `origin/main` with that starting commit. If it
  has advanced, review the intervening changes for overlap and report anything that
  affects your work. If the fetch fails, report that you could not verify the remote tip.
- Use an isolated worktree for each task. Prefer the agent platform's managed worktree
  tool when available; otherwise follow `docs/development.md`. Reuse an existing worktree
  for the same task. Do not stash, reset, or commit unrelated work in the user's checkout.
- A new worktree starts from a commit, not uncommitted changes. When the task depends on
  current work, copy the tracked diff and relevant untracked files into the worktree,
  record the baseline, and distinguish inherited changes from your own. Never share a
  Python virtualenv between worktrees: editable installs can point at the wrong source.
- Define concrete acceptance criteria before implementation. Include the user action,
  expected visible result, persistence/error behavior, and cleanup where applicable.
  Use the acceptance matrix in `docs/development.md` as a starting point.
- Run only the minimum relevant tests for new or changed behavior. Start with the named
  test case or affected test file, plus the one end-to-end workflow that exercises the
  change. State that selection and its purpose before running it. Documentation-only
  changes need no application test run. A deleted test needs collection/lint checks,
  not a rerun of unrelated application behavior.
- Do not run `./verify.sh quick`, `browser`, `desktop`, `all`, an entire unit suite, or
  rebuild installers by default. Broaden only for a changed shared dependency/fixture,
  a failure, an identified coverage gap, a release requirement, or an explicit user
  request. Explain the reason first. Once relevant checks pass, stop testing unless a
  later edit changes their inputs. See `docs/development.md#pick-the-relevant-checks`
  for commands selecting individual Python, component, and browser tests.
- Prefer a meaningful end-to-end regression over several mocked component assertions.
  Check persisted data, actual output pixels/bytes, recovery and cleanup where relevant;
  a toast or a mocked function call alone does not prove that the user's task succeeded.
  Keep focused unit tests for boundary conditions, security, concurrency and algorithms
  that an end-to-end check cannot reliably isolate. Do not replace removed tests with
  loops or giant combined tests just to lower the reported count.
- Verify user-visible changes through the actual affected workflow whenever possible.
  Distinguish mocked checks from real integration tests. Report exactly what was exercised
  and what remains unverified. If the environment prevents verification, investigate
  available alternatives before stopping. On Linux, try the private Xvfb workflow before
  concluding that the absence of DISPLAY prevents native testing.
- Keep automated tests away from the user's actual settings, projects, credentials, and
  desktop input. The native runner uses a private display and temporary app data.
  Keep model downloads, network tests, and live provider calls outside the quick suite.
- Retain logs, screenshots, traces, and `summary.json` under `artifacts/verification/`.
  A missing prerequisite, timeout, skipped layer, or failed build is not a passing check.
  Never describe browser prompt fallbacks as verified native dialogs or a source debug
  build as a tested installer. See `docs/releasing.md` for packaged-platform validation.
