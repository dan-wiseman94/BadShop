"""Bounded declarative recipes. No shell commands, scripts, downloads or file writes."""

import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from badshop.engine.errors import EngineError
from badshop.tools import registry, runner


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    params: dict


class RecipeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image", "text"]
    default: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def portable_default(self):
        if self.kind == "image" and self.default is not None:
            raise ValueError("choose image inputs when running a design; project images are not portable defaults")
        return self


def _text_values(value, inputs):
    if isinstance(value, str) and value.startswith("$text:"):
        name = value[6:]
        if name not in inputs:
            raise EngineError(f"missing text input: {name}")
        return inputs[name]
    if isinstance(value, list):
        return [_text_values(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: _text_values(item, inputs) for key, item in value.items()}
    return value


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(1, ge=1, le=2)
    name: str = Field(min_length=1, max_length=100)
    steps: list[RecipeStep] = Field(min_length=1, max_length=40)
    inputs: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")], RecipeInput] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_steps(self):
        if len(self.model_dump_json()) > 100000:
            raise ValueError("recipe is too large")
        if self.version == 1 and self.inputs:
            raise ValueError("named inputs require recipe version 2")
        if "input" in self.inputs and self.inputs["input"].kind != "image":
            raise ValueError("input is reserved for the main image")
        images = {f"$input:{name}" for name, item in self.inputs.items() if item.kind == "image"}
        texts = {name: item.default or "" for name, item in self.inputs.items() if item.kind == "text"}
        for i, step in enumerate(self.steps):
            spec = registry.get(step.tool)
            if spec.network or spec.writes_files or not spec.mutates:
                raise ValueError("recipes only accept local image-producing tools")
            runner.validate(step.tool, _text_values(step.params, texts) if self.version == 2 else step.params)
            for ref in registry.image_refs(spec.params, step.params):
                if ref != "$input" and ref not in images and ref not in {f"$step{n}" for n in range(i)}:
                    raise ValueError("recipe images must be a declared input or an earlier $stepN")
        return self


def capture(session, step_id):
    step = session.step(step_id)
    if step.status != "done":
        raise EngineError("choose a completed tool step")
    if step.bypassed:
        return Recipe(name="Bypassed effect", steps=[RecipeStep(tool="transform", params={"image": "$input"})])
    params = dict(step.params)
    inputs = {}
    for key, many in registry.image_fields(registry.get(step.tool).params).items():
        if params.get(key) is not None:
            names = [f"{key}_{i + 1}" for i in range(len(params[key]))] if many else [key]
            inputs.update({name: RecipeInput(kind="image") for name in names})
            params[key] = [f"$input:{name}" for name in names] if many else f"$input:{key}"
    for key in ("text", "title", "caption", "captions"):
        value = params.get(key)
        if isinstance(value, str):
            inputs[key] = RecipeInput(kind="text", default=value)
            params[key] = f"$text:{key}"
        elif isinstance(value, list):
            names = [f"{key}_{i + 1}" for i in range(len(value))]
            inputs.update({name: RecipeInput(kind="text", default=item) for name, item in zip(names, value, strict=True)})
            params[key] = [f"$text:{name}" for name in names]
    return Recipe(version=2, name=step.tool, inputs=inputs, steps=[RecipeStep(tool=step.tool, params=params)])


def run(session, recipe, inputs, cancel):
    completed = []
    errors = []
    rows = [{"index": index, "status": "pending", "step_ids": [], "output_id": None, "error": None} for index in range(len(inputs))]
    for row_index, source in enumerate(inputs):
        outputs = []
        row = rows[row_index]
        if cancel.is_set():
            for remaining in rows[row_index:]:
                remaining["status"] = "cancelled"
            return {"completed": completed, "errors": errors, "rows": rows, "cancelled": True}
        try:
            bindings = {"input": source} if isinstance(source, str) else dict(source)
            allowed = {"input", *recipe.inputs}
            if set(bindings) - allowed:
                raise EngineError("unknown design input")
            for name, item in recipe.inputs.items():
                if name not in bindings and item.kind == "text":
                    bindings[name] = item.default or ""
                if name not in bindings:
                    raise EngineError(f"choose an image for {name}")
            for name, value in list(bindings.items()):
                if not isinstance(value, str) or len(value) > 4096:
                    raise EngineError(f"invalid value for {name}")
                if name == "input" or recipe.inputs[name].kind == "image":
                    bindings[name] = session.artifacts.resolve(value)
        except EngineError as error:
            row.update(status="error", error=error.message)
            errors.append({"input": source, "row": row_index, "message": error.message})
            continue
        for item in recipe.steps:
            if cancel.is_set():
                for remaining in rows[row_index:]:
                    remaining["status"] = "cancelled"
                return {"completed": completed, "errors": errors, "rows": rows, "cancelled": True}
            text_bindings = {name: bindings[name] for name, spec in recipe.inputs.items() if spec.kind == "text"}
            params = (_text_values(item.params, text_bindings) if recipe.version == 2
                      else json.loads(json.dumps(item.params)))

            def resolve(ref):
                if ref == "$input":
                    if "input" not in bindings:
                        raise EngineError("choose the main input picture")
                    return bindings["input"]
                if ref.startswith("$input:"):
                    return bindings[ref[7:]]
                return outputs[int(ref[5:])]

            try:
                params = registry.map_image_refs(registry.get(item.tool).params, params, resolve)
                step = session.propose(item.tool, params, "user", reason="Recipe: " + recipe.name)
            except EngineError as error:
                row.update(status="error", error=error.message)
                errors.append({"input": source, "row": row_index, "message": error.message})
                break
            step = session.run(step.id, cancel=cancel)
            row["step_ids"].append(step.id)
            if step.status != "done" or not step.outputs:
                row.update(status="error", error=step.error.message if step.error else "no output")
                errors.append(
                    {
                        "input": source,
                        "row": row_index,
                        "step_id": step.id,
                        "message": step.error.message if step.error else "no output",
                    }
                )
                break
            outputs.append(step.outputs[0])
            row.update(status="done", output_id=step.outputs[0])
            completed.append(step.id)
    return {"completed": completed, "errors": errors, "rows": rows, "cancelled": cancel.is_set()}


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
