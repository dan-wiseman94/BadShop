# First use, requirements and compatibility

BadShop makes deliberately rough photo edits and shitposts. It does not generate image pixels
with an image-generation model. Manual tools and Quick ideas work without a provider.

## Choose a workflow

| Workflow | Needed before starting | Offline fallback |
| --- | --- | --- |
| Quick idea, caption, basic effects, layout | Installed app; bundled sample or your picture | Works without downloads |
| AI art direction | A configured provider with image/tool support; CLI login or API credentials where applicable | Quick ideas and All tools |
| On-device assistant | Optional pinned model/projector and compatible runtime download; see Settings → Assets for the actual total | Manual editing; the small assistant is intended for basic edits |
| Automatic background removal | Optional U2-Net download, about 168 MiB | Rectangle/shape cutout with no AI |
| BiRefNet background removal | About 928 MiB download and substantial memory; historic Linux measurement peaked near 9.3 GiB | U2-Net or manual cutout |
| Video frames | FFmpeg/ffprobe installed and discoverable | Import a still image or GIF |
| PDF pages | Poppler's pdftoppm installed and discoverable | Export the page to PNG/JPEG first |
| Web image discovery | Internet access; some sources also need a key | Bundled sample, imported pictures, Junk drawer, indexed folders |

Settings → Assets shows progress and cancellation. “Local only” blocks remote operations;
it does not download or configure local models. Download required assets first, then enable it.
Use at least 12,288 MB Tool memory for BiRefNet, with additional RAM for the OS and app.
This is a measured example, not a guarantee for every computer or picture.

## Pictures and sharing

Imports accept PNG, JPEG, GIF, WebP, BMP, TIFF and AVIF. AVIF uses the existing Pillow
decoder; its import/edit/save/reopen path is checked on Linux. Installer coverage must
be recorded for each release, and older BadShop versions cannot open projects containing
AVIF originals. HEIC/HEIF still needs conversion to PNG or JPEG in your photo application.
[Pillow includes AVIF support](https://pillow.readthedocs.io/en/latest/releasenotes/11.3.0.html)
in its wheels on BadShop's targeted platforms. The original
bytes are retained; normal editing uses an upright working copy with a longest side of
1,000 pixels. Enlarging an export cannot recreate discarded detail.

Copy image puts a PNG on the clipboard. For animations it copies the selected still frame;
export the original file to preserve the animation. PNG export preserves source transparency;
JPEG flattens it. Resize/format conversion creates a separate History result. Read the joke
in the 320-pixel preview before sharing. Credits export records available source metadata;
it does not grant rights to an image.

## Cloud providers

Under Settings → Providers → Add provider, Cloud API presets fill in a model
for OpenAI, Anthropic, Google Gemini, OpenRouter, Mistral AI, xAI, Together AI, and
Perplexity.
The model remains editable. Supply a key from the selected provider, using the
system keychain or an environment variable. Check setup inspects model capabilities
without a completion. Test connection sends a request to the provider.

The Perplexity preset uses the [Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart)
with an image-capable model that can call functions. Its API key can be stored in
the keychain or read from `PERPLEXITY_API_KEY`. BadShop sends its own editing
tools and applies the session's approval mode before running them. Leave the API
base URL blank for this preset.

## Platform promises

Build targets are Windows x86-64, Linux x86-64, and macOS 14+ on Apple Silicon and Intel.
A target is only release-verified when the exact candidate's installed-platform evidence
passes the [release checklist](releasing.md). A Linux source build or browser test cannot
establish Windows/macOS installer, accessibility, clipboard, keychain or update behavior.
Record OS/build, architecture, CPU/GPU, RAM, runtime/backend, provider version, installer hash
and observed workflow in each release's evidence. Do not carry a previous release's pass forward.

Claude Code and Codex use their own login and processes. Gemini CLI remains experimental.
Provider capabilities and image delivery vary; a configuration check is distinct from the
optional test request and from a successful creative task. Pin tested provider versions in
release notes, and report newer untested versions as such.

Settings can discover subscription CLIs on PATH, in common user install folders,
and inside standard ChatGPT or Codex app installations on macOS. For a custom
installation, enter its path in the Executable path field. On Windows, enter the
path to the native executable or the official npm launcher. The npm versions of
Codex and Gemini CLI need Node.js.

## Project compatibility and recovery

The desktop and core negotiate local wire protocol 1 separately from the project
schema and application version. A mismatched explicit protocol is refused before
commands run. The welcome also identifies the exact core build and process.
Older 0.4.x MCP/updater clients that omit the protocol number remain accepted
during their migration; remove this exception when those clients negotiate the
protocol explicitly. Omitted command context is likewise a transitional 0.4.x
client path, not a guarantee that stale commands are safe.

Desktop actions carry the observed document incarnation, branch and revision.
The core checks ownership again after a queued action acquires the document lock.
Stop and Pause require the same document incarnation but may follow a newer run
revision; recipe Stop and approval responses tolerate revision advancement while requiring
the same branch. Older or mismatched events cannot update a newer snapshot.
Sequence gaps trigger refresh, never automatic mutation retries. A lost response
or a malformed server result has an unknown outcome: inspect the current document
before repeating it. Durable operation receipts are not implemented yet.

Snapshots include the active run ID, its emitted partial text and last terminal
outcome so refresh can recover streaming/retry state. This run state is currently
in memory, not crash-durable project history. Saved image and timeline recovery
use portable projects and the local SQLite recovery store.

Local recovery storage version 1 uses `autosave/session.sqlite` and immutable
files in `autosave/blobs/`. The previous run is retained as `previous.sqlite`.
These are application-owned recovery files, not portable projects: use Save to
produce a `.badshop` archive. SQLite files outside the recovery directory are
not accepted by the project importer. Unknown recovery versions are refused.

The older `session.badshop`/`previous.badshop` recovery format remains readable.
When no SQLite recovery is available, startup offers the legacy archive; Restore
validates it through the normal archive reader, then the next autosave writes
SQLite. The legacy backup remains unchanged. Keep this importer while supported
0.4.x/0.5.x installations can upgrade directly. Downgrading does not convert a
SQLite recovery database: save a portable project before using an older release.

Managed CLI processes receive random revocable adapter credentials, separate from
the renderer token. Document calls require an active run and matching direction;
tool discovery can run while idle. Stop ends authorization for queued work, and
an older socket cannot borrow a later run. Document, direction and profile
replacement revoke the credential and retire the process's private configuration.
The cached process can reconnect with the same credential for its next run until
one of those replacement boundaries retires it.

Standalone MCP retains explicit HMAC-derived credentials for independently
launched integrations. The current proxy negotiates protocol 1 and binds itself
to its first document incarnation/direction across per-call sockets. Reconnect
the proxy explicitly after replacing either. Older 0.4.x proxies without hello
context remain connection-scoped only; remove that exception when the supported
independent clients all negotiate and retain document context. Such credentials
are explicit standalone authorization, not managed-run credentials.

Both the current MCP proxy and native updater explicitly negotiate protocol 1.
The updater refuses a missing or incompatible protocol before starting its HTTP
operation. Its narrow welcome contract has a shared Python/Rust fixture.

API and managed CLI execution consume the same session-owned step budget.
Proposals, user rejection and invalid approval edits consume no execution slot;
an admitted execution attempt consumes one, including tool failure/cancellation.
Parallel approvals cannot exceed the budget. Rejected edits settle in the session
and produce the same recorded result for either provider path.

Current code reads project schemas 1–4 and refuses newer schemas with an explanation.
New automatic turn directions carry an optional retention marker. Missing markers
in older schema 1–4 projects mean permanent retention; names alone never authorize
cleanup. Older format-4 apps can ignore the marker; if they omit it on resave,
those directions become permanently retained when reopened in the current app.
New saves use schema 4 for manual pins, effect bypass and turn checkpoints. Releases
that only support schemas 1–3 cannot open these new saves; keep a backup before upgrading.
See [manual corrections](manual-controls.md) for controls and their limits.
Save a copy before experimenting with a different application version; backward readability
by older apps is not promised. Saving is atomic and preserves the last good file on failure.
Autosave is recovery, not a substitute for explicitly saving important work. Imported privileged
transcript roles are removed; imported text is never trusted as system instructions.

Keep original installers and a copy of important projects for rollback. Do not overwrite your
only project with an older version. If an update fails, keep the current installer/session,
record diagnostics, and use a verified manual installer. Package-manager installations update
through their manager; self-update applies to supported NSIS, Mac app and AppImage builds.
