# Plan 3: providers and the vision agent

Implementation started 2026-10-31 against Plan 2 commit `b4188b5`.
Read the design spec and `2026-09-27-plan-1-carry-forward.md` alongside this record.

## Implemented

- LiteLLM async chat completion adapter: streamed text, rebuilt parallel tool calls,
  capability checks with explicit vision/tool overrides, cancellation and bounded requests.
  Errors exposed to clients omit raw SDK bodies and credentials.
- Provider profiles persisted atomically in `providers.json`; explicit keys in the OS
  keychain, or named environment variables. New key slots preserve the existing key if
  a profile write fails. No automatic plaintext fallback. A corrupt profile file leaves
  sessions/tools available and is not silently overwritten.
- User-only `providers.list/save/delete/test/select` RPCs (`add` aliases `save`), profile
  selection saved through the existing session profile-ID field, and `provider.status`.
  `providers.test` inspects installed capability metadata; `probe=true` explicitly makes
  a test completion. Custom endpoints do not inherit unrelated ambient cloud keys.
- `chat.retry` resumes the last failed provider request in the current running core,
  retaining completed steps and avoiding a duplicate user message. A fresh send clears it.
- Transient image context: latest output plus recent turn references and new imports,
  at most eight PNG views resized with nearest-neighbor to 1024 px. Persisted transcripts
  contain artifact IDs/text, never the generated base64 request payloads.
- Prompt adapted from the reference skill; structured tool results; escaped boundaries
  around web results, including legacy transcripts; corrected finish/export descriptions.
- Model font parameters restricted to discovered font names in both schema and validation;
  the trusted user retains file-path selection.
- `badshop chat`: model/profile setup, streamed text, attached imports, approve/reject/edit,
  save/open/restore/retry and clean EOF/Ctrl-C shutdown through the existing CoreApp.

## Completion follow-up

The remaining implementation landed in [`2026-10-31-complete-app.md`](2026-10-31-complete-app.md):
JSON-mode tool fallback, visible capability warnings, desktop UI and CLI/MCP integration.
Live vision/native-tool smoke passed against Gemini 3.8 Flash and local Ollama Qwen3-VL 2B.
Claude Code and Codex each passed a real resumed turn that opened an image through MCP.
Local Ollama also passed the forced JSON fallback.
The first forced Gemini JSON fallback exceeded the harness's 90-second timeout; a retry
with a 180-second limit completed in 76 seconds. Both cloud and local fallback checks passed.

Linux Secret Service passed a synthetic credential set/get/delete round-trip. Actual
Windows/macOS keychain checks remain release validation. Profile unit
tests use an isolated keychain; missing/unlock errors offer an environment variable, and
plaintext storage is not implemented. The later completion record supersedes the earlier
"no paid provider calls" statement below, which describes only the original Plan 3 turn.

No session schema bump: all persistent session fields already existed at schema 1.

## Validation this session

- Baseline before changes: 1,335 passed, one network test deselected.
- Full regression run: 1,407 passed, one network test deselected. The installed SDK emits
  one Pydantic `ReadOnly` warning; there are no failures or resource-leak warnings.
- After the final queued-start regression cases were added: all 29 terminal/startup tests
  pass, covering the final source. Adapter tests include a real local HTTP/SSE endpoint
  with image input and tool-call fragments, plus the installed Ollama image transformer.
- `uv run ruff check .`, `uv lock --check`, and `git diff --check` pass.
- No paid provider calls were made. No production keychain entries were accessed in tests.
- Pre-PR verification on the final code: 1,411 passed, one network test deselected,
  the same SDK/Pydantic warning; Ruff and lockfile checks pass.
