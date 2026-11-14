# Release 0.5.2 license review

This review was performed by Codex at the maintainer's explicit request. It does
not describe an independent lawyer's opinion. Final acceptance must reference the
installed-package inspection for the exact 0.5.2 candidate.

## Objective-C bindings

The 0.5.1 installed-package inspection failed on `block2`: its supplemental
`LICENSE.md` described MIT and linked the standard terms, but contained no full
permission notice. The same supplemental explanation was used for all twenty
flagged Objective-C binding packages. The 0.5.2 packaging fix retains that
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
