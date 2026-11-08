# Professional release remediation and verification report

Baseline: `079e8a125fc678427ccc0192fa08330d29f7d10b`. Branch: `codex/professional-release-ready`.
The final successful fetch still returned that baseline. The historical
[release and product-value audit](release-readiness-audit-2026-11-07.md) was inherited documentation;
no application changes were inherited. This report covers the subsequent implementation.

## Decision and current status

The intended release is **free**. “Would someone pay for this?” is a benchmark for professional
quality and user value, not a monetization plan. Billing, pricing experiments and paid conversion
are not release requirements. First-use success, useful outputs, repeat use and trust still matter.

BadShop now has a clearer first-use experience for its primary audience: people making shitposts
for friends and small communities. A new user can choose an example, make a joke, change its
punchline, keep another take, and copy/export the result without configuring an AI provider or
downloading a model. The real-core browser journey verifies those operations, including actual
output bytes and clipboard pixels.

The reproduced security defects have fixes and focused regression coverage. Release integrity,
dependency review, privacy documentation, and license inventory are substantially stronger.
This is meaningful progress toward a credible free beta and professional release. Real-user value
still needs observation. The next release is **0.4.0, a free incremental release**; it does not
claim that human usefulness, every provider, or every assistive technology has been validated.
Local core, browser, accessibility and dependency checks now pass. Exact-candidate installed
platform checks remain the publication gate.

A host storage failure interrupted an earlier verification attempt. Source and readable evidence
were backed up; the rescue register preserves 76 unreadable historical files. WSL later became
writable again without this task stopping or repairing the distro. Unused worktrees were archived
and removed at the user's request, recovering about 70 GiB inside Linux. A damaged editable-package
metadata directory was quarantined and reinstalled from the lockfile. Fresh final checks below
supersede the interrupted runs; their original failures remain in the evidence.

## Security, privacy and data integrity

| Audit concern | Implemented behavior | Evidence and remaining boundary |
| --- | --- | --- |
| Imported instructions and malformed history | Validates main/branch transcripts for schemas 1–3; removes privileged imported roles and transient notes; rejects malformed messages, calls/results and remote image references. Quotes current project state at user priority. | Focused project/agent tests cover hostile history, valid compatibility and preservation of the current document after rejected loads. This fixes a concrete privilege boundary; it is not immunity to every semantic prompt injection. |
| Local only during active work | Stops incompatible active/queued providers, CLI activity, approvals and downloads. Rechecks policy before later requests. Native updater work uses scoped core authorization and cancellation; core loss fails closed. | Owned HTTP/SSE tests and five Rust policy tests exercise cancellation races. Actual signed upgrade installation remains a separate platform gate. |
| DNS rebinding | Resolves each hop once and pins the real connection to vetted addresses, preserving TLS/Host identity. Proxy settings cannot bypass it. | Focused network checks passed. The documented user-typed local-URL exception is limited to its first hop. |
| Credentials and local RPC | Non-loopback plaintext HTTP providers need explicit opt-in; changing the URL resets it. WebSocket Origin checks supplement token authentication. Updater credentials cannot act as a user or count as renderer presence. | Profile, WebSocket and updater tests passed. Exact-candidate Windows/macOS WebView behavior remains a platform check. |
| Decoder/media resources | Compressed image decoding and media indexing run in supervised workers with time/memory limits. Parent reconstruction uses raw pixels. Media has status/cancel RPCs and parent-owned scratch cleanup. | Tests include real child timeout/cancel/cleanup. This is an availability boundary, **not an OS privilege sandbox**. Optional PDF decoding was skipped without Poppler. |
| Partial imports/data loss | A 2 GiB aggregate unique-image cap; atomic image batches, library restore and media import. Rollback preserves document/timeline identity and existing deduplicated artifacts. | Real failure reproductions and independent review verify cleanup, state preservation and the queued replay race. |
| Dependencies/model integrity | Patched Python, frontend and desktop dependencies; SHA-256 pins for four background-removal assets; exact-lock security jobs and expiring Rust reviews. | Model hashes were measured after existing size/MD5 verification, not authenticated by upstream signatures. Exceptions are documented below. |
| Browser execution policy | Replaced runtime AJV validation with draft-7-compatible cfworker and removed `unsafe-eval` from production CSP. Python remains authoritative. | Components and production-CSP browser workflow passed. AJV remains development-only because RJSF 6.11.0 exports a test helper importing it; the narrow maintenance exception names its removal condition. |

The independent second pass found five follow-up defects: partial artifact commits, stale
source health, hidden caption-replay errors, media scratch surviving worker termination, and
rollback replacing state used by queued replay. All five were reproduced, fixed and rechecked.
Review and before/after evidence are in `artifacts/verification/release-implementation/second-pass/`.

## Product value and everyday quality

**Quick ideas:** six outcome-led starters with original CC0 pigeon artwork and visible previews.
They reuse existing layout/session execution. Existing users retain the advanced workspace;
new users can begin with a usable example. Creation controls collapse after success.

**Controllable revisions:** caption-only editing preserves picture, layout and headline. Another
take uses existing branches, with a direct return to the original. Replay failures stay visible
and retryable. There is no second project/history implementation.

**Sharing:** a shared export interface serves normal and retro workflows, with dimensions,
format, estimated size, a 320-pixel preview and credits enabled by default. Unconverted exports
preserve selected-artifact bytes; conversion creates a separate history result. PNG preserves
source transparency; opaque golden output remains compatible. Copy image uses actual native
image APIs or the browser clipboard while preserving user-gesture timing.

**Discovery/media:** material type can narrow results to photos, illustrations or objects.
Description relevance precedes existing ranking/diversity. Source health distinguishes failure,
success with zero matches and success with matches, including failed-search history. Media
reports executable availability and allows preview/index cancellation. Unsupported phone formats
explain conversion to PNG/JPEG. Executable presence is not a decoding probe, and fixture tests
are not evidence of current live-source relevance.

**Accessibility:** scalable units and 200% text, larger small-control targets, wrapping headers
and toolbars, measured contrast corrections, and an export dialog with keyboard focus, Escape
close and focus restoration. Final theme checks exposed a wrapped heading overlapping starter
content; a `flex-shrink: 0` correction and regression journey were added but remain unverified
because of the filesystem failure. Automated checks do not establish screen-reader quality or
WCAG conformance.

The frontend production bundle measured 858.74 kB / 272.57 kB gzip after the validator change,
down from 970.61 kB / 308.01 kB gzip. Vite still reports a chunk-size warning. This is a build-size
measurement, not a measured startup improvement. Initial maintenance analysis showed about
1,084 net production lines added; subsequent small fixes are outside that snapshot. New boundaries
serve current callers: updater authorization, bounded decoding, transactional imports and shared
sharing controls.

## Release operations and support

- GitHub Actions references use immutable commit pins. Reusable security checks cover exact
  Python locks, JavaScript dependencies and Rust advisories on PR/main/scheduled runs.
- Installer publication waits for core/frontend/platform/security checks, generates checksums
  and provenance attestations, and creates a **draft** release. PyPI waits for that job. A draft
  is not a public desktop release; the instructions now state that distinction.
- SHA-256 manifests reject duplicate asset basenames and empty release directories.
- Version agreement checks compare all seven application manifests/lockfile records and the
  release tag, preventing an installer from advertising a different version from its core.
- Per-platform CycloneDX inventory collects actual notices from installed build inputs. Missing
  notices fail packaging; MPL covered source is copied into the legal payload. Frozen-core
  metadata collection fails visibly instead of swallowing missing-package errors.
- Added security reporting, support, privacy, compatibility and first-use documentation covering
  downloads, provider costs, local-only semantics, formats, memory needs, source rights and recovery.
- Expanded OS signing/notarization, installed-platform, update and rollback instructions.
  Historical live-provider/installer results are explicitly labelled as historical.

## Verification ledger

Do not add these counts together: focused runs overlap. Later focused passes do not rewrite
an earlier full-suite result. Evidence contains source fingerprints where the harness supports them.

| Check | Actual result |
| --- | --- |
| Broad offline core | Final run: **1,363 passed, 46 skipped**, no failures. Skips are platform-specific or explicitly opt-in (40 macOS, 2 Windows, 1 optional PDF, 2 Gemini, 1 slow MCP). |
| Follow-up import/discovery/media paths | `review-fixes-final.log`: 53 passed, 1 optional PDF skip. |
| Worker/decode/cancellation | `worker-final.log`: 48 passed, 1 optional PDF skip, including child cleanup after timeout/cancel. |
| Frontend components/new validator | 58 passed across 19 files. |
| Production-CSP browser suite | Final run: **43 passed**, including selected/original exported bytes. |
| Quick idea end to end | Creation, narrow revision, variant/return, clipboard pixel digest, exported-byte digest and CC0 credits passed against the real core without a provider or external request. |
| Large text | 900×600, 200% text export/focus journey passed, including the Terminal-theme transition after fixing heading shrink/overlap. |
| Theme accessibility | Final eight-theme sweep passed across populated Quick ideas, Art director and Settings: **24 surfaces**, zero reported axe WCAG A/AA violations. Automated scans do not establish full accessibility conformance. |
| Rust | Broad run: 9 passed. Later updater-policy run: 5 passed. |
| Workflow helpers | Linux broad run: 22 passed. The subsequently added version/tag agreement test passed in a three-test release-integrity run on both Linux and Windows. These are not Windows GUI tests. |
| Maintenance | Final Ruff/Knip and whitespace checks passed; three import contracts and Vulture passed at recorded revisions. Knip retains a narrow documented RJSF development-only exception. |
| Native | Version 0.4.0 source debug and development-launcher workflows passed: native clipboard pixels, Ctrl+V import, core-crash recovery with unsaved session preserved, Cancel/Discard close behavior and no surviving child processes. The shortcut fixes a WebKit paste gap outside editable controls. Source debug results do not establish installer coverage. |
| Creative tooling | All 36 briefs enumerate; deterministic demo/comparison ran. Scripted fixtures are not live AI creativity results. |
| SBOM/notices | Final Linux inventory: **774 components, zero missing notices**, 21 explicit manual-review entries. cfworker MIT/derived-code notices come from its exact source commit. Generated inventory passed CycloneDX 1.6 schema validation. |

Fresh exact-lock Python all-group and JavaScript audits report zero vulnerabilities.
The refreshed Rust audit reports no vulnerability
entries, but **five advisory warnings remain**: glib 0.18.5 unsoundness and four unmaintained
transitive dependencies. Source-graph reachability review and version-exact exceptions expire
**December 7, 2026**. New, changed or expired findings fail the gate. The glib assessment is not a patch.

The 21 licensing review entries include Apple SDK-derived binding notices and an MPL release-source
availability check. Notice collection does not settle legal compatibility or redistribution
obligations; review each actual platform payload before public distribution.

## Remaining gates for a professional free release

| Gate | Required evidence/action |
| --- | --- |
| Finish candidate | Local core/component/browser/accessibility, native lifecycle and dependency checks pass. Complete frozen/installed platform checks for this candidate. |
| Platform coverage | Exact-candidate Windows, Linux and both macOS architectures: install, create/revise/share, save/reopen, recovery, clipboard, native dialogs, keychain and cleanup. Historical passes do not qualify. |
| Trusted distribution | Verify downloaded hashes/attestations and signed updater assets for this release. OS signing/notarization remains a later milestone under the original v1 scope; first-install OS warnings must be disclosed. Test real signed upgrade, failed-update recovery and rollback before claiming those journeys verified. Updater signatures do not replace OS signing. |
| Dependencies/licenses | Inspect each platform inventory/payload, review Apple-derived notices and MPL source availability, resolve or renew justified expiring Rust exceptions. Fresh Linux audits/inventory pass their automated gates. |
| Real creative success | Execute 36 briefs with intended defaults, repeat difficult cases across advertised providers, and obtain blinded human ratings plus time/cost/correction measurements. No live-provider spending was initiated here. |
| User value | Observe 15 first-use sessions: 10 hobbyists, 3 creators, 2 team users. Measure revision/share/recovery success and 7-day return behavior. |
| Accessibility | Manual keyboard/screen-reader review, native dialog/focus checks and representative low-vision users on advertised platforms. |

The [product-validation plan](product-validation.md) supplies a recruitment draft, task script,
36-case benchmark procedure, proposed thresholds and free-beta rollout plan. Initial hypotheses:
≥80% of target users reach a useful result in three minutes, ≥90% finish revision/share/save,
and ≥80% of benchmark outputs are shareable with at most one correction. These are proposed
gates, not observed results or industry standards. Payment and pricing validation are outside
the current release scope.

There is no defensible numerical “percent ready” or remaining calendar estimate before final
candidate verification and user sessions. Technical closure is a bounded queue; user-value
validation may reveal a different product problem.

## Scope decisions

Audit feature ideas were evaluated against the shitpost workflow. Existing replay, takes and
branch history now support narrow revisions. General Undo/Redo spanning AI calls, external files
and persisted state still needs its own semantics and acceptance criteria. More/less ruined,
reusable characters and different settings can already use tools, recipes and creative controls;
further interface work should follow observed friction. HEIC/AVIF ingestion remains unsupported
with a conversion route. Batch/team administration, cloud collaboration, marketplaces, accounts
and subscriptions remain later hypotheses; they would not establish first-use value.

The rule that no image-generation model touches pixels is unchanged. No image generation was
used for the sample artwork, and the proven reference engine was not rewritten.

## Research and evidence references

The historical audit retains the competitive, security, accessibility and release research.
Additional implementation decisions used these primary sources:

- [RJSF cfworker validator](https://rjsf-team.github.io/react-jsonschema-form/docs/api-reference/validator-cfworker/): draft-7 validation without runtime code generation.
- [cfworker MIT notice](https://github.com/cfworker/cfworker/blob/1a0aa37471850c28a4673e12e871e010ea6c26e0/LICENSE.md) and [derived-code notices](https://github.com/cfworker/cfworker/blob/1a0aa37471850c28a4673e12e871e010ea6c26e0/THIRD_PARTY_NOTICES.md): the published package's source commit.
- [Tauri Windows signing](https://v2.tauri.app/distribute/sign/windows/) and [macOS signing/notarization](https://v2.tauri.app/distribute/sign/macos/): platform release gates.
- [Mozilla Public License 2.0](https://www.mozilla.org/en-US/MPL/2.0/): covered-source obligations.
- [Microsoft WSL recovery guidance](https://learn.microsoft.com/en-us/windows/wsl/disk-space): diagnosis of the storage interruption; no repair claimed.

Evidence: `artifacts/verification/release-implementation/` in the isolated Linux worktree,
with a separate Windows backup and historical rescue error register. The PR and release workflow
record exact commits, installed-platform results, signed assets and publication status; this report
does not treat pending checks as passes.
