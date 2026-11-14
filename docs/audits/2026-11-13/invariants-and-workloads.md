# Modernization invariant and workload ledger

This ledger tracks W0 characterization against the current implementation. It is
not a new persistence contract. The migration must preserve these observable
behaviors or explicitly document and test a conversion.

| Invariant | Current owner | Canonical regression/evidence |
| --- | --- | --- |
| Encoded bytes identify a blob; identical bytes currently retain first-producer metadata | `session/artifacts.py` | `test_replay.py::test_byte_identical_outputs_keep_their_first_producer` |
| Imports retain original bytes and an editable working image | `Session.import_image` | `test_decode_worker.py` real worker/import/archive workflow |
| Dependency remapping currently pairs positional outputs | `session/replay.py` | `test_replay.py::test_replay_remaps_references_to_new_outputs` |
| A dependency cannot point forward to a later invocation | Session proposal/run validation | `test_state_machines.py::test_session_run_also_guards_approval_edits` |
| Replaying a file-writing tool must not reuse a cached side effect | Session replay | `test_state_machines.py::test_replay_does_not_reuse_a_file_write` |
| Changed engine builds invalidate replay without erasing saved images | Execution cache identity | `test_replay.py::test_reopened_project_replays_after_runtime_changes` |
| Manual changes between failed turn and retry remain visible to the agent | Agent context/run loop | `test_state_machines.py::test_retry_announces_intervening_manual_changes_without_repeating_prompt` |
| A pending approval has an owner and is cleaned after cancellation/disconnect | CoreApp and approval gates | `test_state_machines.py` CLI cancellation/disconnect cases |
| Branch changes cannot redirect queued work into another timeline | CoreApp branch mutation | `test_state_machines.py::test_queued_auto_replay_does_not_run_in_another_branch` |
| Named branches keep independent edits across save/reopen | `session/branches.py` | `test_library_branches.py::test_branches_keep_independent_replay_and_survive_save` |
| Active branch edits made after snapshot creation survive saving | Branch snapshot publication | `test_library_branches.py::test_active_branch_edits_after_create_survive_save_and_next_switch` |
| A failed save leaves the prior file and unsaved state intact | Project writer and CoreApp saved revision | `test_document_state.py::test_save_baseline_survives_autosave_and_failed_save` |
| A failed autosave stays dirty and can retry | CoreApp autosave | `test_state_machines.py::test_autosave_failure_remains_retryable_without_another_edit` |
| Slow imports cannot commit into replacement documents | CoreApp import ownership | `test_state_machines.py::test_slow_import_cannot_cross_a_document_replacement` |
| Reopening branch metadata cannot remove the bounded decoder | Project validation/reference collection | `test_decode_worker.py` parent decoding forbidden regression |
| Export publishes complete bytes without overwriting a concurrent claimant | Session export and atomic file helper | `test_session.py` export byte/race/write-failure cases |
| Local-only policy is enforced in the core | Network policy, provider checks, workers | `test_network_privacy.py` |
| Provider profile replacement retires old owned resources | CoreApp provider cache | `test_cli_provider.py::test_profile_edits_retire_persistent_process_and_directory` |
| Native stderr storage and diagnostic reads remain bounded | Rust supervisor | `logs_rotate_during_one_process_and_diagnostics_read_only_a_tail` |

## Reproducible history workload

The existing `scripts/resource_report.py` now accepts `history`. It uses a generated
32×32 PNG, real invert operations, actual automatic turn checkpoints, project
save/open, exact final bytes, and branch/step count checks. No models or network
are involved. Temporary projects are removed on exit. The report retains raw
edit/checkpoint durations, source hash, archive size, JSON size, process RSS,
save/open latency, repository state and dependency lock hashes.

Run each workload in a separate process in the isolated task environment:

```sh
uv run --project core --locked python scripts/resource_report.py history --steps 30 --turns 5 --output artifacts/verification/history-30.json
uv run --project core --locked python scripts/resource_report.py history --steps 100 --turns 20 --output artifacts/verification/history-100.json
uv run --project core --locked python scripts/resource_report.py history --steps 1000 --turns 100 --output artifacts/verification/history-1000.json
```

The large case is allowed to expose the current archive limit. A rejected archive
produces a failed JSON report and a nonzero exit; it is never used as a passing
performance baseline. This measures session bookkeeping and archive behavior,
not normal-sized image computation, renderer performance, or worker isolation.
Repeat comparable runs before setting budgets. The native smoke workflow already
retains authenticated-renderer startup and process-tree RSS metrics; core smoke
retains repeated real RPC import/edit/save/open cycles.

Still required for W0: measured library/media workloads, renderer interaction
latencies/heap/transfer counts, large-source and animation profiles, baseline
variation, and validation on the lower-powered target. No budget or performance
improvement is claimed from the existence of the measurement command.
