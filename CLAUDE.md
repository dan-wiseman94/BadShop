# badshop — project notes for Claude

- The design spec is `docs/superpowers/specs/2026-09-26-badshop-app-design.md`. Read it
  before doing anything; it records the decisions and why.
- `reference/badshop.py` is the proven engine (single-file CLI, PEP 723 deps). Port it
  into `core/badshop/engine/`; do not rewrite its pixel logic. `reference/tool-catalog.md`
  lists every command and parameter; the tool registry must cover all of them.
- `reference/SKILL.md` is how an LLM currently art-directs the engine. Its workflow and
  style rules become the agent's system prompt.
- Non-negotiable product rule: no image-generation model ever touches pixels. Hard edges,
  nearest-neighbor scaling, no blending. Bad is the deliverable.
- The user's machine: Arch Linux, KDE Plasma 6 (Wayland), `uv` available, `sudo` needs a
  password (so no unattended system package installs).
