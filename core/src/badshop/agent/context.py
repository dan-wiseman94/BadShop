"""What the model sees: the system prompt, the tool definitions, and the conversation so far."""

import copy

from badshop.session.artifacts import short
from badshop.session.models import ArtifactMeta
from badshop.session.session import Session
from badshop.tools import REGISTRY
from badshop.tools.registry import llm_schema

# A placeholder until Plan 3 derives the real prompt from reference/SKILL.md. It carries the product rules
# (spec §3) and the one thing every model must know to call a tool at all: images are artifact ids.
SYSTEM_PROMPT = """\
You are the art director of badshop, an app for deliberately bad, 2005-forum-style photoshops. You make \
them by calling badshop's tools; the tools own every pixel.

Rules:
- Bad is the deliverable: hard-edged cut and paste, nearest-neighbor scaling, no blending, feathering, \
colour matching or shadows. Fix a placement at most once or twice, then stop.
- Never use or imitate an image-generation or inpainting model.
- Every image parameter takes an artifact id: the hex id of an image in this session, from a tool result \
or the user's message. The first 8 characters are enough (a3f9c1d2). File paths and URLs are not images; \
get new pictures with fetch, wiki, emoji or template.
- Images appear as placeholders like [image a3f9c1d2: lincoln_work, 761x1000]. Call view with the id to \
look at one, with grid=true to read coordinates. Use find for faces instead of guessing coordinates.
- The user can see, edit, reject and re-run every step. A rejected call comes back as "rejected by user: \
<note>": adapt to the note.
- When the picture is done, say in a sentence or two what you made."""

UNANSWERED = "not run: the app stopped before this call finished"


def tool_definitions() -> list[dict]:
    """Every tool in the OpenAI function format, with the schema a model may fill (no user-only fields)."""
    return [{"type": "function",
             "function": {"name": spec.name, "description": spec.description, "parameters": llm_schema(spec)}}
            for spec in REGISTRY.values()]


def image_placeholder(meta: ArtifactMeta) -> str:
    return f"[image {short(meta.id)}: {meta.label}, {meta.width}x{meta.height}]"


def _answered(transcript: list[dict]) -> list[dict]:
    """The transcript with a result for every tool call. Providers refuse a call left unanswered, which is
    what an autosave taken mid-call leaves behind if the core then dies."""
    out: list[dict] = []
    missing: list[str] = []
    for entry in transcript:
        if missing and entry.get("role") != "tool":
            out += [{"role": "tool", "tool_call_id": i, "content": UNANSWERED} for i in missing]
            missing = []
        out.append(entry)
        if entry.get("role") == "tool" and entry.get("tool_call_id") in missing:
            missing.remove(entry["tool_call_id"])
        if entry.get("role") == "assistant":
            missing = [c["id"] for c in entry.get("tool_calls") or []]
    out += [{"role": "tool", "tool_call_id": i, "content": UNANSWERED} for i in missing]
    return out


def build_messages(session: Session) -> list[dict]:
    """The system prompt plus the current step list, then the provider-format history (copied: a
    provider may rewrite what it is given)."""
    summary = session.summary()
    steps = f"Steps so far:\n{summary}" if summary else "No steps yet."
    system = f"{SYSTEM_PROMPT}\n\n{steps}"
    return [{"role": "system", "content": system}, *copy.deepcopy(_answered(session.data.transcript))]
