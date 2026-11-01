# Novelty without losing the joke

The chat composer has a **Novelty** selector:

- **Different visual format** keeps the subject and joke while requesting another layout.
- **Keep joke, change setting** requests new surroundings and a new background.
- **Another era** requests a stated period reflected in sources, typography, and composition.
- **Avoid recent images / formats** supplies recent source URLs, artifact labels, layouts, and styles
  to the art director, with guidance to exclude previously used URLs from discovery.

These are explicit instructions to the selected model, not automatic guarantees. Explicitly
supplied images and named requested formats take precedence. Geometric and perceptual image scores
do not establish whether a joke is funny or whether two poses are compatible; the model must look.

**Images & directions → Recent choices** shows the local history. The history file lives at
`creative-history.json` in the application's data directory, retaining up to twelve session/branch
summaries with forty distinct visual choices each. It contains image hashes/labels, eligible source
URLs, layout ids, and style ids. It does not store full prompts, conversations, local folder paths,
or URLs containing query-string credentials. **Forget prior-session choices** clears this stored
history; the current session still provides context and later work can build a new history.

The `chat.send` RPC accepts optional `novelty`: `different-format`, `change-setting`, `another-era`,
or `avoid-recent`. The server appends the direction and bounded, delimited reference data to the
saved user message, so API and CLI providers see the same request. `novelty.recent` and
`novelty.clear` are user-only methods.
