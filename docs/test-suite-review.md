# Focused test suite review

Baseline: `361a0ef` (0.1.1). Counts below are collected cases, including parameterized
cases, rather than test functions. The unit/component pool fell from **1,154 to 577**:
Python **1,072 → 536**, frontend **82 → 41**. Cases were deleted, not skipped or folded
into loops to change the count.

## What was removed

Prioritize tests that would catch a distinct failure. Remove repeated happy paths,
static catalog/default assertions, mocked UI actions already covered through the real
core, and Cartesian products that exercise the same validator or renderer repeatedly.
Keep security boundaries, pixel/geometry assertions, concurrency races, recovery and
meaningful algorithms. This is a risk-based reduction, not a claim of equal coverage
for every removed input combination.

Python unit/component cases by changed module:

| Module | Before | After | Main reduction |
| --- | ---: | ---: | --- |
| `test_review_focus.py` | 195 | 0 | Format/tool smoke cross-products and coordinate checks accepting any engine error |
| `test_catalog_parity.py` | 130 | 32 | Duplicated invocation examples, inventories and pinned UI formats |
| `test_params.py` | 156 | 59 | Repeated shared-validator combinations; representative boundaries retained |
| `test_tools_api.py` | 69 | 28 | Repeated schemas and actor happy paths |
| `test_registry.py` | 32 | 14 | Registration and successful dispatch duplicates |
| `test_layouts_packs.py` | 53 | 37 | Per-template determinism smoke; all editable geometry cases retained |
| `test_session.py` | 33 | 19 | Defaults, labels and simple successful operations |
| `test_artifacts.py` | 38 | 25 | Simple metadata, encoding and hash repetitions |
| `test_sheets.py` | 29 | 17 | Basic schema rejection examples; custom constraints and pixels retained |
| `test_agent.py` | 51 | 40 | Fake-provider helpers and repeated approval/error happy paths |
| `test_sources.py` | 59 | 48 | Parser examples and unchanged image orientations |
| `test_foundations.py` | 23 | 15 | Direct dataclass/helper assertions and duplicate image handling |
| `test_creative.py` | 5 | 3 | Static styles/catalog assertions |
| Unchanged unit modules | 199 | 199 | Retained |
| **Python total** | **1,072** | **536** | **536 removed** |

Frontend component cases:

| File | Before | After |
| --- | ---: | ---: |
| `chat-controls.test.tsx` | 7 | 3 |
| `creative.test.ts` | 3 | 0 |
| `desktop-controls.test.tsx` | 4 | 1 |
| `document-replacement.test.ts` | 6 | 3 |
| `errors.test.tsx` | 5 | 1 |
| `forms.test.tsx` | 5 | 2 |
| `idea-mixer.test.tsx` | 3 | 2 |
| `layouts-packs.test.tsx` | 3 | 0 |
| `local-media.test.tsx` | 3 | 1 |
| `session-actions.test.tsx` | 13 | 9 |
| `settings-controls.test.tsx` | 3 | 2 |
| `sprite-sheet.test.tsx` | 7 | 2 |
| `stream.test.ts` | 4 | 3 |
| `studio.test.tsx` | 7 | 3 |
| Unchanged component files | 9 | 9 |
| **Frontend total** | **82** | **41** |

The retained component checks include stale retries, reconnect drafts, changed-document
save/close races, input conflicts, optional parameters, sheet limits, scroll position,
source-card validation, shared download cancellation and deterministic idea selection.

## Coverage outside the cut

All **706 Python integration cases** have the same collected node IDs as the baseline.
These include process, transport, project-file, replay, golden/reference, model and
external-service suites. Boundary suites retain their supporting contract checks as
well. The `unit`/`integration` collection markers in `core/tests/conftest.py` make this
scope inspectable; they do not alter default test selection. Network, downloaded-model
and live-provider opt-ins still apply. The Rust and verification-script suites were
also left intact.

The browser suite grows from **34 to 36** real UI/core workflows. The new project
journeys assert actual imported/rendered/exported bytes, replay dependency remapping,
saved state reopened in a separate core process and profile, non-overwriting repeated
exports, and preservation of current work after opening a damaged project.

Shared fixtures now own startup, authenticated RPC deadlines and cleanup in one place,
retain core logs, and reject unhandled exceptions on every browser page. Vite starts
and closes through its API, avoiding a shell process tree during Windows teardown.
Its strict private port prevents accidentally testing a different development server.
Test files are excluded from Vite's watcher so editing a test cannot reload the app
and erase the document being exercised.

Use the [focused commands](development.md#pick-the-relevant-checks) for future changes.
This review does not require running every remaining test after every edit, and browser
dialog fallbacks do not replace native picker or packaged-installer validation.
