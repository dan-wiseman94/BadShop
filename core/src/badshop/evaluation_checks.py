"""Deterministic observations from an archived timeline and explicitly chosen output."""

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from badshop.session.models import Step
from badshop.session.session import Session, _image_refs
from badshop.tools.registry import REGISTRY

PASTE_BOX = re.compile(r"piece placed with top-left at \((-?\d+), (-?\d+)\), (\d+)x(\d+) after scaling")
TEXT_ORIGIN = re.compile(r"at top-left \((-?\d+), (-?\d+)\)$")


@dataclass(frozen=True)
class Check:
    name: str
    status: Literal["pass", "fail", "review", "unknown"]
    detail: str


def repeat_counts(steps: list[Step]) -> dict[str, int]:
    """Count extra occurrences, using stored validated params and content-hash image refs."""
    calls, outputs, placements = Counter(), Counter(), Counter()
    for step in steps:
        if not step.actor.startswith(("agent:", "cli:")) or step.status not in ("done", "error"):
            continue
        calls[step.tool, json.dumps(step.params, sort_keys=True)] += 1
        spec = REGISTRY.get(step.tool)
        if step.outputs and spec and spec.mutates:
            outputs[tuple(step.outputs)] += 1
        if step.tool == "paste":
            placements[step.params.get("base"), step.params.get("piece")] += 1
    return {key: sum(count - 1 for count in counts.values() if count > 1)
            for key, counts in (("repeated_calls", calls), ("repeated_outputs", outputs),
                                ("placement_retries", placements))}


def _lineage(steps: list[Step], output: str) -> tuple[list[Step], set[str], dict[str, set[str]]]:
    # Walk backward in timeline order. A hash can have several producers; the closest
    # completed producer before each consumer owns that occurrence, even for a no-op.
    pending = {output}
    used = set()
    selected = []
    for step in reversed(steps):
        if step.status == "done" and pending.intersection(step.outputs):
            pending.difference_update(step.outputs)
            refs = _image_refs(step)
            pending.update(refs)
            used.update(refs)
            selected.append(step)
    # Resolve the base and piece of each selected paste independently in forward order.
    roots: dict[str, set[str]] = {}
    paste_roots = {}
    for step in reversed(selected):
        inputs = _image_refs(step)
        if step.tool == "paste":
            for field in ("base", "piece"):
                ref = step.params[field]
                paste_roots[step.id, field] = roots.get(ref, {ref})
        ancestors = set().union(*(roots.get(ref, {ref}) for ref in inputs))
        for artifact in step.outputs:
            roots[artifact] = ancestors | {artifact}
    return list(reversed(selected)), used, paste_roots


def _caption_placement(step: Step, width: int, height: int) -> Check:
    name = f"Caption placement · {step.id}"
    origin = TEXT_ORIGIN.search(step.result_text)
    if not origin:
        return Check(name, "unknown", "The saved step has no recognized caption geometry.")
    x, y = map(int, origin.groups())
    if not (0 <= x < width and 0 <= y < height):
        return Check(name, "fail", "Recorded caption bounds start outside the canvas.")
    point = step.params.get("at")
    if point:
        # For a centered caption, its origin and anchor bound the layer extent
        # to within one pixel, including the effect of a rotation.
        right, bottom = 2 * point[0] - x, 2 * point[1] - y
        if right > width or bottom > height:
            return Check(name, "fail", "Recorded caption bounds extend beyond the canvas.")
        if right < width and bottom < height:
            return Check(name, "pass", "Recorded caption bounds fit the canvas.")
    elif step.params.get("bottom"):
        return Check(name, "pass", "Recorded bottom-aligned caption bounds fit the canvas.")
    return Check(name, "review", "Origin is in bounds. Review full caption fit.")


def score_project(session: Session, case: dict, output: str, entry: dict) -> tuple[list[Check], dict[str, int]]:
    steps = session.data.steps
    boundary = entry.get("start_after")
    start = next((i + 1 for i, step in enumerate(steps) if step.id == boundary), 0)
    if "start_after" in entry and not start:
        raise ValueError(f"start_after must name a step in the active timeline, got {boundary!r}")
    scoped = steps[start:]
    current = {step.id for step in scoped}
    lineage, roots, paste_roots = _lineage(steps, output)
    final_steps = [step for step in lineage if step.id in current]
    maker = final_steps[-1] if final_steps and output in final_steps[-1].outputs else None
    completed = maker is not None and maker.tool != "view"
    detail = (f"{maker.id} · {maker.tool}" if completed else
              "The selected artifact is a viewer aid." if maker else "No completed step in this run produced this artifact.")
    checks = [Check("Completed output", "pass" if completed else "fail", detail)]

    role_refs = entry.get("inputs", {})
    roles = case.get("roles", [])
    if not isinstance(role_refs, dict) or any(role not in roles or not isinstance(ref, str) or not ref.strip()
                                              for role, ref in role_refs.items()):
        raise ValueError(f"inputs must map these roles to artifact IDs: {', '.join(roles)}")
    inputs = {role: session.artifacts.resolve(ref) for role, ref in role_refs.items()}
    for role in roles:
        if role not in inputs:
            checks.append(Check(f"Input · {role}", "unknown", "No input ID supplied for this role."))
            continue
        used = inputs[role] in roots
        if role in case.get("ignore_roles", []):
            checks.append(Check(f"Input · {role}", "fail" if used else "pass",
                                "The ignored attachment reaches the output." if used else
                                "The ignored attachment does not reach the output."))
            continue
        if case["id"] == "head-swap" and final_steps:
            field = "base" if role == "target" else "piece"
            paste = next((step for step in reversed(final_steps) if step.tool == "paste"), None)
            used = paste is not None and inputs[role] in paste_roots[paste.id, field]
        checks.append(Check(f"Input · {role}", "pass" if used else "fail",
                            "Used in the selected output." if used else "Missing from the expected output lineage."))

    if "expect_export" in entry and not isinstance(entry["expect_export"], bool):
        raise ValueError("expect_export must be true or false")
    if entry.get("expect_export"):
        export = next((step for step in scoped if step.status == "done" and step.tool == "export"
                       and step.params.get("image") == output and step.result_text.startswith("exported: ")), None)
        checks.append(Check("Export record", "pass" if export else "fail",
                            f"{export.id} recorded a write. Current file presence is unverified."
                            if export else "No successful export step for this output in the selected run."))

    forbidden = [step.id for step in final_steps if step.tool in case.get("forbidden_tools", [])]
    if case.get("forbidden_tools"):
        checks.append(Check("Brief restraint", "fail" if forbidden else "pass",
                            "Unexpected effects: " + ", ".join(forbidden) if forbidden else
                            "Selected output avoids the disallowed effects."))
    if "max_fry_level" in case:
        levels = [step.params["level"] for step in final_steps if step.tool == "deepfry"]
        limit = case["max_fry_level"]
        checks.append(Check("Fry intensity", "pass" if levels and max(levels) <= limit else "fail",
                            f"Recorded levels {levels}; expected a fry at level {limit} or lower."))

    caption = next((step for step in reversed(final_steps) if step.tool == "text"), None)
    if "caption" in case:
        expected = " ".join(case["caption"].split()).casefold()
        matches = caption and " ".join(caption.params["text"].split()).casefold() == expected
        checks.append(Check("Caption wording", "pass" if matches else "fail",
                            f"{caption.id} contains the expected wording." if matches else
                            "The selected output has no matching caption step."))
    if case["id"] == "preserve-concept":
        previous = steps[start - 1] if start else None
        if previous and previous.tool == "text":
            same = caption and caption.params["image"] == previous.params["image"]
            checks.append(Check("Original caption base", "pass" if same else "fail",
                                "Reused the original base." if same else "The caption uses a different base."))
        else:
            checks.append(Check("Original caption base", "unknown", "Supply the original caption as start_after."))

    for step in final_steps:
        if step.tool == "paste":
            base = session.artifacts.meta[step.params["base"]]
            box = PASTE_BOX.search(step.result_text)
            if box:
                x, y, width, height = map(int, box.groups())
                visible = x < base.width and y < base.height and x + width > 0 and y + height > 0
                checks.append(Check(f"Paste placement · {step.id}", "pass" if visible else "fail",
                                    "Bounds intersect the canvas." if visible else "Piece is entirely off canvas."))
            else:
                checks.append(Check(f"Paste placement · {step.id}", "unknown", "No single-piece bounds were recorded."))
        elif step.tool == "text":
            base = session.artifacts.meta[step.params["image"]]
            checks.append(_caption_placement(step, base.width, base.height))

    previous_paste_outputs: dict[str, str] = {}
    for step in scoped:
        if step.status != "done" or step.tool != "paste" or not step.actor.startswith(("agent:", "cli:")):
            continue
        base, piece = step.params["base"], step.params["piece"]
        if previous_paste_outputs.get(base) == piece:
            checks.append(Check("Possible stacked correction", "review",
                                f"{step.id} pastes the same piece onto an earlier result using that piece."))
        previous_paste_outputs.update({artifact: piece for artifact in step.outputs if artifact != base})
    return checks, repeat_counts(scoped)
