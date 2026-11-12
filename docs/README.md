# Current BadShop documentation

Start here for current behavior. The original design records product intent and
architectural decisions; dated plans and audits record history, not current setup
commands or proof that a newer revision passed verification.

| Topic | Current owner |
| --- | --- |
| Product rules and original architecture | [Original design](superpowers/specs/2026-09-26-badshop-app-design.md), with its supersession notes |
| Development, task isolation, focused verification, maintenance | [Development guide](development.md) |
| Diff review and regression negative controls | [Review guide](diff-review.md) |
| Project formats, provider requirements, platform promises | [Compatibility](compatibility.md) |
| Installers, updates, release gates and current platforms | [Releasing](releasing.md) |
| Current workflow states and recovery rules | [State machines](state-machines.md) |
| Windows / macOS source and installed setup | [Windows](windows.md) / [macOS](macos.md) |
| Privacy, support and licenses | [Privacy](privacy.md), [support](support.md), [model licenses](model-licenses.md) |

The executable contracts remain authoritative for serialized fields and accepted
arguments: `core/src/badshop/session/models.py`, the tool registry, and the RPC
handlers. `app/src/wire.generated.ts` is generated from the shared Python models.
The manifests and committed lockfiles own dependency versions.

When behavior changes, update its current owner in the same change. Add a link at
the affected historical section if it could otherwise direct an implementer to
reintroduce old behavior. Preserve historical decisions and evidence as history.

Documents under `superpowers/plans/` and `research/`, and dated audit/verification
reports, describe their stated revision and date. Their proposed work is not a
standing instruction to expand product scope. Current acceptance evidence belongs
under `artifacts/verification/` for the actual revision under test.
