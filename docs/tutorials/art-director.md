# Guide an AI art director

[Documentation](../README.md) · Previous: [Manual tools and replay](edit-and-replay.md)

**Goal:** ask for one image edit, inspect the proposed tool call, approve it, and
refine its parameters yourself. You need a picture and a configured vision-capable
provider. Manual tools and Quick ideas remain available without one.

The model chooses operations. BadShop's engine performs them and records each one
in History. A prompt is creative direction, so different providers may choose
different steps; the engine parameters remain inspectable.

## 1. Connect a provider

Open **Settings → Providers → Add provider**. Give the profile a recognizable name
and select the provider kind that matches what you already use:

| Provider path | Fill in | Check before editing |
| --- | --- | --- |
| Cloud API | A preset or model identifier, plus credentials through the OS keychain or a named environment variable | **Check setup** inspects capabilities; **Test connection** sends a request and may incur charges |
| Local model/server | Model identifier and the local server's API base URL | The server must be running and accept images; use capability overrides only for supported features |
| OpenAI-compatible endpoint | Model identifier, base URL and that endpoint's credentials if required | Confirm the endpoint supports image input and the configured tool mode |
| Subscription CLI | Installed CLI, optional executable path and optional model | Sign in through the CLI first, then use **Detect installed CLI** / **Check installation** |

Save the profile, close Settings and select it in the header's provider selector.
Subscription CLIs use their own login; do not paste a subscription token into an
API-key field. The optional built-in on-device setup and asset requirements are
covered in [compatibility](../compatibility.md).

If your model lacks native tool calling, BadShop shows a warning about the JSON
fallback. That does not give a text-only model vision. Read capability errors
before continuing. No particular model name or subscription is required by this
tutorial.

## 2. Ask for one small change

Open **Art director / All tools**, import a picture and select it. Set
**Approval mode** in the header to **Ask for changes**. Enter:

> Deep-fry this picture once. Keep the composition and stop after the effect.

Send the message. The assistant may first inspect the image with read-only tools.
When it proposes a change, a **Your call** card shows the tool and parameters.

| Approval mode | What waits for your decision |
| --- | --- |
| **Ask for changes** | Tools that are not read-only, including export |
| **Ask for everything** | Every proposed tool call, including inspection |
| **Auto** | Routine tool calls run without a per-tool pause |

Pinned source, caption or placement settings can still require approval in Auto
mode when the AI operates on the protected result or its descendants. See
[manual corrections](../manual-controls.md) for pins, pause controls and undoing
the last AI turn.

## 3. Approve, edit or reject

Read the proposed image reference and effect parameters. Choose **Approve** to
run it. The step should finish in History and the result should appear in the
viewer. To change a proposal before it runs, choose **Edit**, adjust its form and
use **Approve with changes**. To decline it, optionally enter a note such as
`Keep the original colors; use a caption instead`, then click **Reject**.

After the turn finishes, select its completed step and use **Apply & replay** to
change it without another model call. For example, changing the `deepfry` seed
varies its deterministic noise. The [manual tutorial](edit-and-replay.md) explains
how downstream steps follow updated outputs.

Use **Stop** if the assistant is doing too much or is waiting on an approval you
no longer want. Completed steps remain. If a provider request fails, inspect its
error, correct the connection or setup, and use **Retry turn** when offered. Retry resumes
the failed provider request without deliberately repeating completed tool calls.

## 4. Keep and share the result

Select the output you want, save a `.badshop` project with **Ctrl+S / Cmd+S**, then
use **Export** or **Copy image**. The project keeps the conversation, timeline and
images; the image file is for sharing. Reopening the project should restore those
records. Credentials stay in the keychain/environment rather than the project.

For a more involved second exercise, ask:

> Add a large caption saying “ABSOLUTELY FINE”. Keep the edges hard. Show me the
> result, then stop so I can adjust the text.

Inspect each proposal and check the caption in the small export preview. For more
material, explore [image discovery](../image-discovery.md), [styles and branches](../retro-workbench.md)
or [the idea mixer](../idea-mixer.md).

## Troubleshooting

- **No provider is selected:** select the saved profile in the header. Saving a
  profile and making it active are separate actions.
- **A local request fails:** confirm the server is running, the model supports
  images and its context window can hold the conversation, images and tool list.
- **A CLI is missing:** sign in outside BadShop, then check its installation. Use
  the executable-path field for a custom installation.
- **Local only blocks the request:** that preference blocks cloud/custom/CLI
  provider paths; it permits chat with a local-provider loopback address. Choose
  a compatible local profile or change the preference intentionally.
- **An approval edit is rejected:** correct the invalid field or choose an image
  in the current project, then submit again. An invalid edit does not count as approval.

See [support](../support.md) for diagnostics and [privacy](../privacy.md) for what
images and text leave the machine when a remote provider is used.
