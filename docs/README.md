# BadShop documentation

BadShop makes deliberately rough cut-and-paste images. Start with a Quick idea or
run tools yourself; an optional vision model can direct the same tools. The engine
produces the pixels, and the editable timeline records the work.

These guides describe the source checkout. An installed release may have older
controls; see [compatibility](compatibility.md) and the release's notes.

## Start here

| I want to… | Read this |
| --- | --- |
| Make something without configuring AI | [Your first Quick idea](tutorials/first-shitpost.md) |
| Change an effect and keep editing later | [Manual tools, replay and projects](tutorials/edit-and-replay.md) |
| Preview corrections, pin settings or undo an AI turn | [Manual corrections](manual-controls.md) |
| Have an assistant propose edits I can approve | [Guide an AI art director](tutorials/art-director.md) |
| See the interface before installing | [Screenshot tour](screenshots/README.md) |
| Understand how the app works | [Architecture](architecture.md) |
| Install or troubleshoot | [Windows](windows.md), [macOS](macos.md), [support](support.md) |

## Find material and develop an idea

- [Image discovery, the Junk drawer and branches](image-discovery.md): find a
  source, import a candidate, reuse it, and keep alternate directions.
- [Layouts and packs](layouts-and-packs.md), [retro workbench](retro-workbench.md):
  build compositions from fixed layouts, decorations, palettes and recipes.
- [Local media](local-media.md), [sprite sheets](sprite-sheets.md): extract frames,
  page regions and grid cells from material you already have.
- [Open collections](open-collections.md), [collections and pairing](collections-and-pairing.md):
  choose sources and compare subjects with backgrounds.
- [Idea mixer](idea-mixer.md), [novelty controls](novelty.md): explore a joke and
  vary its setting, format or era.

## Understand your data

Saving a `.badshop` project keeps editable work. Exporting writes a shareable
image. Autosave offers recovery after an interruption; save important projects
explicitly. The [manual-editing tutorial](tutorials/edit-and-replay.md#save-reopen-and-export)
walks through all three.

Read [privacy](privacy.md) for local storage and provider data flow,
[compatibility](compatibility.md) for file formats and optional downloads, and
[model licences](model-licenses.md) for bundled/downloaded assets. For an image
found online, review the source's rights information before reuse.

## Develop and maintain BadShop

Start with [architecture](architecture.md), then [development and testing](development.md).
The [release guide](releasing.md) covers packaging and platform verification;
[creative evaluation](creative-evaluation.md) covers art-direction quality.
The [tool catalogue](../reference/tool-catalog.md) documents the original CLI
surface; the current registry also includes the expansion tools linked above.

The [original design spec](superpowers/specs/2026-09-26-badshop-app-design.md)
records product decisions. Plans, dated audits and verification reports are
historical evidence, not a replacement for the current source or release checks.
Use [state machines](state-machines.md) and [diff review](diff-review.md) when
investigating lifecycle bugs or reviewing a change.

### Maintain the right guide

| Topic | Current owner |
| --- | --- |
| Product rules and original decisions | [Original design](superpowers/specs/2026-09-26-badshop-app-design.md), with its supersession notes |
| Implementation boundaries and data flow | [Architecture](architecture.md) |
| Development, task isolation, verification and maintenance | [Development guide](development.md) |
| Diff review and regression negative controls | [Review guide](diff-review.md) |
| Project formats, provider requirements and platform promises | [Compatibility](compatibility.md) |
| Installers, updates and release gates | [Releasing](releasing.md) |
| Workflow states and recovery rules | [State machines](state-machines.md) |
| Correction previews, pins and turn recovery | [Manual corrections](manual-controls.md) |
| Platform setup | [Windows](windows.md), [macOS](macos.md) |
| Privacy, support and licences | [Privacy](privacy.md), [support](support.md), [model licences](model-licenses.md) |

Update the relevant guide when behavior changes, and link from affected historical
sections rather than treating an old plan as a new implementation requirement.
Documents under `superpowers/plans/` and `research/`, and dated audit/verification
reports, describe their stated revision and date; their proposed work does not
expand the current product scope.

The executable contracts remain authoritative for serialized fields and accepted
arguments: [session models](../core/src/badshop/session/models.py), the
[tool registry](../core/src/badshop/tools/registry.py), and
[RPC handlers](../core/src/badshop/server/app.py).
[wire.generated.ts](../app/src/wire.generated.ts) is generated from the shared
Python models. Manifests and committed lockfiles
own dependency versions. Current verification evidence belongs under
`artifacts/verification/` for the actual revision tested.
