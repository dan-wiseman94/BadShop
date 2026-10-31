import { useState } from "react";
import Form from "@rjsf/core";
import { customizeValidator } from "@rjsf/validator-ajv8";
import type {
  RJSFSchema,
  UiSchema,
  WidgetProps,
  FieldProps,
} from "@rjsf/utils";
import { Crosshair, FolderOpen, Shuffle } from "lucide-react";
import type { Params, Tool, Artifact } from "../types";
import { action, run, useSession, useArtifact, imageUrl } from "../data";
import { native, pickImages } from "../native";
import { useUI } from "../store";
import { BIREFNET_MEMORY_NOTE } from "../constants";
const validator = customizeValidator({
  ajvOptionsOverrides: { strict: false },
  customFormats: {
    "badshop-image": () => true,
    "badshop-point": () => true,
    "badshop-box": () => true,
    "badshop-segment": () => true,
    "badshop-spot": () => true,
    "badshop-seed": () => true,
    color: () => true,
  },
});
export function normalizeSchema(raw: RJSFSchema): RJSFSchema {
  const schema = structuredClone(raw);
  const walk = (node: RJSFSchema) => {
    if (node.anyOf) {
      const nonNull = node.anyOf.filter(
        (s) => typeof s === "object" && s.type !== "null",
      );
      if (nonNull.length === 1 && typeof nonNull[0] === "object") {
        const { anyOf: _, ...rest } = node;
        Object.assign(node, { ...nonNull[0], ...rest });
        delete node.anyOf;
        if (node.default === null) delete node.default;
      }
    }
    if (node.prefixItems && Array.isArray(node.prefixItems)) {
      node.items = node.prefixItems as RJSFSchema[];
      delete node.prefixItems;
    }
    if (
      [
        "badshop-point",
        "badshop-box",
        "badshop-segment",
        "badshop-spot",
      ].includes(String(node.format)) &&
      Array.isArray(node.items)
    ) {
      node.items = node.items[0];
    }
    Object.values(node.properties ?? {}).forEach((value) => {
      if (typeof value === "object") walk(value);
    });
    if (Array.isArray(node.items))
      node.items.forEach((value) => {
        if (typeof value === "object") walk(value);
      });
    else if (typeof node.items === "object") walk(node.items);
    for (const branch of node.anyOf ?? [])
      if (typeof branch === "object") walk(branch);
  };
  walk(schema);
  return schema;
}
export function schemaUI(schema: RJSFSchema): UiSchema {
  const ui: UiSchema = {};
  if (schema.format === "badshop-image") ui["ui:widget"] = "ImagePicker";
  if (schema.format === "color") ui["ui:widget"] = "ColorPicker";
  if (
    [
      "badshop-point",
      "badshop-box",
      "badshop-segment",
      "badshop-spot",
    ].includes(String(schema.format))
  )
    ui["ui:field"] = "Coordinates";
  if (schema.format === "badshop-seed") ui["ui:widget"] = "Seed";
  if (
    (schema.type === "number" || schema.type === "integer") &&
    schema.minimum !== undefined &&
    schema.maximum !== undefined
  )
    ui["ui:widget"] = "range";
  for (const [name, child] of Object.entries(schema.properties ?? {}))
    if (typeof child === "object") ui[name] = schemaUI(child);
  if (typeof schema.items === "object" && !Array.isArray(schema.items))
    ui.items = schemaUI(schema.items);
  return ui;
}
function Thumbnail({ artifact }: { artifact: Artifact }) {
  const { data } = useArtifact(artifact.id, true);
  return <img src={imageUrl(data)} alt="" />;
}
export function ImagePicker({
  id,
  value,
  onChange,
  required,
  disabled,
}: WidgetProps) {
  const { data: session } = useSession();
  const selected = session?.artifacts[String(value)];
  const all = Object.values(session?.artifacts ?? {});
  const imports = all.filter(
    (artifact) => !all.some((other) => other.original_id === artifact.id),
  );
  return (
    <div className="image-picker">
      <select
        id={id}
        required={required}
        disabled={disabled}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">Choose an image…</option>
        {imports.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label} ({a.width} × {a.height})
          </option>
        ))}
      </select>
      {selected && <Thumbnail artifact={selected} />}
      <button
        type="button"
        title="Open image file"
        disabled={!native || disabled}
        onClick={() =>
          run(async () => {
            const paths = await pickImages();
            if (paths?.length) {
              const result = await action("artifacts.import", {
                path: paths[0],
              });
              onChange(result.working.id);
            }
          })
        }
      >
        <FolderOpen size={15} />
      </button>
    </div>
  );
}
function ColorPicker({ id, value, onChange, disabled }: WidgetProps) {
  const str = String(value ?? "#ffffff");
  return (
    <div className="color-picker">
      <input
        type="color"
        aria-label="Color swatch"
        value={/^#[\da-f]{6}$/i.test(str) ? str : "#ffffff"}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      <input
        id={id}
        value={str}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
function Seed({ id, value, onChange, disabled }: WidgetProps) {
  return (
    <div className="color-picker">
      <input
        id={id}
        type="number"
        value={Number(value ?? 1)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.valueAsNumber)}
      />
      <button
        type="button"
        title="New random seed"
        disabled={disabled}
        onClick={() => onChange(Math.floor(Math.random() * 2147483647))}
      >
        <Shuffle size={15} />
      </button>
    </div>
  );
}
export function Coordinates(props: FieldProps) {
  const { schema, formData, onChange, disabled, fieldPathId } = props;
  const kind =
    schema.format === "badshop-box"
      ? "box"
      : schema.format === "badshop-segment"
        ? "segment"
        : "point";
  const labels =
    kind === "box" || kind === "segment"
      ? ["X1", "Y1", "X2", "Y2"]
      : schema.format === "badshop-spot"
        ? ["X", "Y", "Radius"]
        : ["X", "Y"];
  const value = (Array.isArray(formData) ? formData : []) as number[];
  const change = (next: number[]) => onChange(next, fieldPathId.path);
  return (
    <div className="coordinate-field">
      <label>{schema.title ?? "Coordinates"}</label>
      <div className="coordinate-inputs">
        {labels.map((label, i) => (
          <label key={label}>
            {label}
            <input
              type="number"
              aria-label={`${schema.title ?? "Coordinates"} ${label}`}
              disabled={disabled}
              value={value[i] ?? ""}
              onChange={(e) => {
                const next = labels.map((_, j) => value[j] ?? 0);
                next[i] = e.target.valueAsNumber;
                change(next);
              }}
            />
          </label>
        ))}
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() =>
          useUI.getState().set({
            pick: {
              kind,
              complete: (next) =>
                change(
                  schema.format === "badshop-spot"
                    ? [...next, value[2] ?? 20]
                    : next,
                ),
            },
          })
        }
      >
        <Crosshair size={14} />
        Pick on image
      </button>
      {!props.required && value.length > 0 && (
        <button
          type="button"
          onClick={() => onChange(undefined, fieldPathId.path)}
          disabled={disabled}
        >
          Clear coordinates
        </button>
      )}
      <p className="field-description">{schema.description}</p>
    </div>
  );
}
export function ToolForm({
  tool,
  initial,
  onSubmit,
  submitLabel = "Run tool",
  disabled = false,
}: {
  tool: Tool;
  initial?: Params;
  onSubmit: (params: Params) => Promise<unknown>;
  submitLabel?: string;
  disabled?: boolean;
}) {
  const [formData, setFormData] = useState<Params>(
    Object.fromEntries(
      Object.entries(initial ?? {}).filter(([, value]) => value !== null),
    ),
  );
  const [busy, setBusy] = useState(false);
  const schema = normalizeSchema(tool.schema);
  return (
    <Form
      schema={schema}
      uiSchema={schemaUI(schema)}
      validator={validator}
      fields={{ Coordinates }}
      widgets={{ ImagePicker, ColorPicker, Seed }}
      formData={formData}
      onChange={(event) => setFormData(event.formData ?? {})}
      onSubmit={(event) =>
        run(async () => {
          setBusy(true);
          try {
            await onSubmit(event.formData ?? {});
          } finally {
            setBusy(false);
          }
        })
      }
      disabled={disabled || busy}
      showErrorList="top"
      omitExtraData
      liveOmit
      experimental_defaultFormStateBehavior={{
        arrayMinItems: { populate: "requiredOnly" },
      }}
    >
      {formData.model === "birefnet-general" && (
        <p className="model-memory-note">{BIREFNET_MEMORY_NOTE}</p>
      )}
      <button
        type="submit"
        className="primary form-run"
        disabled={disabled || busy}
      >
        {busy ? "Working…" : submitLabel}
      </button>
    </Form>
  );
}
