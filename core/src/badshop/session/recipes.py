"""Bounded declarative recipes. No shell commands, scripts, downloads or file writes."""

import json
from pydantic import BaseModel, ConfigDict, Field, model_validator
from badshop.engine.errors import EngineError
from badshop.tools import registry, runner


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    params: dict


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(1, ge=1, le=1)
    name: str = Field(min_length=1, max_length=100)
    steps: list[RecipeStep] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_steps(self):
        if len(self.model_dump_json()) > 100000:
            raise ValueError("recipe is too large")
        for i, step in enumerate(self.steps):
            spec = registry.get(step.tool)
            if spec.network or spec.writes_files or not spec.mutates:
                raise ValueError("recipes only accept local image-producing tools")
            runner.validate(step.tool, step.params)
            for ref in registry.image_refs(spec.params, step.params):
                if ref != "$input" and ref not in {f"$step{n}" for n in range(i)}:
                    raise ValueError("recipe images must be $input or an earlier $stepN")
        return self


def capture(session, step_id):
    step = session.step(step_id)
    if step.status != "done":
        raise EngineError("choose a completed tool step")
    if step.bypassed:
        return Recipe(name="Bypassed effect", steps=[RecipeStep(tool="transform", params={"image": "$input"})])
    params = dict(step.params)
    for key, many in registry.image_fields(registry.get(step.tool).params).items():
        if params.get(key) is not None:
            params[key] = ["$input"] if many else "$input"
    return Recipe(name=step.tool, steps=[RecipeStep(tool=step.tool, params=params)])


def run(session, recipe, inputs, cancel):
    completed = []
    errors = []
    for source in inputs:
        outputs = []
        for item in recipe.steps:
            if cancel.is_set():
                return {"completed": completed, "errors": errors, "cancelled": True}
            params = json.loads(json.dumps(item.params))

            def resolve(ref):
                return source if ref == "$input" else outputs[int(ref[5:])]

            params = registry.map_image_refs(registry.get(item.tool).params, params, resolve)
            step = session.propose(item.tool, params, "user", reason="Recipe: " + recipe.name)
            step = session.run(step.id, cancel=cancel)
            if step.status != "done" or not step.outputs:
                errors.append(
                    {
                        "input": source,
                        "step_id": step.id,
                        "message": step.error.message if step.error else "no output",
                    }
                )
                break
            outputs.append(step.outputs[0])
            completed.append(step.id)
    return {"completed": completed, "errors": errors, "cancelled": cancel.is_set()}


def credits(session, artifact_id):
    """Follow every input edge, including original imports. Never attribute unrelated search hits."""
    pending = [session.artifacts.resolve(artifact_id)]
    seen = set()
    sources = []
    all_steps = [*session.data.steps, *(s for b in session.data.branches.values() for s in b.steps)]
    while pending:
        aid = pending.pop()
        if aid in seen:
            continue
        seen.add(aid)
        meta = session.artifacts.meta[aid]
        if meta.source:
            row = meta.source.model_dump(mode="json")
            if row not in sources:
                sources.append(row)
        if meta.original_id:
            pending.append(meta.original_id)
        # Match output ids too: branch step ids can name different edits.
        step = next((s for s in all_steps if s.id == meta.produced_by and aid in s.outputs), None)
        if step:
            pending.extend(registry.image_refs(registry.get(step.tool).params, step.params))
    return {
        "artifact_id": artifact_id,
        "sources": sources,
        "notice": "Source metadata is supplied by the collection. Unknown rights remain unknown.",
    }
