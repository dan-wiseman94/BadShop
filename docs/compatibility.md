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

Imports accept PNG, JPEG, GIF, WebP, BMP and TIFF. HEIC/HEIF and AVIF are not supported by
the import allowlist; export a PNG or JPEG from your photo application first. The original
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

Current code reads project schemas 1–3 and refuses newer schemas with an explanation.
Save a copy before experimenting with a different application version; backward readability
by older apps is not promised. Saving is atomic and preserves the last good file on failure.
Autosave is recovery, not a substitute for explicitly saving important work. Imported privileged
transcript roles are removed; imported text is never trusted as system instructions.

Keep original installers and a copy of important projects for rollback. Do not overwrite your
only project with an older version. If an update fails, keep the current installer/session,
record diagnostics, and use a verified manual installer. Package-manager installations update
through their manager; self-update applies to supported NSIS, Mac app and AppImage builds.
