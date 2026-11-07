# BadShop reliability audit

Baseline: main `05de166`, including the state-machine fixes in PR #12. This follow-up
audits the six requested areas in the order below. Confirmed issues, fixes, tests,
and retained evidence are maintained here. Pixel algorithms remain unchanged.

## Acceptance and order

| Order | Area | Acceptance criteria |
| --- | --- | --- |
| 1 | Native lifecycle | A smoke pass requires authenticated renderer readiness and usable session data; interruption/restart/normal close preserve work and drain children. Attribute or explicitly delimit the observed native teardown diagnostic. |
| 2 | Crash consistency | Hard termination and failed writes preserve the last committed project; competing cores cannot steal recovery or silently overwrite shared runtime state. Multi-resource writes expose no partial committed records. |
| 3 | Trust boundaries | Untrusted RPC actors, project/archive members, URLs, and paths cannot obtain user-only authority, traverse paths, or expose secrets. Refusals leave state consistent. |
| 4 | Resource ownership | Cancellation, malformed input, slow clients, repeated starts/stops and failures have bounded resources and deterministic cleanup; the next operation remains usable. |
| 5 | Windows portability | Classify the 68 prior failures, repair actual product defects and invalid platform assumptions, and retain passing relevant Windows checks without hiding unsupported capabilities. |
| 6 | Project/replay compatibility | Old/current projects and changed schemas restore faithfully or fail with actionable errors; corrupt/oversized archives are bounded; replay respects artifact identity and engine/cache versions. |

## Findings and repair ledger

Audit in progress. Priority is impact; implementation follows the acceptance order.

| Issue group | Impact and reachable evidence | Repair and regression |
| --- | --- | --- |
| R1: Native lifecycle and verification | P1 verification gap: TCP plus image entropy passed a loading renderer, and could pass `corrupted double-linked list` with a successful shell exit. The stronger run also found surviving core processes on direct and source-launcher close. | Opt-in renderer/session probe, fatal-diagnostic rejection, retained core logs, crash/recovery exercise. Native lifecycle investigation remains open. |
| R2: Exclusive runtime ownership | P1 recovery loss: `CoreApp.__init__ → claim_autosave` moves `session.badshop` to the shared `previous.badshop`; a second live core can claim it and independently overwrite shared settings/profiles/library state. Per-instance asyncio locks do not protect another process. | Hold OS locks on both data and config directories for the complete server/terminal lifetime, before constructing CoreApp. Real competing-core test preserves the live recovery bytes; process tests cover partial overlap, forced termination and retry. |
| R3: Actor-bound authority | P1 approval bypass: `_make_provider` passed the renderer token to CLI proxy configuration; `_hello` accepted that token with any client-supplied actor, including `user`. User RPCs can approve steps and change approval mode. | Derive distinct HMAC credentials for each CLI actor. User token stays in the shell/core; CLI credentials cannot authenticate as user or another CLI. Bad-hello transport cases and the real MCP bridge cover refusals and legitimate use. |
| R4: Bounded subscribers and requests | P2 exhaustion: every WebSocket frame created an independent task; both event and output queues were unbounded. A blocked tool or slow reader could retain unlimited calls/snapshots. | Limit per-socket pending calls and queued messages/bytes. Overload closes the socket with 1013, drains/cancels requests and applies existing disconnect approval cleanup. Slow-subscriber and request-flood regressions also require a healthy subscriber/new connection to work. |

### Ownership and transitions

| Boundary | States and allowed transitions | Invariant / failure behavior |
| --- | --- | --- |
| Runtime lease | unowned → held → released; contender → refused; crashed owner → OS release → retry | Acquire all data/config locks before recovery or configuration mutation; release partial acquisitions; never delete lock-file inodes. Standalone low-level Session/CoreApp instances require their embedding caller to own shared directories. |
| Project save | old committed file → sibling temporary archive → fsync → atomic replace | Hard termination before replace preserves the prior archive. Existing failed-replace regression plus a real killed writer check reopening and a subsequent successful save. Interrupted temporary files may remain, but are never recovery candidates. This tests process death, not physical power-loss durability. |
| RPC authentication | untrusted → authenticated(actor) or closed(1008) | Credential is bound to actor before dispatch; derived CLI credentials remain privileged within their own scope, and expire with the core token. Raw clients using the old user token as a CLI actor must use the scoped credential supplied by BadShop. |
| Subscriber | active → overloaded → detached/closed; disconnect → canceled → drained | Queue limits apply to retained string size and message count. Socket overload must be visible, rather than silently dropping events while leaving stale UI connected. |

Library writes already publish immutable image blobs before the atomic JSON record;
failure before the record can leave unreferenced blobs but cannot publish a partial
record. Existing project-member traversal, hash, bounded decompression, image-decoder,
RPC method-scope and network-policy tests remain part of final validation.

## Verification

Evidence: `artifacts/verification/reliability/`. Use isolated Windows and Linux
worktrees, separate Python environments, private Xvfb, temporary config/data and local
scripted providers. No live provider calls or model downloads are needed. Source
debug desktop checks do not establish installed-package coverage.

- Windows `boundaries-windows.log`: 26 targeted tests passed (crash/lease,
  authentication, request flood, slow subscriber and queue bounds).
- Windows `lease-core-windows.log`: real competing core refused, recovery untouched.
- Linux `native-first/summary.json`: build passed; direct and launcher lifecycle
  failed on surviving cores. Launcher stderr also reproduced the allocator diagnostic.
  Neither run is counted as passing native coverage.
