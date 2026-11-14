# Privacy and local data

Screen capture runs only after **Capture screen region**. It uses your OS's capture
permission flow where available, then keeps a local preview until you import or
cancel it. Cancelling through the import panel removes that cached capture.
Imported regions are ordinary project images, without a full-screen original
containing pixels outside the selected region. Capture itself does not contact a
provider. Windows/macOS screen permissions and the Wayland desktop portal remain
under OS control.

BadShop stores projects, autosaves, preferences, provider profiles, cached assets, image-library
entries and diagnostics on your computer. Credentials use the OS keychain or named environment
variables. Provider secrets are not saved in project archives. Projects can contain original
pictures, prompts, replies, source URLs, filenames and credits: inspect what you share.

**Export → Let someone remix this** creates a separate, limited project with the selected
image's local edit chain and dependency pictures. It strips original containers, embedded
photo metadata, private filename hints, conversations and unrelated directions. Inspect
the included picture previews and optional source credits before exporting. Faces, visible
words and edit parameters remain; captions can themselves contain private information.
Custom fonts must be replaced with the default and replayed before editable sharing.
This filter applies to editable remix export, not ordinary project saves or asset packs.

Quick ideas and local editing need no service account. Configuring an API/CLI provider can send
prompts, conversation context and selected images to that provider. Provider billing, retention
and policies are separate from BadShop. Subscription CLIs are external processes and can have
their own network behavior. Source search sends search terms to selected collections; downloads
contact the asset/source hosts. Automatic update checks contact GitHub when enabled.

Settings → Preferences → Sources, privacy and creative history includes **Local only**.
Its acknowledgement means incompatible active turns, probes, downloads and update checks have
stopped. New remote calls are blocked. A local provider must use a loopback address; CLI providers
are disabled in this mode. Loopback servers remain separate software and may themselves contact
other services. Local only is an application policy, not an OS firewall or a sandbox.

Non-loopback plaintext HTTP providers require a per-address opt-in because images, prompts and
credentials would travel without transport encryption. HTTPS is the normal choice. Guarded image
downloads pin vetted DNS addresses and bypass ambient proxies so a proxy cannot bypass that
address policy. This may require direct outbound access on a corporate network.

Image decoding, media preview/indexing and editing use supervised child processes in the desktop.
Decode/media work has a 30-second execution budget and 1 GiB RSS watchdog; startup has a separate
60-second limit. Session image bytes are capped at 2 GiB, matching the archive payload ceiling.
These are failure/resource controls, not exploit containment: workers retain ordinary user-level
permissions. The per-file, pixel and preview limits still apply. Process RSS can briefly exceed a
sampled watchdog threshold. The standalone engine CLI and in-process embedding do not provide
the desktop's decode supervision.

Cancel preview/indexing stops both active and queued extraction requests. The supervising
process owns temporary video/PDF copies and removes them after normal completion, cancellation
or worker failure; an abrupt OS crash/power loss can still require normal OS temporary-file cleanup.

Settings can clear creative history and disposable source previews. Deleting an index does not
delete original pictures. Saved projects and exports remain until you delete them yourself;
removing a provider profile attempts to remove its saved keychain entry. OS backups and provider
copies are outside BadShop's control. Review diagnostics before posting them: automatic redaction
reduces accidental disclosure but cannot recognize every private filename or conversation detail.

Local settings also retain up to 20 recent project paths, names and small PNG
previews, up to 30 export presets, and up to 50 reusable designs with text defaults.
Turning off history prevents new recent-project entries; remove existing entries
from Projects. Removing a recent entry or reusable design does not delete project
files, source images or exported files. These libraries are local, not uploaded.

No analytics or crash-upload service is added by this release work. Support and research below
are opt-in activities; do not add silent usage tracking to implement the proposed product study.
