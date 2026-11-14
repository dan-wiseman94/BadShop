import type { DocumentContext } from "./wire.generated";
import { WIRE_SCHEMAS } from "./wire.generated";
import { customizeValidator } from "@rjsf/validator-cfworker";
import type { RJSFSchema } from "@rjsf/utils";

const validator = customizeValidator({ draft: "2020-12", shortCircuit: true });
const schemas = new Map<string, RJSFSchema>();
export function validPayload(kind: "result" | "event", name: string, value: unknown): boolean {
  const key = `${kind}:${name}`;
  let schema = schemas.get(key);
  if (!schema) {
    const methods = WIRE_SCHEMAS.methods as Record<string, { result: object }>;
    const events = WIRE_SCHEMAS.events as Record<string, object>;
    const raw = kind === "event" ? events[name] : methods[name]?.result;
    if (!raw) return false;
    schema = { ...raw, $id: `urn:badshop:protocol:${key}`, $defs: WIRE_SCHEMAS.definitions } as RJSFSchema;
    schemas.set(key, schema);
  }
  const checked = validator.rawValidation(schema, value);
  return !checked.validationError && !checked.errors?.length;
}

export function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export function counter(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
export function documentContext(value: unknown): value is DocumentContext {
  return object(value) &&
    [value.core_instance_id, value.document_id, value.document_incarnation].every(
      id => typeof id === "string" && id.length > 0 && id.length <= 128,
    ) && (value.branch_id === null || typeof value.branch_id === "string") &&
    counter(value.revision) && counter(value.event_seq);
}
export function parseFrame(raw: unknown): Record<string, unknown> {
  if (typeof raw !== "string" || raw.length > 64 * 1024 * 1024)
    throw new Error("The core sent an oversized or non-text response.");
  const parsed: unknown = JSON.parse(raw);
  if (!object(parsed)) throw new Error("The core response must be an object.");
  const stack: [unknown, number][] = [[parsed, 0]];
  let nodes = 0;
  while (stack.length) {
    const [value, depth] = stack.pop()!;
    if (++nodes > 1_000_000 || depth > 64)
      throw new Error("The core response exceeds the structure limit.");
    if (typeof value === "number" && !Number.isFinite(value))
      throw new Error("The core response contains a non-finite number.");
    if (value && typeof value === "object")
      for (const child of Object.values(value)) stack.push([child, depth + 1]);
  }
  return parsed;
}
