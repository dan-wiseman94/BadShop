# Release 0.5.4 license review

This review was performed by Codex at the maintainer's explicit request. It does
not describe an independent lawyer's opinion. Final acceptance must reference the
installed-package inspection for the exact 0.5.4 candidate.

## Objective-C bindings

The 0.5.1 installed-package inspection failed on `block2`: its supplemental
`LICENSE.md` described MIT and linked the standard terms, but contained no full
permission notice. The same supplemental explanation was used for all twenty
flagged Objective-C binding packages. The 0.5.3 packaging fix retains that
explanation and adds two unmodified, authoritative upstream notices:

- [Current MIT text, Mads Marquart](https://github.com/madsmtm/objc2/blob/ee9a7ada2131f5944b8750428e265c15632f2a19/LICENSE-MIT.txt).
- [Historical MIT text, Steven Sheldon](https://github.com/madsmtm/objc2/blob/9961247c1a82027d6edbe6c516011b1363b9354c/LICENSE.txt).

The historical notice was removed when upstream introduced its licensing
explanation in [cfb1992](https://github.com/madsmtm/objc2/commit/cfb199226661ec6e4939fcd7cd7531b3c5453076).
Preserving it avoids treating the newer copyright notice as a replacement for
earlier attribution. The declared MIT option is retained; no pending relicensing
proposal is treated as completed. Upstream's [notice discussion](https://github.com/madsmtm/objc2/issues/826)
does not establish that the newly added notice alone covers earlier contributors.

The Apple SDK question is separate from the binding authors' MIT terms. The
[Xcode agreement](https://www.apple.com/legal/sla/docs/xcode.pdf), sections 2.2 and
2.4, permits development with the macOS SDK and distribution of compliant macOS
applications outside the App Store without a separate developer-program
agreement. This release distributes a macOS application linked against system
frameworks, not an SDK or an iOS library. Windows/Linux inventories include
non-host Cargo packages; inclusion in an inventory is not evidence that Apple
framework code executes on those hosts. This is the basis for reviewing the
binding use, not a claim that SDK redistribution is permitted.

The installed-package inspection verifies every inventoried notice against its
recorded hash and verifies the installed SBOM matches the release sidecar. The
MIT and SDK notices for all flagged bindings must be present before approval.

## selectors 0.38.0

`selectors` is unmodified MPL-2.0 covered code. The package inventory copies its
complete crate source into `legal/covered-source/selectors-0.38.0` and retains
the MPL text. The installed-package inspection verifies that source is present
and records its file hashes. The third-party notice tells recipients where that
source is located. This satisfies the distribution approach described in
[Mozilla's FAQ, question 8](https://www.mozilla.org/en-US/MPL/2.0/FAQ/), subject to
verification of the actual source and notice files. No MPL source modifications
or additional restrictions on recipients' rights are introduced.

The source remains available from the [versioned crate download](https://crates.io/api/v1/crates/selectors/0.38.0/download).
Source inclusion in the installer avoids depending solely on that external link.

## Dependency changes since 0.5.3

The Rust and Python dependency locks change only the application version. The frontend adds `@tanstack/react-virtual` 3.14.26 and `@tanstack/virtual-core` 3.19.11. Both registry archives match their committed SHA-512 integrity values, declare MIT, and include the complete copyright and permission notice. This agrees with the [upstream MIT terms](https://github.com/TanStack/virtual/blob/main/LICENSE).

Both new packages' license files have SHA-256 `a405ee70c632bb938acb7ac5f210e814409b3760ea9d2329d8ed8ffcfd11a0e7`. Final installed-package inspection must also verify these notices against the candidate SBOM.

## Exact candidate decision

Approved for source `837ab8c71aceefc33b01f69625023fe6c89ccd00` and SHA256SUMS digest `c76d426930ddfad3dd6361c5702a95e1bcaacd8d96d5e88bda302b3abe3f91b5`.

Codex performed the review and inspections at dan-wiseman94's explicit direction to complete the checks, review licenses, and publish. This is not independent human or legal-counsel review.

All 21 flagged components on each of four platforms were verified (84 decisions). Every installed notice hash matched the SBOM, each installed SBOM matched its release sidecar, all twenty Objective-C binding packages included the MIT and SDK notices, and all 22 files in the selectors registry archive matched the installed covered source byte for byte. The registry archive checksum matched Cargo.lock. The two new TanStack notices matched their integrity-verified registry packages and the installed SBOM notices on all four platforms.

Retained `license-inspection.json` evidence:

- [Windows x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43575254527/artifacts/14105839129)
- [macOS arm64](https://github.com/dan-wiseman94/BadShop/actions/runs/43575254527/artifacts/14105848948)
- [macOS x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43575254527/artifacts/14105474214)
- [Linux x64](https://github.com/dan-wiseman94/BadShop/actions/runs/43575254527/artifacts/14105978340)

Both Mac jobs passed full acceptance. Windows and Linux completed their license inspections but failed later during native process transitions. Their rerun results are recorded separately in the release acceptance record; these license approvals do not turn a failed platform run into a passing one.

