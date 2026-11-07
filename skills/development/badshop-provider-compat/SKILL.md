---
name: badshop-provider-compat
description: Diagnose and verify BadShop provider compatibility when Claude Code, Codex, Gemini CLI, LiteLLM, or an OpenAI-compatible endpoint changes. Use for stream formats, MCP images, approvals, cancellation, and conversation resume; not for generic model recommendations.
---

# BadShop provider compatibility

Establish which provider behavior works at a named version and fix the requested
compatibility issue. Preserve BadShop's session execution and approval gate: the
provider directs tools while the deterministic engine owns the pixels.

## Establish the contract

Resolve the active BadShop worktree from the task. Read its `AGENTS.md`, design
spec, and relevant development documentation. Paths below resolve from that
worktree, not this skill. Use a task-isolated environment and record the revision
and inherited changes as described in `docs/development.md`.

Identify the provider, platform, executable path/version or API model and endpoint,
the failing user action, and expected result. Read current source and the installed
CLI's `--help`/`--version`; verify changing upstream contracts against official
provider documentation. Historical design-spec flags are not proof of compatibility.

| Concern | Source and existing tests |
| --- | --- |
| CLI discovery, launch flags, private config/auth, streams, resume, cleanup | `core/src/badshop/providers/cli_provider.py`, `core/src/badshop/providers/cli_turn.py`, `core/src/badshop/providers/windows_job.py`; `core/tests/test_cli_provider.py`, `core/tests/fixtures/cli/` |
| API streaming, fragmented tool calls, capability overrides, errors, images | `core/src/badshop/providers/litellm_provider.py`; `core/tests/test_litellm_provider.py` |
| Profile configuration and first-turn behavior | `core/src/badshop/providers/profiles.py`; `core/tests/test_provider_profiles.py`, `core/tests/test_provider_start.py` |
| MCP images, authorization scope, approval waits, heartbeats, disconnect | `core/src/badshop/mcp/proxy.py`; `core/tests/test_mcp_proxy.py` and the relevant session/server implementation |
| Real CLI and API smoke contracts | `core/tests/test_cli_live.py`, `core/tests/test_live_provider.py` |

Confirm these paths exist in the tested revision; use `rg` to locate renames. Read
only relevant files. Record versions without printing tokens, authentication files,
environment secrets, or private prompts.

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

## Exercise the affected behavior

Define acceptance for the failing flow and affected adjacent behavior:

- Stream text and complete tool arguments correctly, including multiple calls,
  malformed/unknown events, interrupted output, and readable provider errors.
- Return actual MCP image content through `view`; maintain artifact references
  after resumed/retried turns and retain the intended conversation identifier.
- Execute tools through the core session and honor approve/edit/reject. Preserve
  approval heartbeats and appropriate deadlines; do not bypass waits by allowing
  unrestricted tools or disabling the approval gate.
- Stop/cancel releases streams and pending approvals, keeps completed steps, and
  terminates owned processes and descendants, including on Windows.
- Preserve supported CLI authentication through task-private configuration.
  Custom endpoints must not receive unrelated ambient provider credentials.

Use existing fixtures and a minimal reproduction first. Add or update a regression
test for the observed defect or changed contract, with redacted transcripts when
needed. Do not rewrite pixel algorithms or change unrelated provider profiles.

Before running checks, state the named regression or affected test file and the
one end-to-end provider/session workflow selected, with the purpose of each.
Confirm current test names and commands in
`docs/development.md#pick-the-relevant-checks`. Start with that minimum selection,
not both whole CLI and MCP files automatically.

Prefer real session/MCP execution and persisted artifacts, image bytes, resume,
recovery, and process cleanup over several mocked assertions. Retain focused unit
checks for parsing boundaries, security, concurrency, and algorithms that an
end-to-end check cannot reliably isolate. Do not consolidate tests into loops or
giant cases merely to lower their count.

Documentation-only changes need no application tests. Deleted tests need
collection/lint checks, not unrelated application behavior. Do not default to
`./verify.sh quick`, `browser`, `desktop`, `all`, entire unit suites, or installer
rebuilds. Broaden only for a changed shared dependency/fixture, a failure, an
identified coverage gap, a release requirement, or explicit user request; explain
the reason first. Once relevant checks pass, stop unless a later edit changes inputs.

Retain commands, outcomes, and evidence under `artifacts/verification/`. Consult
the installed `badshop-verification` skill for the private Arch WSL route and
native/installer coverage. Focused commands must run in the task's isolated Linux
worktree, never in the launcher's setup checkout.

## Live checks are a separate result

Inspect current live test files before enabling their switches. Run real requests
only when the task authorizes the chosen provider and account usage; reuse
authorization already given. Installing this skill alone does not authorize a
provider call. Otherwise finish fixtures and state the live coverage gap.
Keep credentials out of commands, logs, fixtures, and project files.

- `test_cli_live.py`: `BADSHOP_LIVE_CLI` selects `claude`, `codex`, or `gemini`.
  Optional model, total timeout, and redacted tracing use
  `BADSHOP_LIVE_CLI_MODEL`, `BADSHOP_LIVE_CLI_TIMEOUT_S`, and `BADSHOP_LIVE_CLI_TRACE`.
  Its current smoke inspects a generated fixture image and resumes the same
  conversation; it does not prove every approval or cancellation flow.
- `test_live_provider.py`: `BADSHOP_LIVE_MODEL` and optional
  `BADSHOP_LIVE_API_BASE` select the target. Cloud calls additionally require
  `BADSHOP_LIVE_ALLOW_CLOUD=1`; the optional key is read from
  `BADSHOP_LIVE_API_KEY`. `BADSHOP_LIVE_TOOL_CALLS=false` exercises the fallback,
  and `BADSHOP_LIVE_TIMEOUT_S` bounds the call. Its current smoke checks vision
  plus a tool request, not the complete desktop agent workflow.

Use `-m live` with the selected test file and scope switches to that child process.
Do not persist switches in user settings or expand to other providers. Stop at the
authorized scope or budget rather than retrying paid calls indefinitely; report
authentication, quota, or upstream blockers.

## Compatibility report

Record revision, OS, provider/CLI/library versions, redacted reproduction, changed
contract, test commands/outcomes, and evidence paths. Separate fixtures, real local
server tests, actual provider calls, and native/installer coverage. Skipped live
checks remain unverified. One smoke does not establish other versions or platforms.

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
