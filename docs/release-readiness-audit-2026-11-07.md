# BadShop professional release and product-value audit

**Subsequent scope clarification:** BadShop will remain free for now. The owner's “would someone
pay?” question was a benchmark for professional quality and value. Paid-launch/pilot recommendations
below are historical analysis, not the current release plan. See the
[implementation report](release-implementation.md) and [user-validation plan](product-validation.md)
for the updated free-release scope; pricing and payment are not release gates.

**Audit date:** November 7, 2026

**Release-status cutoff:** approximately 22:44 UTC; the report does not predict subsequent CI or publication results.

**Primary audience:** hobbyists making shitposts; independent creators second; designers and small teams third.

**Audited source:** 0ee20840e2c47c9e478b57dc76ccfe508310bbbe.

**Final upstream review and targeted recheck:** 23b7fce794b52ca7db430ae1d75d90755b6a4645; see section 12 for changes merged during the audit.

**Published release examined:** v0.2.0, built from 5e48f916c615d64308ae5f71300ba749fef5a4d4.

**Scope:** product value, willingness to pay, creative outcomes, onboarding, interaction design, accessibility, performance, reliability, security, privacy, providers, packaging, delivery, maintenance, support, licensing, and a practical release plan.

This is an independent engineering and product assessment, with source review, fresh isolated checks, controlled reproductions, actual UI inspection, release-job inspection, and primary-source research. It is not a customer study, exhaustive penetration test, or certification. Findings below distinguish observed defects, dependency advisories, historical evidence, product judgments, and work that remains unverified. No real customer images, settings, credentials, or desktop input were used. No paid model requests were made.

## 1. Decision

**BadShop has enough substantive functionality to become a worthwhile paid niche product. I would not call the current revision ready for a broad, professional paid launch.** The strongest next milestone is a reliable, immediately enjoyable beta for people who want to make shitposts, followed by a paid pilot.

The implementation is substantially more mature than a prototype. It has deterministic editing, inspectable and replayable steps, saved projects, recovery, approvals, multiple provider integrations, reusable assets, recipes, branching, visual comparison, source attribution, and installers for three operating systems. Fresh persistence and native-lifecycle checks passed. There is a distinctive product here.

During the audit, main gained guided on-device basic edits and signed in-app update support. Those are material improvements and are credited below. All four controlled security/reliability reproductions still occurred when rerun against that newer revision. The native/UI measurements retain their original revision labels.

The largest gap in value is **getting an ordinary person from an idea to a funny image they actually want to send, with little setup and little supervision**. That outcome has not been established by the codebase's feature count, passing transport tests, or existing example galleries. The current interface exposes much of the machinery before proving the payoff.

The largest release blockers are concrete:

1. A locked image-decoding dependency has applicable published security advisories.
2. “Local only” does not stop subsequent API requests in an already-running turn.
3. Imported projects can inject a high-priority provider message or contain malformed history that breaks the next turn.
4. The public-address download policy can be bypassed through DNS rebinding.
5. The release process has an actual PyPI publishing failure, unsigned desktop distribution, and gaps in integrity, update, and support practices.
6. The populated editor has reproduced accessibility problems, and the primary casual-user journey needs simplification and validation.

Professional quality for this product means dependable, effortless delivery of intentionally rough images. It does not require a general-purpose design suite. More effect families, enterprise features, or image-generation models would not resolve the current launch problems. The rule that no image-generation model touches pixels should remain intact.

### Readiness by dimension

| Dimension | Assessment | Why |
| --- | --- | --- |
| Distinctive concept | Strong enough to test commercially | Real-image compositing, deliberately crude style, transparent steps, and iterative variants form a coherent niche. |
| Functional breadth | More than enough for the next milestone | 36 tools, six composition directions, 16 general layouts, 28 retro layouts, packs, recipes, branches, and multiple acquisition routes already exist. |
| Immediate fun for a first-time hobbyist | Needs a focused product pass | Manual onboarding exists, but the landing workspace remains dominated by chat/provider concepts and an empty canvas. |
| Reliable creative success | Promising, not established | A real Claude workflow was historically verified; broad real-model, real-brief performance and human preference data are missing from the evidence inspected. |
| Persistence and recovery | Comparatively strong | Fresh real-core save/reopen/export and damaged-project checks passed; native crash recovery passed. |
| Security and privacy | Release-blocking findings | Decoder advisories and three reproduced trust-boundary/policy defects need resolution. |
| Accessibility and compact-window usability | Partial | Focus trapping worked in the checked dialog; populated-state contrast, target size, and incomplete text scaling need work. |
| Distribution and update experience | Beta quality, improving | Installers have meaningful CI coverage; in-app updater code has now landed, while OS signing, real signed-upgrade validation and support promises remain release work. |
| Willingness to pay | Unproven | Comparable products establish that the category can charge; they do not establish demand for BadShop. |
| Team/agency readiness | Premature to prioritize | Rights assurance, support, predictable throughput, and organizational administration would add substantial scope. |

## 2. Would someone pay for it?

### The likely answer

**Some technically comfortable meme and retro-art enthusiasts plausibly would. A broad casual audience has not yet been given a sufficiently effortless reason to pay.** This is my product judgment, not a measured conversion forecast.

The enthusiast can appreciate local files, editable history, unusual compositions, reusable heads and props, and the freedom to make something ugly on purpose. Someone already paying for a compatible AI service may find BadShop a useful creative interface.

The newly merged on-device assistant makes basic requests available without an account or API key after an optional download. This directly improves the entry proposition. Its deliberately limited one-edit workflow is not equivalent to the broader multi-step art director; market those capabilities separately.

A casual hobbyist is buying amusement and social payoff. Their comparison is the fastest way to make a joke for a friend, group chat, or community. They are unlikely to assign much value to MCP, provider diversity, tool schemas, deterministic artifact hashes, or another settings page. They experience those capabilities as value only when the joke lands faster, survives revisions, and is easy to share.

For an independent creator, the attractive outcome is a recognizable visual voice and repeatable series: the same recurring subject, a new scenario, reliable captions, and several alternatives. Existing recipes, junk drawer, branches, and comparison already support this. The task is making them easy to discover and use.

For a designer or small team, BadShop could become a specialist companion for rough collages, campaign exploration, and recurring absurdist content. It currently lacks evidence sufficient to promise predictable production delivery across all providers and platforms. Do not let that secondary audience turn the first launch into a full design-platform project.

### A sharper promise

A useful positioning hypothesis is:

> Turn your photos and half-formed jokes into ridiculous, editable shitposts. Keep the real images. Change the joke. Make it worse on purpose.

Test the wording with the intended audience. “2005 forum-style” is a clear niche, but it can also imply that all outputs are nostalgic Impact-font memes. The newer layouts and composition tools support a wider range of visual jokes. Show that range with actual finished images rather than a list of eras.

The core value loop should be:

1. Bring a picture or choose a ready-to-use example.
2. Pick a recognizable outcome or describe a joke.
3. Get something understandable quickly.
4. Make one obvious correction or choose a different premise.
5. Copy or export it into the place the user wanted to share it.
6. Return later because making the next joke feels easier.

A session that runs many tools but leaves no image the user wants to send is a product failure, even when every tool behaved correctly.

### Competitive reality

These are primary-source observations checked for this audit. Prices and plans can change, and advertised capability is not an independent quality test.

| Alternative | What the customer can already obtain | Implication for BadShop |
| --- | --- | --- |
| Imgflip | Large template access in the free tier; paid tiers remove ads/watermarks and add creation features. Its page lists Basic at $4.95/month with annual billing and Pro at $11.95/month. [Imgflip plans](https://imgflip.com/pro-basic) | Captioning a familiar template is not enough differentiation. BadShop must win on compositing, personal specificity, control, or the overall experience. |
| Kapwing | Free meme creation with templates and uploads; its current free exports carry a watermark. [Meme maker](https://www.kapwing.com/meme-maker) | A smooth, private, watermark-free desktop workflow can be valuable, but a simple export must feel at least as straightforward. |
| Supermeme | Text-to-meme positioning and included credits; its Solo plan is advertised at $6.49/month billed annually. [Pricing](https://supermeme.ai/pricing) | “Type a joke, get memes” already exists as a category. BadShop must demonstrate the particular compositions and editable results it does better. |
| Mosh / Mosh-Pro | A free browser entry point; the paid product emphasizes deeper effects, reusable projects/presets, batch export, and higher-resolution output. Its current page advertises $49/year. [Official product](https://moshpro.app/) | The closest useful lesson is immediate visual gratification followed by deeper control. A distinctive creative toy can support paid functionality. |
| Photopea | A capable raster/vector editor that runs on the device in a browser; free and Premium accounts exist. [Introduction](https://www.photopea.com/learn/), [accounts](https://www.photopea.com/api/accounts) | “It edits locally” and “it has many tools” are not sufficient reasons to switch. BadShop's distinctive workflow matters more. |
| Canva | Photo editing, templates, captions and an integrated path from editing to download. [Photo editor](https://www.canva.com/photo-editor/) | Customers expect obvious output formats and a short path to a finished image. There is little benefit in competing on general design breadth. |
| Pinterest Shuffles | Mobile collage creation and sharing within an existing social ecosystem. [Official help](https://help.pinterest.com/en/article/shuffles) | Phone-first creation is a real alternative for casual collage. Desktop BadShop should first win a specific desktop use case; mobile expansion is a later evidence-based decision. |
| Aseprite | A focused creative tool sold with signed installers, updates, and support; its FAQ lists a $19.99 minimum purchase. [Official FAQ](https://www.aseprite.org/faq) | Buyers pay for focused creative tools and a dependable surrounding service. This is an analogy, not evidence that BadShop can charge the same price. |

### Monetization recommendation

Do not commit to a subscription before establishing repeat use. For the local architecture, now including optional basic on-device AI and BYO providers for broader direction, my first experiment would be a **one-time purchase or paid supporter edition**, with a clear update/support period and optional genuinely useful packs later.

Test offers around **$9, $19, and $29** with real purchase intent. These are experimental price points, not a valuation or an estimate of the market-clearing price. A free/manual trial or clearly limited preview should let users experience the distinctive result before paying.

There are three viable models to investigate:

| Model | Why it might fit | What must be true |
| --- | --- | --- |
| One-time desktop purchase | Matches occasional creative play and user-owned files; avoids another recurring bill | Support and update costs remain sustainable; AI access is clearly described as separate when applicable. |
| Free core plus paid edition/packs | Reduces trial friction and may encourage a community | Paid extras must offer real convenience or distinctive content; basic sharing should not feel deliberately obstructed. |
| Hosted AI credits or subscription | Could remove API-key and CLI setup | Requires measured inference cost, privacy/retention rules, abuse controls, billing/refunds, service operations, and reliable creative completion. This is a larger product change. |

BadShop's MIT licensing permits commercial distribution while retaining notice obligations. It also means the current source is not a defensible paywall. Convenience, curation, identity, support, trusted distribution, and continuously useful workflows are more plausible reasons to buy. Do not casually change licensing to manufacture a moat. [MIT license](https://opensource.org/license/mit)

If using hosted inference, track **cost per image the user keeps**, including failed attempts, searches, retries, and discarded takes. Token cost per successful API request is an incomplete business metric. A 40-tool step limit is not a monetary spending limit. The current provider reply contract does not expose a product-level token/cost budget.

For every proposed paid offer, calculate:

**Contribution per buyer = collected revenue − payment/store fees − refunds − hosted usage − allocated support/update costs.**

Use measured inputs. There is no defensible revenue forecast in the present evidence.

## 3. Product and interaction findings

The direct UI observations and screenshots below are from 0ee2084. The final upstream review credits its new on-device welcome/setup route in section 12; it does not treat the original screen as the exact current first-run screen.

### P-01 — The first-run experience asks the user to understand too much before the payoff

**Priority: high for the primary audience. Evidence: observed UI and source.**

There is a real “Edit a photo without AI” route and clear first-edit instructions. After choosing it, however, the workspace still shows “Choose your art director,” approval mode, a large art-direction pane, novelty and style selectors, and a chat composer. “Connected” is shown even when no provider is configured; it describes the local core connection, but can easily be read as AI readiness.

At 1280 × 720, much of the interface is devoted to an inactive chat workflow and an empty step history. At the supported minimum 900 × 600, the three panes leave the canvas particularly narrow. The interface is visually coherent, but its information hierarchy suits someone learning the system better than someone seeking a quick laugh.

**Change:** make the first screen an immediately usable creative starting point. Offer a small set of visual, outcome-based choices such as caption, deep fry, fake error, ridiculous head swap, and three different situations. Include a licensed sample. Remember the user's chosen mode. Let manual users start in a canvas-led workspace and make AI an obvious optional enhancement.

**Acceptance:** a new nontechnical participant can create and export a recognizable, personally chosen result without configuring AI or reading developer documentation. Measure unassisted completion and time to the first image they would send. Keep advanced controls available through progressive disclosure.

Evidence: [Welcome implementation][code-welcome], [chat][code-chat], screenshots in the evidence appendix.

### P-02 — The strongest playful features are buried inside a broad utility dialog

**Priority: high. Evidence: observed UI and feature inventory.**

“Images & directions” contains ten top-level areas, including discovery, retro workbench, idea mixer, junk drawer, branches, layouts/packs, local media, sprite sheets, image pairs, and recent choices. Retro workbench has another six sections. Several of the most immediately enjoyable actions live behind these layers.

The raw tool palette also exposes implementation vocabulary: acquire, pair_images, retro_layout, export_profile, and “inspect retro.list.” It is valuable for advanced users, but is a demanding primary interaction for a toy.

**Change:** surface six to eight curated starting actions and a visual favorites/recent strip. Reuse the existing tool registry and workflows underneath. Put acquisition and reuse near the image, creative choices near the result, and low-level parameters behind an “Adjust” affordance. User-facing labels can be plain language without renaming engine commands or breaking recipes.

**Acceptance:** users can find a suitable style, change the caption, and make an alternative without knowing tool names, artifact IDs, or which tab contains the feature.

### P-03 — Creative quality needs a demonstrated success rate

**Priority: launch gate for AI-led marketing. Evidence: existing evaluation support; missing outcome evidence.**

The system prompt already instructs the art director to inspect final images, preserve recognizable subjects, avoid hidden captions, and make three distinct premises. The repository has six fixed briefs, a saved-project checker, a before/after HTML gallery, and human rating controls. Those are useful foundations, and should be reused.

They are not proof that models reliably follow the instructions. The offline demo uses scripted calls and synthetic input cards. Historical tests establish some real vision/tool compatibility and one complete Claude composition, not a measured share-worthy success rate across a product audience. [Creative evaluation][doc-evaluation], [historical verification][doc-history]

**Change:** run the existing briefs against the one or two configurations actually recommended to customers, then add representative user jokes. Record all attempts, latency, failures, final files, revisions, and cost. Score joke comprehension, subject preservation, text readability, controllability, and whether the user would send it. Keep “deliberate badness” separate from accidental failure.

A rough cutout can be excellent. An unrecognizable intended subject, cropped punchline, irrelevant source image, repeated take, or false claim that a file was exported is not a successful result.

### P-04 — Sharing should become a primary action

**Priority: high. Evidence: source and observed export.**

The existing export flow works and the browser journey checks actual bytes. There are exact-size export profiles and an export-with-credits route. The current native clipboard integration provides text copying and image input; I did not find an output-image clipboard action. General export and specialized profile/credits preparation are separated across the UI.

For a shitpost, the endpoint is often a chat, not a project file. Saving into Pictures and revealing a folder is useful, but creates an extra step.

**Change:** add “Copy image” and a simple export panel showing the selected result, dimensions, format, file size, destination, and any available attribution. Preserve PNG transparency and animated-output semantics; say clearly when the clipboard carries a still image. Make “Keep this version” and “Make another” adjacent to the result.

Test output in the actual applications users share to. Do not promise that an animated GIF survives every clipboard or chat integration.

### P-05 — Protect the joke's readability at the intended sharing size

**Priority: high for defaults; style-dependent. Evidence: one observed manual example.**

I imported the repository's Lincoln fixture, entered “CHECKING ONE EMAIL” / “3 HOURS LATER,” built the default GeoCities layout, and exported its PNG. The operation completed successfully, and the subject stayed recognizable. In the fitted editor preview, the title and caption were tiny. At 900 × 600, the result displayed at roughly 28% and the joke was difficult to read.

This does not invalidate pixel-era layouts: tiny bitmap furniture is part of their style. It does mean they should not automatically be treated as legible modern feed posts.

**Change:** provide a preview at typical sharing size and a way to add a large punchline outside the retro frame. Test caption bounds and readability separately. Preserve exact requested text or explain why it will not fit. Avoid forcing the user to inspect tool parameters to understand the tradeoff.

Do not replace the established pixel logic to make outputs generically prettier. Also clarify the technical claim about nearest-neighbor scaling: the inherited import-preparation path deliberately uses Lanczos when shrinking a source, while composition/retro operations preserve their intended hard-edged behavior. [Import preparation][code-common]

### P-06 — Image discovery is useful, but breadth does not equal joke relevance

**Priority: medium-high. Evidence: live public-source search plus source review.**

A default “angry cat” search completed in **4.9 seconds**, returning four cat photographs and four museum/amulet objects. It displayed rights metadata and source links. This is a successful live discovery example, not a comprehensive service-availability or relevance benchmark. Acquisition was initiated separately but not observed through completion before the private browser was closed, so it is not counted as a passed live import.

The current ranking uses transparent metadata/geometry heuristics. It does not establish identity, pose, expression, or humor. Some web/photo providers need separate credentials. The UI accurately marks configuration requirements.

**Change:** rank relevance first, then diversity; offer an obvious photo/illustration/object preference; keep successful sources usable when others fail; and display source health separately from “configured.” For the primary audience, a small collection of ready-to-use, rights-reviewed examples and recurring personal subjects may be more valuable than another ten sources.

### P-07 — Familiar editing actions deserve a thin, understandable layer

**Priority: medium-high. Evidence: source and manual workflow.**

Editing step parameters, replaying, deleting the last step, branching, and comparison already provide substantial control. The mental model remains more technical than ordinary undo/redo and “change this one thing.”

**Change:** evaluate a history-oriented Undo/Redo interface backed by existing session semantics; rename/label finished variants; keep the original subject easily selectable; and expose “same composition, new caption,” “same joke, different setting,” and “more/less ruined” directly. The novelty and “worse” features already provide much of the underlying behavior. Avoid building a second state or execution engine.

### P-08 — Accessibility has concrete defects, alongside working foundations

**Priority: high for fixes; remaining manual verification required.**

Fresh axe checks on the empty main screen, tool palette, and retro gallery found no automatic violations, with contrast items left for manual review. That result changed in the populated editor.

At 900 × 600 with the app's 150% text preference, axe reported:

- The completed-step status at **4.09:1** contrast, below the relevant 4.5:1 threshold.
- Step metadata at **4.44:1**.
- Two remove-attachment targets measuring **16 × 16 px** with insufficient spacing.
- Additional checks requiring manual review.

The text-size preference changes the root font size, but many interface labels remain fixed at 9–12 px. The screenshot confirms that large buttons grow while much of the small explanatory/status text does not.

The checked Settings dialog did move focus inside, trap Tab from its last control back to the close button, and return through Escape. A global trap exists in App.tsx. A claim that the app has no focus management would be incorrect.

**Change:** use consistent scalable typography, repair contrast tokens in selected states, enlarge or space small controls, and test the populated editor in every shipped theme. Test native screen readers, keyboard-only editing/approvals, 200% scaling, reduced motion, error announcements, and file dialogs. Treat WCAG 2.2 AA and the ARIA dialog pattern as useful engineering targets, not a claim of current certification. [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [modal-dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

Evidence: [root text scaling][code-app-scale], [attachment and timeline styles][code-style], axe logs and screenshots in the appendix.

### P-09 — Put requirements and limits where a casual user encounters them

**Priority: high for truthful onboarding.**

Models/fonts download on demand. The default U2-Net file is about 168 MiB; optional BiRefNet is about 928 MiB, and the historical Linux measurement peaked at 9,328 MiB RAM. Video extraction needs FFmpeg; PDF extraction needs Poppler. Current image import accepts PNG, JPEG, GIF, WebP, BMP and TIFF, not a general promise of every phone format such as HEIC or AVIF.

At the initial revision, provider setup involved installing/authenticating a CLI, supplying an API key, or operating a local vision server. The final upstream revision adds guided on-device setup for basic edits. Its pinned model and image projector alone total about 748 MiB, plus a platform-dependent runtime; the Linux CUDA selection adds approximately 746 MiB of runtime/libraries. “Local only” remains a network policy, separate from setting up that assistant. Keep the limited assistant's capabilities clear.

**Change:** show a short readiness checklist for the chosen workflow, model download size/progress/cancellation, and a direct manual fallback. Provide a useful message for unsupported phone formats. Ship a clear tested hardware/OS matrix and explain that exports based on reduced working copies do not magically recover source detail.

Bundle inexpensive essentials where licensing and package size permit; keep very large optional models optional. The priority is predictable first use, not eliminating every byte from the installer.

## 4. Security and privacy findings

Severity here describes the potential consequence and the evidence available. “Release blocker” is a prioritization judgment for this product, not a claim that every issue enables remote code execution. No destructive payloads, memory-exhaustion samples, real credential exfiltration, or third-party systems were attacked.

### S-01 — Update the image decoder and isolate hostile decoding

**Severity: high. Release blocker. Status: affected locked version and reachable decode paths confirmed; individual CVE exploitation not attempted.**

The audited environment and core lock use **Pillow 12.3.0**. The package scan returned 39 Pillow advisory records. Several apply directly to accepted image families:

| Primary advisory | Relevance | Published fix |
| --- | --- | --- |
| [TIFF/JPEG strip memory disclosure](https://github.com/python-pillow/Pillow/security/advisories/GHSA-q45j-58j2-45rg) | Crafted accepted TIFF content may expose uninitialized process memory through decoded pixels | Pillow 13.0.0 |
| [PNG Exif quadratic processing](https://github.com/python-pillow/Pillow/security/advisories/GHSA-g4qv-2jxx-769h) | PNG decoding/Exif processing is on normal import and web-image paths | Pillow 13.0.0 |
| [BMP RLE allocation amplification](https://github.com/python-pillow/Pillow/security/advisories/GHSA-24rc-8hj2-v98c) | BMP is accepted for local/project imports; small declared dimensions do not guarantee low memory consumption | Pillow 13.0.0 |

The decoder allowlist and pixel limit are valuable, but cannot neutralize bugs within the allowed decoders. Import and project decoding run in the core's worker threads rather than the resource-limited tool subprocess. A blocked decoder can therefore affect the core and hold a session operation open. The TIFF consequence is especially relevant when the same process manages provider credentials.

**Remediation:** update to a currently patched compatible Pillow release, regenerate the lock, verify deterministic/golden image behavior, and test the frozen builds on every supported platform. Plan process isolation and time/memory bounds for untrusted decoding, not only editing tools. Preserve the proven engine semantics rather than rewriting its pixel logic.

**Regression:** representative safe/corrupt PNG/JPEG/GIF/WebP/BMP/TIFF inputs; bounded decoder-failure tests; project rejection without losing the open document; a release-build smoke after the shared dependency change. Do not execute hazardous vendor proof-of-concepts on the user's normal environment.

Evidence: [locked dependency][code-lock], [import decoder][code-artifacts], [core import entry][code-import], [Pillow 13 release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html).

### S-02 — Local-only mode permits further API traffic in an active turn

**Severity: high privacy defect. Release blocker. Status: reproduced through normal RPC dispatch and the real LiteLLM adapter.**

Sequence:

1. Configure an API profile pointed at an audit-owned loopback HTTP server.
2. Start a turn and pause its first response.
3. Set no_remote to true through settings.set.
4. Release a valid canvas tool call.
5. Observe a second POST containing the new image while local-only remains enabled.

The result recorded two requests: the second arrived after the toggle and included image content. No external provider or real key was involved.

The UI says “Local only (block downloads and cloud providers).” The provider is checked when created, but the already-running loop retains it. Settings application does not cancel that turn, and the loop does not recheck policy before each completion. This is an actual mismatch between a privacy control and behavior.

**Remediation:** define an atomic policy transition. Stop incompatible active turns and downloads, invalidate pending starts, and recheck policy before every outbound request. Communicate when the transition has completed. Do not silently allow another image upload after showing the setting as active.

**Regression:** the owned-server scenario must receive no second request after activation; cancellation, queued provider setup, CLI processes, and active asset downloads need corresponding coverage.

Evidence: [provider check][code-provider-check], [settings application][code-settings-apply], [completion loop][code-loop], [local-only UI][code-local-only], audit-local-only/summary.json.

### S-03 — Imported transcripts cross the model-instruction trust boundary

**Severity: high model-integrity risk. Release blocker before encouraging project sharing. Status: message forwarding reproduced; model obedience/external action not tested.**

A crafted but otherwise loadable .badshop project can put an arbitrary entry with role “system” into its transcript. The stored transcript is copied into the next API message list after the application's own system prompt. The audit marker reached that list as a system message.

This elevates data supplied by another project author into a high-priority model instruction. It can affect the art director's decisions and claims. Existing tool permissions and approvals still apply; this finding is not evidence of arbitrary shell execution or unrestricted filesystem access.

**Remediation:** treat imported history as untrusted. Reconstruct trusted app change notes from validated state; strip, reject, or demote externally supplied system/developer messages; and use a documented transcript schema with compatibility handling. Apply the rule to saved branch transcripts too.

**Regression:** an imported project cannot add a trusted model instruction, while legitimate older projects retain usable history and unchanged pixels.

Evidence: [untyped transcript fields][code-models], [context construction][code-context], audit-security-probes/summary.json.

### S-04 — Malformed transcript entries survive opening and break the next AI turn

**Severity: medium reliability defect. Fix with S-03. Status: reproduced.**

A project containing an assistant entry with a tool_calls array containing an empty object opened successfully. Constructing the next provider context then raised **KeyError: 'id'**.

Project validation is careful about step IDs, parameters, artifact hashes, branches and ZIP structure, but does not validate the provider-history structures that context construction assumes. A user can therefore open a project that appears valid and only encounter the damage when continuing a conversation.

**Remediation:** validate role/content/tool-call shapes, identifiers, ordering, bounds and references on load. Offer a clear recovery path that retains images and edit history while dropping unusable conversation history where safe. Never replace the current document with a partially accepted one.

**Regression:** malformed main and branch history must be rejected clearly or recovered explicitly; the next AI turn must not fail with an internal KeyError.

Evidence: [project validation][code-project], [tool-call reconstruction][code-answered], audit-security-probes/summary.json.

### S-05 — Resolve-then-connect allows a DNS-rebinding policy bypass

**Severity: medium-high, depending on reachable local services. Release blocker for unrestricted remote sourcing. Status: controlled network-policy bypass reproduced.**

The public-address guard resolves a hostname and checks the returned IPs. urllib resolves again when connecting. The source explicitly describes this as best-effort protection.

The audit supplied a public answer for validation, then loopback for connection, using an audit-only hostname and an owned local HTTP server. The protected downloader received the server's marker. This proves the check and the connection can disagree; it does not constitute an attack against a real router or cloud metadata endpoint.

A malicious image URL or remote source could use this class of discrepancy to reach local HTTP services, undermining the stated public-network boundary.

**Remediation:** bind the connection to vetted resolved addresses, preserve the original Host/TLS identity, and validate every redirect and retry. Account for proxies and IPv4/IPv6 behavior. Retain the explicit, deliberate user-typed-URL exception if that remains the product policy.

**Regression:** controlled rebinding cannot reach the local marker; redirects, encoded host forms, mapped addresses, and ordinary public hosts still behave correctly. [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

Evidence: [DNS policy][code-netpolicy], [urllib connection][code-assets], audit-security-probes/summary.json.

### S-06 — Dependency monitoring does not establish the safety of the shipping lock

**Severity: high process gap; individual advisory severity varies. Status: fresh scans.**

| Ecosystem | Audit outcome | Interpretation |
| --- | --- | --- |
| Python installed locked environment | 52 advisory records across Pillow 12.3.0 (39) and filelock 3.32.7 (13); editable BadShop package skipped | These are advisory records, not 52 demonstrated application exploits. Pillow has directly relevant decode paths. Filelock findings need backend, platform and filesystem-permission reachability analysis. |
| JavaScript, all dependencies | Five package/advisory records across four distinct GHSAs in the Vitest/tinypool/mocker development chain | Scanner labels include critical prototype-pollution gadgets. This does not establish shipped-desktop RCE. |
| JavaScript, production-only | Scan passed | No advisories reported by that database for that dependency subset at audit time; not proof of no vulnerabilities. |
| Rust lock, OSV batch query | 488 registry package entries checked initially; 535 at the final upstream revision; the same five packages flagged | glib 0.18.5 has an unsound iterator advisory; four other entries are unmaintained/migrated-crate notices. Aliases were not counted as separate vulnerabilities. |

The glib dependency is present through the GTK/Tauri stack on Linux. Its advisory describes unsafe iterator behavior and possible optimized-build crashes; application reachability has not been demonstrated. The other Rust findings are proc-macro-error, zbus_names, zvariant, and zvariant_derive. The zbus-related notices reflect consolidation into zbus 6, and should not be described as proven exploitable flaws. [glib advisory](https://rustsec.org/advisories/RUSTSEC-2024-0429.html), [proc-macro-error](https://rustsec.org/advisories/RUSTSEC-2024-0370.html), [zbus_names](https://rustsec.org/advisories/RUSTSEC-2026-0371.html), [zvariant](https://rustsec.org/advisories/RUSTSEC-2026-0370.html), [zvariant_derive](https://rustsec.org/advisories/RUSTSEC-2026-0372.html)

The weekly dependency workflow upgrades a candidate Python lock and runs tests. It does not audit the shipped lock, does not cover JavaScript/Rust vulnerability status, and does not itself merge the refreshed candidate.

**Remediation:** scan the exact shipping locks and frozen inventory, triage reachability, record time-limited exceptions, and establish a patch owner and cadence. Update vulnerable development tooling without conflating it with runtime impact. Resolve GTK-stack advisories through a supported upgrade/backport strategy rather than an arbitrary incompatible dependency override.

Evidence: [dependency workflow][code-dependency-ci], pip/pnpm/OSV JSON files in the evidence directory.

### S-07 — Harden the remaining boundaries without overstating current exposure

**Priority: medium. Status: source-based hardening recommendations.**

- **CSP:** script-src includes unsafe-eval. RJSF/Ajv runtime schema compilation may explain it; investigate precompiled validators before removing it. No executable HTML-injection path was demonstrated. React Markdown is constrained and normal rendering escapes content. [Tauri CSP](https://v2.tauri.app/security/csp/)
- **Custom endpoints:** profile validation accepts HTTP as well as HTTPS for arbitrary hosts. Permit loopback/local development deliberately, but make sending credentials or images over non-loopback plaintext a clear exceptional choice.
- **WebSocket origins:** the loopback server uses strong token/actor authentication but does not restrict Origin in its serve call. An allowlist is useful defense in depth, not a substitute for tokens and not evidence that authentication is currently bypassed.
- **Asset integrity:** the existing background-removal models use size and MD5; fonts and YuNet use SHA-256, as do the newly merged on-device weights/runtime downloads. Add SHA-256 for the remaining model releases. Cached-file validation already recomputes configured hashes; do not misreport it as size-only verification.
- **Flatpak permissions:** home-directory and network access are broad. Review narrower portal-based access against the actual import/export workflows. Avoid a permission change that silently breaks chosen user files.
- **Resource limits:** decoder isolation and aggregate session/cache/disk limits deserve attention. A per-image pixel cap is not a total-session memory limit. The measured moderate workload passed; no general long-session limit was established.

### Security strengths worth preserving

The audit found meaningful protections already implemented:

- Loopback binding; a short authenticated handshake; constant-time token comparison; separate actor capabilities and scoped CLI tokens.
- User-only settings, credentials and profile operations; agent-visible artifact IDs instead of general paths; centralized tool validation and approvals.
- Tool execution in bounded subprocesses with cancellation and cleanup.
- ZIP preflight limits, path/duplicate-member checks, content hashes, older-format handling, atomic project writes and last-good-file preservation.
- OS keychain or environment references for credentials, with explicit keychain failures rather than silent plaintext fallback.
- Explicit custom-endpoint credentials preventing accidental forwarding of ambient cloud keys.
- Redirect scheme checks and removal of sensitive headers across origins.
- Escaped untrusted-web-data wrappers, constrained tool execution and prompt rules that prohibit generated pixels.
- Private structured diagnostics, redaction and bounded log-report output.
- Bounded external media tools, including restricted FFmpeg protocols and timeouts.

These foundations make targeted remediation realistic. A rewrite would discard useful verified behavior.

## 5. Release, distribution and operational readiness

### R-01 — Complete the release pipeline and make its status unambiguous

**Priority: high. Status: actual release-job failure.**

The latest published release is v0.2.0. Its release workflow [42408644104](https://github.com/dan-wiseman94/BadShop/actions/runs/42408644104) concluded **failure** because the PyPI job reported **invalid-publisher**: the OIDC identity did not match a configured trusted publisher.

The desktop build matrix and installer publication succeeded. Therefore, “the release failed” does not mean that no desktop installers exist. Conversely, the existence of downloadable installers does not make the complete release workflow green.

**Action:** configure the intended PyPI trusted publisher to match repository, workflow and environment, then verify installation from the actual package index in a fresh environment. Decide whether Python-package publication is part of the same public release contract; if not, separate its status clearly. Add an automated version-agreement check for Python, frontend, Tauri and tag metadata. [PyPI troubleshooting](https://docs.pypi.org/trusted-publishers/troubleshooting/)

### R-02 — Raise distribution trust for a consumer-facing paid release

**Priority: high for a broad paid launch; a scope increase beyond the original unsigned-v1 plan.**

Current documentation explicitly calls desktop releases unsigned and explains bypassing OS warnings. That was an intentional original scope decision, not a hidden failure to implement the original specification.

For casual paying customers, however, installer warnings create a significant trust and support burden. Plan Windows publisher signing and macOS Developer ID signing/notarization. Signing alone does not instantly establish SmartScreen reputation. [Microsoft guidance](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation), [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

Version 0.2.0 has six installers, roughly **185–369 MiB** depending on platform/package. GitHub exposes SHA-256 digests for the assets. Unlike the prior desktop release, this release does not include a standalone SHA256SUMS.txt asset. No SBOM or provenance-attestation asset is present in the inspected release/workflow.

**Action:** ship a consistent checksum manifest, package inventory/SBOM, build provenance, and exact install requirements. Verify downloaded published bytes, not only the pre-upload build. Pin third-party GitHub Actions to reviewed full commits and protect release credentials/tags/environments. Repository rulesets were empty in the inspected API response; classic branch protection could not be read because the integration returned 403, so its presence is **unknown**, not absent. [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use), [artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

### R-03 — Provide a credible update and compatibility promise

**Priority: high before sustained paid distribution. Status: implementation landed during the audit; real upgrade acceptance remains.**

The initial revision had no updater. By the final fetch, PR #28 had merged automatic/manual checks, signed downloads, explicit installation, project-save decisions and a release-feed generator. This materially closes the implementation gap. Its PR explicitly says real version-to-version signed installation on Windows/macOS/AppImage remains a release-validation requirement. Debian and Flatpak use package-manager/manual guidance; v0.2.0 needs one manual installation to gain the feature. See section 12.

Decide the supported update window, release channels, downgrade behavior, offline behavior, and what happens to projects saved by a newer release. Format 3 can read older supported formats, while older apps cannot necessarily read new projects. Preserve a backup before any irreversible migration.

The new code uses Tauri's signed updater. Verify actual release-key/feed provisioning, tampered packages, version ordering, interruption, recovery and rollback decisions. Updater signatures and OS publisher signing are separate controls. [Tauri updater](https://v2.tauri.app/plugin/updater/)

### R-04 — Close the remaining real-platform acceptance gaps

**Priority: high, scoped to the platforms advertised.**

There is substantial installer coverage already:

- The historical v0.2.0 Windows job exercised actual installation, an image workflow, dirty-close decisions, relaunch, and reopen.
- Linux CI exercised packaged variants, including AppImage extraction-based launch and Flatpak.
- Both macOS architectures built and launched; Intel macOS also exercised real U2-Net background removal.
- This audit's fresh Linux native source run verified rendering, authenticated core connection, recovery after killing the core, launcher behavior, and clean shutdown.

These layers should not be flattened into “all platforms fully tested.” Browser dialogs are fallbacks, Xvfb is not KDE Wayland, AppImage extract-and-run is not FUSE mounting, and a source debug build is not a tested signed installer.

Before broad release, retain interactive evidence for macOS/Linux file dialogs and clipboard; KDE/Wayland drag/drop; standard-user Windows operation; clean installs with no developer toolchain; update/reinstall/uninstall; Unicode/long/OneDrive paths; restricted networks; locked keychains; and display scaling. Test the chosen minimum supported OS versions, not only the current CI runner.

### R-05 — Finish the support and trust layer

**Priority: high for a paid pilot.**

The repository has installation and development documentation, diagnostics, release notes, and explanatory model-license material. I did not find a dedicated SECURITY.md, SUPPORT.md, privacy notice, or user-oriented support policy in the audited tree.

Provide:

- A short illustrated first-run guide and a “what works without AI” explanation.
- A supported-provider/version matrix, known limitations and self-check that distinguishes setup validation from a real connection test.
- An in-app help/support entry, with a user-reviewed diagnostic export.
- A vulnerability-reporting address/process and supported-version/security-update policy.
- A plain-language data-flow notice: local projects and caches, images/prompts sent to the chosen AI provider, search queries/download hosts, and any future telemetry.
- Clear purchase terms, download recovery, update entitlement, refunds, and support response expectations if money is charged.
- A way to inspect and remove retained caches, downloaded models, history and recovery data without accidentally deleting user projects.

Do not upload prompts, images or diagnostics automatically merely to obtain product metrics. The existing diagnostic redaction is a useful base; any added analytics should be optional and purpose-limited.

### R-06 — Complete the redistribution and content-rights inventory

**Priority: high for distribution hygiene; legal review depends on the business model.**

The project includes a third-party notice file, Python distribution metadata and a generated Python inventory. The notice says JavaScript and Rust licenses are recorded in lockfiles/upstream packages, but lockfiles are not complete collections of required license texts. The freezer also catches metadata-copy exceptions broadly.

**Action:** generate and verify a complete shipped-component license bundle for Python, JavaScript, Rust and native libraries; make missing required notices visible in the build. Verify what is actually inside each installer. This audit did not establish that every binary license obligation is met or breached.

Keep model-weight licensing separate from the wrapper library's license. The existing model-license document correctly makes that distinction. Preserve image provenance and the existing credits export. A source's rights metadata is not an ownership guarantee; CC attribution/share-alike conditions and third-party personality/privacy rights can still matter. Provide concise information at the point of reuse, without turning every playful edit into a legal wizard. [Creative Commons FAQ](https://creativecommons.org/faq/), [CC BY terms](https://creativecommons.org/licenses/by/4.0/)

If adding hosted accounts, public sharing, commercial asset packs, or a marketplace, obtain focused review of the actual jurisdiction, provider terms, consumer terms, moderation/reporting process and content licenses. Those are future scope decisions, not reasons to build an enterprise compliance program for a local beta.

## 6. Architecture, performance and maintainability

The architecture has sensible boundaries: a deterministic engine, tool registry, session/persistence layer, provider adapters, server and native supervisor. Recent maintenance checks enforce import/execution boundaries and detect high-confidence dead code. Exact-main CI actually ran core tests, frontend tests, browser workflows, Rust tests/formatting, and maintenance checks; these were not merely green wrapper jobs with every relevant layer skipped.

Keep the centralized execution and validation paths. The size of a file or the number of tests is not itself an architectural defect. There is no evidence here that the app needs a framework rewrite or a second rendering engine.

A fresh synthetic workload imported ten distinct 2048 × 1536 noise PNGs and made 20 seeded deepfry steps, then saved and reopened:

| Measurement | Result |
| --- | --- |
| Final project size | 117,907,433 bytes, approximately 112.4 MiB |
| Import duration including autosave | Median 0.255 s; maximum 0.329 s |
| Edit duration including autosave | Median 0.289 s; maximum 0.378 s |
| Explicit save | 0.069 s |
| Reopen | 0.806 s |
| Peak core-process RSS | 339.4 MiB |
| Reopened state | 20 steps, 40 artifacts |

This used Linux WSL/ext4, an in-process executor and generated noise inputs. It does not measure packaged startup, inference, background-removal models, integrated UI latency, slow disks, or low-end hardware. It is evidence that a moderate persistence workload works well, not a universal performance guarantee.

The main scale risks are visible in the design: original and working image bytes are kept in memory; changing session operations can rewrite the autosave; snapshots and browser image data grow with history; models can dominate startup and RAM. Profile realistic long sessions before optimizing. Prioritize aggregate disk/memory visibility, safe limits, and cancellation over speculative complexity.

The default 1000-pixel working size is defensible for the primary meme audience when clearly explained. High-resolution/print/CMYK workflows should not delay the first hobbyist release. Source-format compatibility, legible captions and convenient sharing matter more to that audience.

## 7. Provider reliability and the AI promise

Provider support is a maintenance commitment, not just a settings dropdown. BadShop has useful separation between API and CLI adapters, schema normalization, image handling, approvals, cancellation, and resume behavior. Its CLI wrappers deliberately restrict built-in tools and isolate configuration so pixels still go through BadShop.

The evidence supports a narrower public promise than “all supported providers work equally well”:

| Configuration | Evidence available | What it does not establish |
| --- | --- | --- |
| Claude Code | Historical complete native composition with five approvals, export and same-hash replay | Current-version performance across a diverse set of jokes and operating systems |
| Codex CLI | Historical image/tool and conversation-resume smoke checks | A current full creative benchmark or consistent multi-step quality |
| Gemini CLI/API | Configuration and adapter checks; historical end-to-end attempts hit service/quota failures | A dependable successful full editing journey |
| External local vision models | Historical one-tool success through several local transports | Fast full art direction on ordinary CPUs; a historical 2B-model run timed out at 120 seconds on the tested setup |
| New managed on-device assistant | Source implements guided downloads, a pinned 0.8B vision model and limited basic edits; PR #27 reports real Linux/Windows workflows | This audit did not independently rerun model inference or certify its hardware/platform range; see section 12 |
| API/custom endpoint | Strong focused tests and a real-adapter controlled-server probe in this audit | Current production-model quality, availability, billing or latency |

A timeout on one local machine does not mean local AI never works. Equally, accepting an OpenAI-compatible request does not establish usable vision, tool calling, context handling, or creative direction.

CLI interfaces evolve independently. The Codex adapter uses internal model-metadata rewriting in addition to public command behavior; this deserves a versioned compatibility fixture and a failure message when an assumed contract changes. Claude's built-in-tool restriction and permissions flags are distinct controls and should remain tested together. The current public references are [Codex CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli), [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [Claude CLI](https://code.claude.com/docs/en/cli-reference), and [Gemini headless mode](https://geminicli.com/docs/cli/headless/). Documentation is not a substitute for running the exact adapter.

**Recommended release contract:**

- Name one preferred cloud configuration and one optional local configuration only after complete workflow verification.
- Publish tested CLI/model versions and dates. Label other combinations experimental.
- Make the readiness check exercise image understanding and a harmless BadShop tool, with explicit user control over any billed check.
- Show useful stages: connecting, thinking, waiting for approval, downloading, editing and exporting. Cancellation must stop the owned operation and leave a usable project.
- Show provider limits and any known usage/cost information. Do not present step limits as spend protection.
- Keep manual creation enjoyable when the provider is unavailable. Never silently substitute a different cloud provider.
- Record a bounded, redacted diagnostic bundle that helps support distinguish app failures from authentication, rate limits, provider outages and unsupported capabilities.

Do not add another five adapters before making the recommended one consistently successful. Distinguish the optional no-account basic assistant from advanced direction that needs another provider; state downloads, hardware needs and any separate payment clearly.

## 8. Feature priorities: what to change and what to defer

The proposed improvements below mostly expose capabilities already built. They should not create parallel execution, persistence or asset systems.

| Priority | User outcome | Smallest useful change | Release acceptance |
| --- | --- | --- | --- |
| First | A joke appears before configuration becomes work | Outcome-led start screen, licensed examples, a manual-first canvas | New users make and export something they choose without help |
| First | The result reaches the group chat | Copy image and one understandable export flow | Correct bytes/format; tested paste into target applications |
| First | The joke survives revision | Clear caption/subject selection, “same image, change this,” keep/compare variants | Requested text and intended subject survive a narrow change |
| First | The app feels dependable | Fix S-01–S-05, honest readiness/status, readable controls | Security regressions pass; cancellation and recovery preserve work |
| Next | Repeating a personal joke becomes easy | Surface existing junk drawer, recipes and favorites near the canvas | Reuse a subject/recipe without navigating a large utility dialog |
| Next | Different takes really differ | Better presentation and evaluation of existing three-take/novelty controls | Alternatives differ in premise or composition, not merely captions |
| Next | History feels familiar | Thin Undo/Redo and named-version affordances using existing history | Consistent behavior across manual and AI steps and project reopening |
| Later, if observed | Better image finding | Source health, relevance tuning, curated reusable assets | Better results on recorded user queries; failure remains recoverable |
| Later, if observed | Phone-friendly sharing | Export/share handoff improvements | Removes an observed desktop-to-phone obstacle |
| Defer | General design-suite parity | Layers/tool breadth/print production/mobile rewrite | Build only if the chosen paying audience repeatedly needs it |
| Defer | Organization workflows | Accounts, teams, admin, collaboration, brand governance | Requires actual team buyers and a separate scope/economics decision |
| Defer | Hosted AI and public community | Billing, credits, public galleries and moderation | Demand and operational capacity justify a service business |

A few carefully curated packs can help first use. A large pack marketplace, social feed, or template catalog should wait. They create content-quality, licensing and operational obligations before solving the basic value loop.

Discoverability and marketing are part of readiness too. Publish a short demonstration of three actual end-to-end jokes, the minimum supported machines, the separate AI requirement if applicable, and the exact output/reuse promise. Show honest timings. Avoid a landing page built around tool counts or unsupported “private/offline” claims. The repository already has install and first-edit documentation; the missing evidence is that intended customers can follow it comfortably.

## 9. Validate usefulness and willingness to pay

### Observe real creation before surveying preferences

Run two small formative rounds with about five primary-audience participants each. Recruit people who regularly share memes or make crude edits, including several who do not use developer tools. Add a few independent creators and a few team users separately so their needs do not silently redefine the primary audience.

This is usability research, not a statistically representative demand study. Iterative small studies can reveal major interaction problems; what people actually do is more useful than asking whether a feature sounds appealing. [Nielsen Norman Group on small studies](https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/), [observed behavior](https://www.nngroup.com/articles/first-rule-of-usability-dont-listen-to-users/)

Use participants' own harmless, consented images and jokes, with permission for any cloud processing. Start from a clean install. Observe:

1. Can they tell what BadShop is for and what costs extra?
2. Can they start without assistance?
3. How long until the first result they would actually send?
4. Can they preserve the funny part while changing one thing?
5. Do they keep, export or copy the result?
6. Do they voluntarily make another?
7. Do they return after seven and fourteen days?
8. What do they choose instead when BadShop frustrates them?

Do not count an export as a real social share. Ask permission to observe whether they use the image; never post on their behalf. Keep content and telemetry private by default. A short optional local session record or consented study can measure this without introducing blanket analytics.

### Measure creative outcomes systematically

Extend the existing six-brief harness to roughly 30–50 representative briefs: personal subject swaps, short captions, long captions, a specific image attachment, deliberate restraint, extreme degradation, narrow revisions, three distinct premises, source-search ambiguity, and recovery after interruption.

For each run, retain provider/model/version, input permission, seed where applicable, budget, elapsed time, tool steps, approvals, errors, final images, revisions and actual spend. Use the existing side-by-side gallery for blinded human preference. Separate technical completion from quality:

- **Technical:** correct inputs, valid tools, completed output, readable file, correct persisted history, honest completion claim.
- **Creative:** understandable joke, recognizable subject, readable punchline, meaningful alternatives, and deliberate rather than accidental ugliness.
- **Practical:** little supervision, acceptable wait/cost, easy revision and sharing.

Report the failures, not just a curated gallery. Track median and slow-tail latency. Benchmark a simple free alternative on comparable tasks; BadShop need not win every caption-only case, but should clearly win its chosen compositing use cases.

### Suggested gates, explicitly proposals

These are starting product targets to agree on and test, **not measured current results or industry standards**:

| Gate | Proposed threshold or required evidence |
| --- | --- |
| Manual first success | At least 8 of 10 target users complete a chosen first result and export unassisted within three minutes after installation; separately measure download/install time |
| AI creative success | At least 80% of representative target briefs produce a result the intended user keeps within two revisions, using the advertised configuration |
| AI technical completion | At least 95% complete or fail recoverably without lost work; disclose the sample size and uncertainty |
| Wait tolerance | Start with a goal of a useful first AI result within 90 seconds median; validate the actual acceptable wait with users and publish slow-tail behavior |
| Revision control | A narrow caption change preserves the chosen subject/composition on the evaluation set |
| Sharing | Copy/export succeeds in the actual target apps and preserves intended dimensions, transparency or animation |
| Trust | No open reproduced privacy/trust-boundary blocker; no untriaged high-impact reachable decoder advisory |
| Data protection | Reopen/recovery/migration and interruption cases pass with exact output/history checks and no observed loss; never present finite tests as a guarantee |
| Accessibility | Resolve reproduced violations and pass manual keyboard/scaling/native assistive-technology checks for the promised scope |
| Distribution | Published signed/notarized packages, clean-install/update checks, clear support route, and truthful release status |

A 95% target evaluated on 30–50 briefs is a directional signal, not a precise reliability estimate. Increase sampling as use grows. A single good screenshot is much weaker evidence.

### Test payment with an honest paid pilot

After the trust and first-use fixes, offer a limited paid pilot with clear product status, a real price, the AI requirements, an update/support promise, and a straightforward refund policy. Begin with perhaps 20–30 qualified users; that is a learning cohort, not a validated market size.

Compare the proposed one-time prices across comparable recruitment channels rather than letting a few enthusiastic friends define the market. Record actual purchases, refunds, support time, repeat creation and voluntary recommendations. Do not infer willingness to pay from compliments or free download counts.

Set the go/no-go economics before the pilot: the revenue needed to cover distribution, support and any included service use; a maximum acceptable support burden; and the retention/repeat-use pattern appropriate to occasional creative play. There is no honest universal conversion threshold to invent without an acquisition channel and traffic quality.

## 10. Practical route to release

The sequence below is more useful than a percentage-complete score. A product can have 95% of its code and still miss the one experience customers buy.

| Phase | Work | Exit condition |
| --- | --- | --- |
| A — Repair trust | Decoder/dependency remediation, local-only transition, transcript validation/trust, network connection policy; add focused regression evidence | Reproduced defects closed and reviewed; shipping dependencies triaged |
| B — Prove the fun loop | Curated start, readable result/revision controls, image copy/export, provider readiness and actionable failures | Target users succeed without coaching; existing capabilities become easy to reach |
| C — Prove the promise | Real-model creative benchmark, clean-machine platform runs, signing/publishing/update/support decisions | Advertised workflow and supported configurations have current evidence |
| D — Test payment | Small paid pilot and measured support/return behavior | Real buyers retain value and unit economics support the offer |
| E — Broaden carefully | Address observed demand for packs, creators, local AI or teams | Each expansion has evidence and an owner |

**Planning estimate:** allow roughly **4–8 focused calendar weeks** for a small team with platform/signing access to close the technical and first-use gaps and run an initial paid pilot. This is a planning hypothesis, not a delivery commitment. Security/dependency work may take one to two engineering weeks; product simplification one to three; user recruitment, observation and repeat-use measurement need two to four elapsed weeks and can overlap. External signing setup, incompatible upstream upgrades, provider problems and part-time staffing can extend it substantially.

That estimate excludes building a hosted inference business, mobile apps, team collaboration or a marketplace. It also excludes promising that research will confirm demand. With one part-time maintainer, plan by completed gates rather than treating the range as a deadline.

Assign named ownership for the release checklist, security inbox, dependencies, provider compatibility and customer support. Keep a lightweight incident process: reproduce, contain, communicate, patch, verify, and document affected versions. A solo maintainer can own several roles; the promise still needs to be explicit.

The immediate recommendation is **a smaller, better-exposed product with stronger trust**, not a smaller engine or a new architecture. Preserve the unusual deterministic editing identity. Spend the next work on security, first-use payoff, convenient sharing and evidence that users enjoy returning.

## 11. Evidence and limits

### Fresh checks against the audited revision

All application verification used isolated data and the dedicated Arch WSL toolchain. The initial Linux runs were clean at 0ee2084; the focused final recheck used clean 23b7fce. The Windows audit worktree contains this report and ignored evidence; application source was not modified by this audit.

| Check | Actual result | Evidence |
| --- | --- | --- |
| Focused Python boundaries, profiles and server WebSocket tests | 45 passed, 1 deselected | [Core summary](../artifacts/verification/linux/audit-focused-core/summary.json) |
| Real-core browser project journey | 2 passed: edit/replay/save/reopen/export; damaged-project preservation | [Browser summary](../artifacts/verification/linux/audit-project-journey/summary.json) |
| Native Linux source build and private-Xvfb lifecycle | Build, native window and launcher checks passed; authenticated core, forced-core-exit recovery and cleanup exercised | [Native summary](../artifacts/verification/linux/audit-native/summary.json) |
| Local-only active-turn probe | Reproduced an image-bearing request after activation | [Probe result](../artifacts/verification/linux/audit-local-only/summary.json) |
| Imported history and DNS probes | System-role forwarding, malformed-history error and owned-loopback rebinding reproduced | [Probe results](../artifacts/verification/linux/audit-security-probes/summary.json) |
| Moderate persistence workload | 10 large imports, 20 edits, save/reopen completed; detailed measurements above | [Benchmark](../artifacts/verification/linux/audit-persistence/summary.json) |
| Manual browser workflow | Real imported image, GeoCities composition and PNG export completed | [Output](../artifacts/verification/geocities.png), [editor](../artifacts/verification/retro-result.png) |
| First use and compact/scaled UI | Inspected at 1280 × 720 and 900 × 600; populated-state axe findings and Settings focus behavior recorded | [First use](../artifacts/verification/manual-first-run.png), [150% scale](../artifacts/verification/scaled-150-900x600.png) |
| Live image discovery | One public-source query completed in 4.9 s; live acquisition completion not verified | [Discovery](../artifacts/verification/discovery-result.png) |
| Offline creative evaluation | Existing six-brief scripted demo generated successfully; no model called | [Scripted gallery](../artifacts/verification/linux/audit-creative-demo/comparison.html) |
| Dependency scans | Python and development JS findings; production JS clean by database; Rust OSV advisories/notices | [Python](../artifacts/verification/linux/pip-audit.json), [JS](../artifacts/verification/linux/pnpm-audit.json), [production JS](../artifacts/verification/linux/pnpm-audit-prod.json), [Rust](../artifacts/verification/linux/rust-osv.json) |

The focused core command selected test_project_boundaries.py, test_provider_profiles.py and test_server_ws.py. The browser command selected e2e/project-journey.spec.ts. Native verification was broadened deliberately because this is a release-readiness audit and source-level native lifecycle coverage was a material gap. No unrelated full local unit suite was run.

The historical/remote evidence was also checked directly:

- [Exact-main core workflow](https://github.com/dan-wiseman94/BadShop/actions/runs/42415779150): real core tests, script tests and lint.
- [Exact-main desktop workflow](https://github.com/dan-wiseman94/BadShop/actions/runs/42415779083): frontend and browser checks, Rust tests/formatting.
- [Exact-main maintenance workflow](https://github.com/dan-wiseman94/BadShop/actions/runs/42415778874): import/maintenance checks and negative controls.
- [v0.2.0 release workflow](https://github.com/dan-wiseman94/BadShop/actions/runs/42408644104): installer success and separate PyPI failure.
- [Published release](https://github.com/dan-wiseman94/BadShop/releases/tag/v0.2.0): actual asset inventory and metadata.
- [Prior provider/platform evidence][doc-history]: useful context, dated October 31; not counted as fresh live-provider testing.

### What this audit does not establish

It does not establish customer demand, real willingness to pay, a measured retention rate, current multi-provider creative success, absence of all vulnerabilities, or full accessibility compliance. It does not freshly certify every Windows/macOS installer, Wayland desktop, GPU driver, screen reader, long session, background-removal model, or network environment.

The native test was a Linux source/debug build on a private Xvfb display. It was not a newly built installer or a real KDE Wayland run. Browser file chooser behavior is not evidence for native dialogs. Previously published installer jobs are valuable historical evidence at the release tag, which differs from the audited main commit.

Public dependency databases can have aliases, inaccuracies and applicability limits. The report separates advisory counts from proven application defects. No destructive payloads or real-secret attacks were run. Model outcomes and pricing recommendations remain hypotheses until measured.

Screenshots, traces, logs, probe scripts and machine-readable summaries are retained under artifacts/verification in the isolated audit worktree. Those artifacts are intentionally ignored by Git; copy them with the report when archiving or sharing this audit. Temporary servers, browser session, test subprocesses and owned temporary project data were cleaned up.


## 12. Changes merged during the audit and final recheck

The required final fetch found that origin/main advanced from **0ee2084** to **23b7fce**. The intervening changes touched 54 files: mainly shared frontend controls, guided on-device AI, and in-app updates. There is no path overlap with this audit's sole documentation addition. The initial application snapshot was retained for the UI/native evidence; the isolated Linux worktree was advanced for the focused follow-up.

### Newly landed capability

**Guided on-device AI — [PR #27](https://github.com/dan-wiseman94/BadShop/pull/27).** First launch and Settings now offer a model/runtime download, with SHA-256-pinned assets and owned inference-process lifecycle. The new provider supports basic text, deepfry, filter and censor edits, plus a targeted laser-eye flow using detected landmarks. This is an appreciable reduction in account/key setup friction.

The PR reports a real Linux browser workflow with Local only enabled, targeted laser eyes and a follow-up deep fry, plus Windows installer testing on an RTX 4080 SUPER before the final runtime-ownership split. These are reported implementation results, not independent inference runs in this audit. The newly added activation/persistence test passed in this audit, but mocks runtime readiness. Keep those evidence levels distinct.

Publish the supported hardware and capability boundaries, measure first download/start/use latency, and test recovery from interrupted downloads and runtime startup failure. The pinned model/projector total about 748 MiB. Runtime choice adds roughly 12–36 MiB on several CPU/Mac/Windows paths or approximately 746 MiB for the Linux CUDA runtime plus libraries. Available RAM/VRAM and supported OS/runtime binaries matter independently of download size. Linux runtime selection requires glibc 2.38 or newer in the current code.

The one-basic-edit scope is useful. It is not evidence that the full original art-director feature set now runs locally with equivalent quality. Retain this focused positioning until measured.

**Signed in-app updates — [PR #28](https://github.com/dan-wiseman94/BadShop/pull/28).** Main now has automatic/manual checks, explicit download/install, progress, save/discard/cancel before installation, a signed four-target feed, and a version bump to 0.3.0. The PR reports signing credentials configured; this audit did not inspect secrets. Its own acceptance notes correctly leave real signed version-to-version installation as release work. Existing 0.2.0 installs need one manual upgrade.

There are two additional source-based concerns to include in that release work:

- **Network-policy consistency:** useUpdates enables checks by default, after five seconds and every six hours. Neither that hook nor the native updater commands consult the core's no_remote setting. Thus an updater-enabled release can check GitHub, and the explicit update-download path can fetch packages, independently of the setting that says it controls BadShop network calls and blocks downloads. This was established by source review, not a release-build network capture. Define whether security update checks are an explicit exception, show that clearly, and enforce the selected policy across native and core networking. This does not imply that update checks upload photos. [Hook](https://github.com/dan-wiseman94/BadShop/blob/23b7fce794b52ca7db430ae1d75d90755b6a4645/app/src/updates.tsx#L8), [native commands](https://github.com/dan-wiseman94/BadShop/blob/23b7fce794b52ca7db430ae1d75d90755b6a4645/app/src-tauri/src/updates.rs#L26)
- **Download cancellation:** the progress modal has no cancellation control and the native download timeout is 15 minutes. On a stalled connection, the user may have a long blocking wait. Define a safe cancel path and test retry, saved work and process cleanup. This is a source-based UX concern, not a reproduced installer hang.

Updater signatures do not resolve the separate unsigned Windows/macOS publisher trust issue.

### Findings retained after recheck

A fresh focused run at 23b7fce passed **46 tests with one deselected**, including the added on-device activation/persistence case. The same controlled probes reproduced:

- An API request containing an image after Local only was enabled.
- An imported system-role message entering the provider request as system.
- A loaded malformed tool-call history causing KeyError on context construction.
- A guarded download reaching the owned loopback marker through changed DNS answers.

The relevant project models, project loader and network-policy modules did not change. The provider/context additions did not close those defects. The Python lock diff did not update Pillow or filelock. A fresh OSV scan of the expanded **535-entry Rust registry lock** found the same five flagged packages.

Evidence: [follow-up tests](../artifacts/verification/linux/audit-upstream-core/summary.json), [privacy reproduction](../artifacts/verification/linux/audit-local-only-23b7fce/summary.json), [history/network reproductions](../artifacts/verification/linux/audit-security-probes-23b7fce/summary.json), [updated Rust scan](../artifacts/verification/linux/rust-osv-23b7fce.json).

The new frontend refactor leaves the cited small-text/contrast CSS values and root-scaling approach unchanged. I did not rerun the complete UI accessibility suite or rebuild native installers after these merges; the original measurements remain labeled with their tested revision.

At the final release-status check, 0.2.0 remained the latest published release. The [0.3.0 release run](https://github.com/dan-wiseman94/BadShop/actions/runs/42420316864) was still in progress: Windows, Linux, Apple Silicon, core and frontend jobs had passed; Intel macOS was still running and publication was not complete. The newer [core](https://github.com/dan-wiseman94/BadShop/actions/runs/42420297931), [desktop](https://github.com/dan-wiseman94/BadShop/actions/runs/42420297927) and [maintenance](https://github.com/dan-wiseman94/BadShop/actions/runs/42420297898) workflow summaries were successful. An in-progress release is not counted as a published or fully validated update.

These changes improve the product's trajectory. They do not overturn the launch recommendation: fix the reproduced trust defects, finish real distribution acceptance, and prove the short, enjoyable creation-to-sharing loop before making a broad paid-quality promise.

### Source locations for reproduced findings

These links pin the reviewed source rather than following future changes on main.

[code-welcome]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/app/src/components/Settings.tsx#L863
[code-chat]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/app/src/components/Chat.tsx
[doc-evaluation]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/docs/creative-evaluation.md
[doc-history]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/docs/verification-2026-10-31.md
[code-common]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/engine/common.py#L35
[code-app-scale]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/app/src/App.tsx#L105
[code-style]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/app/src/style.css#L968
[code-lock]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/uv.lock#L1451
[code-artifacts]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/session/artifacts.py#L55
[code-import]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/server/app.py#L1045
[code-provider-check]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/server/app.py#L433
[code-settings-apply]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/server/app.py#L1186
[code-loop]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/agent/loop.py#L231
[code-local-only]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/app/src/components/SourceSettings.tsx#L49
[code-models]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/session/models.py#L90
[code-context]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/agent/context.py#L231
[code-project]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/session/project.py#L247
[code-answered]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/agent/context.py#L97
[code-netpolicy]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/session/netpolicy.py#L59
[code-assets]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/core/src/badshop/engine/assets.py#L76
[code-dependency-ci]: https://github.com/dan-wiseman94/BadShop/blob/0ee20840e2c47c9e478b57dc76ccfe508310bbbe/.github/workflows/dependency-check.yml
