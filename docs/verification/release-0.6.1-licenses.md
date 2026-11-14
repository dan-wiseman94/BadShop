# Release 0.6.1 license review

Approved for source `c5fe4977ce5db62c918cb1ffca116aabfe8fbdb6` and SHA256SUMS
digest `903eae433903d4c2fdecff4e8de03bbb06e8e5a2f0a585abb20897d4cdc72d30`.
Codex performed this review at dan-wiseman94's explicit direction to make the
release. This is not independent human or legal-counsel review.

## Installed candidate inspection

All 21 flagged components on each of four platforms were inspected (84 decisions).
Every installed notice hash matched its SBOM, and each installed SBOM matched the
release sidecar. All twenty flagged Objective-C binding packages included the MIT
and SDK notices. All 22 files in the selectors 0.38.0 registry archive matched the
installed covered source byte for byte; the archive checksum matched Cargo.lock.

The four candidate SBOM component/version sets match 0.5.4 except for BadShop's own
version. The manual-review packages and reasons are unchanged. New development
tools in the source lockfile are not represented as bundled runtime dependencies.
This comparison does not substitute for the installed-candidate inspections.

Retained `license-inspection.json` evidence:

- [Windows x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43629656695/artifacts/14128050766)
- [macOS arm64](https://github.com/dan-wiseman94/BadShop/actions/runs/43629656695/artifacts/14127911263)
- [macOS x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43629656695/artifacts/14127582357)
- [Linux x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43630037656/artifacts/14128151918)

These inspections completed before subsequent UI automation failures in some of
those runs. They approve the inspected license material only. Passing platform
acceptance is recorded separately in [the acceptance record](../../packaging/release-acceptance/v0.6.1.json).

## Basis for the decisions

The Objective-C bindings retain both the [current MIT notice](https://github.com/madsmtm/objc2/blob/ee9a7ada2131f5944b8750428e265c15632f2a19/LICENSE-MIT.txt)
and the [historical MIT notice](https://github.com/madsmtm/objc2/blob/9961247c1a82027d6edbe6c516011b1363b9354c/LICENSE.txt).
The declared MIT option is used; a proposed upstream licensing change is not
treated as completed. Keeping both notices preserves historical attribution.

The Apple SDK terms are separate. Sections 2.2 and 2.4 of the
[Xcode agreement](https://www.apple.com/legal/sla/docs/xcode.pdf) provide the basis
for building and distributing this macOS application outside the App Store.
BadShop links system frameworks; it does not redistribute the SDK. Cargo packages
listed in a Windows or Linux inventory do not imply Apple framework execution on
those hosts. The [0.5.4 review](release-0.5.4-licenses.md) records the unchanged
binding-notice history and distribution rationale.

For unmodified MPL-2.0 `selectors`, the installer includes complete crate source
under `legal/covered-source/selectors-0.38.0`, the MPL notice, and directions to
that source in its third-party notices. This follows the executable-distribution
approach in [Mozilla's FAQ, question 8](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).
Recipients have the source in the installed package, in addition to the
[versioned upstream archive](https://crates.io/api/v1/crates/selectors/0.38.0/download).
No source modifications or additional restrictions are introduced.
