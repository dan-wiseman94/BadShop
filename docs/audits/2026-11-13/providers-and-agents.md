# Provider and agent architecture audit

This audit covers BadShop's API providers, subscription agents, on-device assistant, MCP bridge, context construction, approvals, cancellation, and provider-related trust boundaries at commit `fb1ad675546bd466d5578fbf324a72361458a619`. Findings describe source behavior at that revision. Runtime scenarios that were not reproduced are identified explicitly.

BadShop should retain its deterministic engine, central tool registry, and session-owned execution. The provider subsystem needs a substantial boundary refactor. Replacing it wholesale with a general agent framework would introduce capabilities and maintenance costs the product does not need. The target is a small application-owned run controller with typed provider contracts, bounded context, explicit authority, and interchangeable transports.

## Current behavior and ownership

API providers return text and requested tool calls to the in-app loop. That loop records the conversation, proposes steps, obtains approval, executes through `Session`, and returns outcomes to the provider. Subscription agents own their reasoning loop. BadShop starts a restricted CLI process, renders its stream, and exposes editing tools through an MCP proxy forwarding to the same session execution path. The optional on-device assistant uses the API loop but adds constrained editing policies inside its provider adapter.

The core owns session state, the agent turn, approval gates, tool workers, provider profiles, external processes, and policy changes. There are two partially duplicated turn lifecycles: the API loop and CLI loop, with CLI invocation policy spread into `CoreApp`.

The provider conversation is persisted in OpenAI Chat Completions dictionary shapes. User-facing messages and editing steps are also persisted. External CLI conversation IDs remain adapter runtime state, while each turn receives a BadShop snapshot. This keeps project reconstruction independent of a surviving CLI process, but exact agent continuation and project reconstruction are different contracts.

Sources: [API protocol](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/provider.py#L1), [API loop](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L225), [CLI turn](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_turn.py#L13), [MCP bridge](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/mcp/proxy.py#L25), [persisted model](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/models.py#L107).

## Properties to preserve

The code already contains substantial lifecycle and security work. Modernization must preserve these behaviors explicitly.

| Existing property | Value and evidence |
| --- | --- |
| Session-owned execution | API providers return requests; CLI stream events do not execute tools. This prevents a second pixel execution path. [API invocation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L278), [CLI parser](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L176) |
| Deterministic approval policy | Registry metadata determines approval. Invalid edited parameters leave the proposal pending. [Policy and gate](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/approval.py#L22) |
| Careful cancellation | Mutation is shielded; wind-up settles unanswered calls; repeated cancellation waits for cleanup. [Wind-up](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L146), [shielded calls](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L201) |
| Complete-response validation | Truncated/refused API responses cannot execute tool fragments. [Stream validation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/litellm_provider.py#L227) |
| Private CLI configuration | BadShop restricts its own agent instance without overwriting ordinary user configuration. Windows npm wrappers avoid shell interpolation. [Configuration](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L271), [launcher resolution](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L94) |
| Descendant cleanup | Process groups/Windows jobs, inherited pipes, and repeated Stop are handled. [Supervision](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L364), [cleanup](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L479) |
| Actor-scoped credentials | A CLI cannot use its token as renderer/user authority. [Derivation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/auth.py#L6), [handshake](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/ws.py#L54) |
| Coordinated Local only transition | Active probes, turns, downloads, CLI processes, and update leases are stopped before acknowledgement. [Transition](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L1410) |
| Untrusted data stays below application instructions | Source results are escaped/wrapped; imported project state is projected at user authority. [Result wrapping](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/context.py#L116), [state projection](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/context.py#L235) |
| Sanitized diagnostics | Provider exception bodies are suppressed; sensitive structured fields and known secrets are redacted. [Provider errors](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/litellm_provider.py#L47), [redaction](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/diagnostics.py#L29) |

## Findings

### PA01 Persisted conversation is coupled to one provider protocol

**High architectural leverage. Confirmed source property.** `Provider.complete()` accepts dictionary messages/tools explicitly defined as OpenAI chat format. Session and branch transcripts persist that representation. `_openai_call()` constructs provider-shaped data in the application loop. Perplexity translates it into Responses-style inputs, and a provider-specific `thought_signature` has entered the common tool request. The loop discovers capability flags with `getattr`.

A new protocol with different continuation, reasoning metadata, or message kinds consequently affects persistence, project import validation, context reconstruction, and adapters. Switching providers raises the question of which opaque continuation data may cross boundaries. Existing exceptions show this pressure is already present.

Persist typed domain records such as `UserMessage`, `AssistantMessage`, `ToolInvocation`, `ToolOutcome`, `RunStarted`, and `RunFinished`. Keep opaque continuation data bounded and namespaced by adapter/model/format version; never replay it into another adapter. Provider request conversion belongs at the adapter boundary. A compatibility reader should convert old transcripts while preserving original project files. Compare old/new projections on saved-project fixtures before changing the writer. An unsupported continuation field should limit continuation, not prevent editing an otherwise valid project.

Evidence: [provider contract](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/provider.py#L12), [transcript fields](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/models.py#L94), [OpenAI call construction](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L53), [adapter flags](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L237), [Perplexity conversion](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/perplexity_provider.py#L16).

### PA02 Context is bounded by image count but not text or tokens

**High priority. Confirmed source property; overflow threshold depends on provider/project.** Images have an eight-image, 1,024-pixel limit. Text has no equivalent budget: context construction copies the full repaired transcript, adds project state, and supplies every registry tool. CLI snapshots limit item counts, not encoded size. The managed local runtime has a 16,384-token context. API overflow is handled after rejection by suggesting a new session or larger model.

A long editing session can become unusable with its provider although the project remains valid. Large discovery results/tool schemas can exhaust context earlier. Repeated encoding and copying are also plausible performance costs, not measurements established here.

Introduce a deterministic context assembler with budgets for instructions, latest request, essential state, tool definitions, recent complete call/result groups, older conversation, and images. Preserve unresolved calls and pairing. Prefer deterministic state summaries. Optional model-written compaction may summarize intent but must not replace authoritative steps, artifact identities, approvals, or provenance. Select relevant tool families without treating selection as authorization. Keep inspection/continuation available. Report omitted context and usage, and bound any image-projection cache by artifact hash plus transformation parameters.

Evidence: [image limits/all tools](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/context.py#L79), [full transcript](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/context.py#L235), [CLI item limits](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_turn.py#L40), [overflow error](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/litellm_provider.py#L59), [local context size](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/local_runtime.py#L82).

### PA03 Duplicated turn lifecycles already differ

**High architectural leverage. Confirmed duplication and budget inconsistency.** API turn policy lives in `agent/loop.py`; CLI policy is split between `cli_turn.py` and private `CoreApp` state. `_run_or_reject()` documents its equivalence to API `_execute()`. Finish-tool names are hard-coded twice. Routing uses `isinstance(provider, CLIProvider)`.

The API budget counts executed tools and excludes rejected/invalid calls. CLI decrements before proposal validation and approval. Identical rejection/correction workflows therefore consume different budgets. This could be intentional, but the distinction is not expressed as a product contract.

Share run identity, lifecycle, checkpoint, cancellation, budget ledger, and terminal outcome under a run controller. Share proposal/approval/execution/settlement under a tool invocation service using the existing `Session`. Retain two honest adapter interfaces: a completion adapter returns one model completion; an external-agent adapter manages a process/session and emits normalized events. Move finish-phase classification into registry metadata and one policy. Define separate limits for attempted invocations, executed steps, provider requests, response bytes, and elapsed time.

Evidence: [API lifecycle](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L188), [private-state coupling](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_turn.py#L61), [CLI invocation policy](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L1047), [duplicated settlement](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L1123), [API budget assertion](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/tests/test_agent.py#L348).

### PA04 Replaced CLI profiles can retain processes until shutdown

**Medium priority. Confirmed source path; not reproduced with a real provider.** Replacing a cached CLI provider after profile changes adds the old instance to `_retired_clis` without closing it. That list is drained at app shutdown. Claude retains its process after a completed turn. Editing its profile and starting again can leave the old process/private directory alive until shutdown; repeated edits can accumulate them. Branch changes already close retired instances immediately.

Revoke authority and close an adapter as soon as ownership ends. Retain a retirement entry only while cleanup is in progress, then remove it. Add a fake-process regression checking actual process and directory cleanup, not merely a mocked `close()` call.

Evidence: [replacement](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L488), [shutdown drain](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L630), [persistent Claude process](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L454), [branch cleanup](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L890).

### PA05 CLI turns lack a turn deadline and total-output limit

**Medium priority. Confirmed source property.** CLI discovery and cleanup are bounded, but `turn()` reads stdout and waits for completion without an application turn deadline. `MAX_LINE` bounds one line, not accumulated output. An inert agent can keep the turn busy indefinitely until Stop; a noisy one can accumulate output. LiteLLM bounds its complete request with `asyncio.timeout`.

Use separate startup, idle, provider-request, and absolute deadlines. Approval waiting is a distinct state and should suspend the relevant idle timer. Add total event/byte limits. Timeout must settle the same state as Stop and distinguish provider waiting from human waiting.

Evidence: [CLI turn](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L402), [line bound](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L25), [API deadline](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/litellm_provider.py#L227).

### PA06 CLI support detection is weaker than its displayed meaning

**High compatibility concern. Confirmed detection mechanism; future-version failures are scenarios.** Help-flag inspection produces `supported=True`, and CLI capabilities report vision/tools unconditionally. Configuration depends on additional behavior, notably Codex model-catalog fields and feature/config keys. A release can retain help flags while changing these contracts. Synthetic transcripts prove parser behavior for modeled shapes, not installed authenticated-agent compatibility.

Distinguish discovery, launch-interface compatibility, successful configuration, and verified-version status. Maintain a compatibility manifest with tested versions, required features, exclusions, and evidence. Report unknown versions as unverified. Keep discovery offline/free. During warranted compatibility/release work, retain small real probes: image read, authorized edit, denied built-in tool, rejection/edit/approval, resume, cancellation, and descendant cleanup. Keep sanitized recorded transcripts alongside synthetic adversarial fixtures.

ACP merits a focused experiment, conditional on subscription auth, image delivery, BadShop-only tools, approval semantics, and cleanup. Transport standardization does not establish confinement. An integration unable to establish tool restriction should fail closed rather than rely on instructions to the model.

Evidence: [inspection](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L142), [capabilities](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L261), [catalog/config adaptation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L295), [fixture provenance](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/tests/fixtures/cli/README.md#L1), [live probes](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/tests/test_cli_live.py#L1).

### PA07 Actor authority is not bound to a project or run

**Medium trust-boundary improvement. Confirmed scope; no exploit executed.** Actor credentials correctly prevent a CLI from authenticating as the renderer, but are derived from core token plus actor name. The handler chooses the current session when a request arrives. A credential remains valid for that actor during the core lifetime, and budget association depends on matching the active actor.

A stale, retained, or compromised external instance could retain authority after its intended profile/project transition. This is a lifetime mismatch, not the previously fixed renderer-token flaw. Mint revocable grants bound to project ID, session incarnation, adapter instance, operations, and budget owner. Validate before selecting the session. Revoke on relevant Stop, profile replacement, branch/project change, and shutdown. Give standalone MCP use an explicit separate contract if it remains supported.

Evidence: [token derivation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/auth.py#L6), [accepted actors](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/ws.py#L29), [session/budget selection](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L1055), [per-request MCP sockets](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/mcp/proxy.py#L40).

### PA08 The on-device provider owns product editing policy

**Medium boundary repair. Confirmed coupling.** The local adapter recognizes “laser eyes,” constructs `find`/`eyes` calls, parses a `structured_data` suffix from result prose, and decides whether an edit succeeded. Constraining a small model is useful, but the transport now depends on artifact-label syntax, tool names, transcript format, and editing workflows. Changing result wording can break the special path while structured results remain valid.

Extract single-edit/face-targeting strategies above transport. Consume typed outcomes and request structured target selection from the model. The adapter should own inference and capability reporting. Keep the constrained behavior explicitly rather than trying to make the small model imitate a full cloud agent.

Evidence: [strategy selection](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/local_vision.py#L40), [laser workflow](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/local_vision.py#L98).

### PA09 The response interface loses safe operational metadata

**Medium priority. Confirmed interface limitation.** `Reply` has text/tool calls; `ProviderError` has a message. Sanitization is correct, but there is no common representation for error category, retry advice, request ID, usage, model identity, or latency. CLI normalization similarly collapses much metadata.

Support cannot reliably distinguish provider latency, repeated requests, context exhaustion, adapter incompatibility, and tool time. Add safe typed failure, usage, completion metadata, and run outcome records. Correlate session/run/request/tool IDs. Unknown usage must remain unknown; subscription-agent cost may not be observable. Label catalog-derived costs as estimates. Full payload capture, if offered, must be a separate explicit diagnostic action.

Evidence: [reply/error interface](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/provider.py#L20), [safe error classification](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/litellm_provider.py#L47), [CLI normalization](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L176).

### PA10 External retry does not establish exactly-once continuation

**Medium priority. Confirmed retry distinction; duplicate side effect requires testing.** API retry resumes stored history without repeating the prompt or completed tools. CLI retry reconstructs the last user request and sends another prompt plus snapshot. External session IDs are adapter state. MCP forwarding has no durable invocation idempotency key.

If a CLI exports successfully and fails before its final answer, Retry can resend the request and the model may export again. The snapshot supplies evidence of completed work but cannot enforce exactly-once effects. This outcome was not reproduced here.

Define Retry separately from Repeat. Supported retry should continue an identified run with completed outcomes and durable operation deduplication where possible. When external continuity is insufficient, offer an explicit “Continue from current result” behavior. Resubmitting text is not equivalent to resuming an interrupted protocol exchange.

Evidence: [API retry](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/agent/loop.py#L319), [CLI retry](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_turn.py#L20), [MCP invocation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/mcp/proxy.py#L83), [external session ID](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/providers/cli_provider.py#L247).

## Comparisons with related projects

These primary sources describe applications hosting agents, durable conversations, or constrained tools. They do not share BadShop's pixel rules. The final column is an architectural inference, not a claim that BadShop should reproduce their product scope.

| Project | Verified pattern | Application to BadShop |
| --- | --- | --- |
| Zed | Hosts thread UI while external agents generally own runtime, authentication, models, tools, and native configuration. [Official documentation](https://zed.dev/docs/ai/external-agents) | Use a distinct external-agent interface and document which authority remains with BadShop. |
| Agent Client Protocol | Negotiates protocol versions/capabilities and defines typed prompt/tool/usage/state updates. [Initialization](https://agentclientprotocol.com/protocol/v1/initialization), [prompt turns](https://agentclientprotocol.com/protocol/v1/prompt-turn) | Candidate for replacing bespoke stream parsing after confinement and image-delivery acceptance. Consulted docs distinguish stable v1 from draft v2. |
| OpenHands | Separates conversation lifecycle/state from an append-only event log; its LLM layer normalizes events and records usage/latency/cost. [Conversation](https://docs.openhands.dev/sdk/arch/conversation), [LLM](https://docs.openhands.dev/sdk/arch/llm) | Borrow typed run records and safe metadata. Do not import remote workspaces, containers, or general coding machinery. |
| Aider | Selects relevant repository structure under a token budget and adapts the map to conversation state. [Repository map](https://aider.chat/docs/repomap.html) | Build a compact artifact/step dependency view. Borrow relevant-state selection, not code-search machinery. |
| Goose | Documents session permission modes and CLI-provider permission integration. [Official repository](https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/managing-tools/goose-permissions.md) | Preserve consistent approvals across adapters. BadShop's deterministic registry rules suit its narrow tools better than model-based classification or general shell access. |

## Target contracts

These responsibilities are grounded in current callers. They are not a proposal for a generic plugin framework or a class for every noun.

| Owner | Responsibilities | Exclusions |
| --- | --- | --- |
| Run controller | Identity, lifecycle, checkpoints, cancellation, budgets, terminal outcome, retry eligibility | Pixels and provider serialization |
| Tool invocation service | Validation, proposal, approval, session execution, durable outcome, supported deduplication | Alternate artifact store or engine path |
| Completion adapter | One request, normalized reply, safe usage/error metadata | Session mutation and editing recipes |
| External-agent adapter | Process/session lifecycle, capability contract, normalized events, scoped grant | Renderer authority or independent pixels |
| Context assembler | Budgeted projection, references, paired outcomes, image views | Authoritative state or destructive history truncation |
| Constrained editing strategy | Local-assistant policy and typed tool outcomes | HTTP/process transport and credentials |
| Compatibility manifest | Tested versions/features, restrictions, evidence | Claiming that help flags prove integration |

A run has one terminal outcome. Late events carry enough identity to reject them after replacement. An approval binds the exact invocation and parameter revision. Application tools must not be replayed just because a response was lost.

## Migration and acceptance

Each stage may need multiple focused PRs. Keep one observable behavior change per PR and remove superseded paths with their replacement.

| Stage | Work | Acceptance |
| --- | --- | --- |
| 1 | Characterize API, JSON fallback, CLI, local semantics | Matrix covers attachments, rejection/edit, budgets, pause, retry, switch, reconnect, interruption, cleanup; labels unit/fake/live evidence. |
| 2 | Fix retirement and bound CLI turns/output | Old PID/private directory gone after profile edit; inert/noisy fake agent exits cleanly; human approval wait survives; completed pixels preserved. |
| 3 | Typed outcomes/capabilities/usage | No loop capability `getattr`; refusal/truncation/auth/timeout/unknown usage distinguishable; diagnostics contain no secrets, image bodies, or prompts. |
| 4 | Shared lifecycle/invocation owners | API/CLI use defined consistent policy; double Stop/disconnect leaves no orphan approval or duplicate terminal event. |
| 5 | Session/run grants | Stale proxy cannot mutate replacement, including reopening the same persistent project ID; revoked grants cannot reconnect. |
| 6 | Context budgeting | Long projects fit configured ceilings; unresolved calls remain paired; current/requested old images remain accessible; project history unchanged. |
| 7 | Local strategy extraction | Basic edit/face targeting consume typed outcomes; presentation wording changes do not break behavior; ambiguity/rejection remains visible. |
| 8 | Durable history migration | Old projects open/save/reopen preserving steps/artifact bytes; incompatible adapter metadata never crosses boundaries; interrupted state restores deterministically. |
| 9 | One ACP trial | Recorded version proves images, restricted tools, approval edits, continuation, cancellation, process-tree cleanup; adoption deletes meaningful bespoke code. |
| 10 | Remove obsolete paths | Delete old writers, duplicate finish lists, private helper imports, and replaced parsers with explicit compatibility-reader lifetime. |

Inspect actual side effects during acceptance: exported file count/content, artifact hashes, approval count, process existence, and temporary directory cleanup. A status event does not prove completion. A red-image/tool-call smoke establishes basic protocol behavior, not creative quality, long-context stability, or subscription-agent confinement.

## Coverage limits

The repository has extensive fake-provider, parser, context, cancellation, and approval tests; live API/CLI probes are opt-in. The CLI fixture README identifies synthetic inputs. Preserve those distinctions in release claims.

This audit read implementation and relevant tests. It did not call live providers, access credentials, launch the application, or run an application suite. Retirement, budget difference, absent text ceiling, and coupling are source findings. Resource consumption, concrete overflow thresholds, and duplicate external retry effects require focused measurements. No application behavior was changed.
