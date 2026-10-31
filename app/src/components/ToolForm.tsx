import { useEffect, useRef, useState } from "react";
import Form from "@rjsf/core";
import { customizeValidator } from "@rjsf/validator-ajv8";
import type {
  RJSFSchema,
  UiSchema,
  WidgetProps,
  FieldProps,
  IconButtonProps,
} from "@rjsf/utils";
import {
  Crosshair,
  FolderOpen,
  Shuffle,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  Copy,
  X,
} from "lucide-react";
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
  let swatch = /^#[\da-f]{6}$/i.test(str) ? str : "#ffffff";
  if (typeof CanvasRenderingContext2D !== "undefined") {
    const ctx = document.createElement("canvas").getContext("2d");
    if (ctx) {
      ctx.fillStyle = "#ffffff";
      ctx.fillStyle = str;
      const normalized = ctx.fillStyle;
      if (/^#[\da-f]{6}$/i.test(normalized)) swatch = normalized;
      else {
        const channels = normalized.match(/[\d.]+/g)?.slice(0, 3);
        if (channels?.length === 3)
          swatch =
            "#" +
            channels
              .map((channel) =>
                Math.round(Number(channel)).toString(16).padStart(2, "0"),
              )
              .join("");
      }
    }
  }
  return (
    <div className="color-picker">
      <input
        type="color"
        aria-label="Color swatch"
        value={swatch}
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
interface ToolFormContext {
  coordinateImageId: string | null;
  coordinateImageLabel?: string;
}
function cleanParams(params: Params = {}) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== null && value !== undefined,
    ),
  );
}
/** Refresh unchanged fields after replay; retain draft edits and identify real conflicts. */
export function mergeParameterDraft(
  draft: Params,
  baseline: Params,
  current: Params,
) {
  const data: Params = {};
  const conflicts: string[] = [];
  const equal = (a: unknown, b: unknown) =>
    JSON.stringify(a) === JSON.stringify(b);
  for (const key of new Set([
    ...Object.keys(baseline),
    ...Object.keys(draft),
    ...Object.keys(current),
  ])) {
    const edited = !equal(draft[key], baseline[key]);
    const changed = !equal(current[key], baseline[key]);
    const value = edited ? draft[key] : current[key];
    if (value !== undefined) data[key] = value;
    if (edited && changed && !equal(draft[key], current[key]))
      conflicts.push(key);
  }
  return { data, conflicts };
}
export function Coordinates(props: FieldProps) {
  const { schema, formData, onChange, disabled, fieldPathId } = props;
  const context = props.registry?.formContext as ToolFormContext | undefined;
  const targetImage = context?.coordinateImageId;
  const path = fieldPathId.path;
  const itemIndex = path
    .map((part) => typeof part === "number")
    .lastIndexOf(true);
  const title =
    schema.title ??
    (itemIndex >= 0
      ? `${String(path[itemIndex - 1]).replaceAll("_", " ")} ${Number(path[itemIndex]) + 1}`
      : "Coordinates");
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
      <label>{title}</label>
      <div className="coordinate-inputs">
        {labels.map((label, i) => (
          <label key={label}>
            {label}
            <input
              type="number"
              aria-label={`${title} ${label}`}
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
        disabled={disabled || !targetImage}
        onClick={() =>
          targetImage &&
          useUI.getState().set({
            pick: {
              kind,
              artifactId: targetImage,
              label: context?.coordinateImageLabel,
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
      {!targetImage && (
        <p className="field-description">
          Choose an input image to pick coordinates.
        </p>
      )}
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
function ArrayAction({
  kind,
  id,
  onClick,
  disabled,
}: {
  kind: "add" | "remove" | "up" | "down" | "copy" | "clear";
} & IconButtonProps) {
  const Icon = {
    add: Plus,
    remove: Trash2,
    up: ArrowUp,
    down: ArrowDown,
    copy: Copy,
    clear: X,
  }[kind];
  const label = {
    add: "Add item",
    remove: "Remove item",
    up: "Move item up",
    down: "Move item down",
    copy: "Copy item",
    clear: "Clear item",
  }[kind];
  return (
    <button
      type="button"
      id={id}
      className="array-action"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon size={14} />
      {kind === "add" && label}
    </button>
  );
}
const arrayButtons = {
  AddButton: (props: IconButtonProps) => <ArrayAction {...props} kind="add" />,
  RemoveButton: (props: IconButtonProps) => (
    <ArrayAction {...props} kind="remove" />
  ),
  MoveUpButton: (props: IconButtonProps) => (
    <ArrayAction {...props} kind="up" />
  ),
  MoveDownButton: (props: IconButtonProps) => (
    <ArrayAction {...props} kind="down" />
  ),
  CopyButton: (props: IconButtonProps) => (
    <ArrayAction {...props} kind="copy" />
  ),
  ClearButton: (props: IconButtonProps) => (
    <ArrayAction {...props} kind="clear" />
  ),
};
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
  const [formData, setFormData] = useState<Params>(() => cleanParams(initial));
  const baseline = useRef(cleanParams(initial));
  const initialSignature = JSON.stringify(cleanParams(initial));
  const baselineSignature = useRef(initialSignature);
  const source = useRef({
    data: cleanParams(initial),
    signature: initialSignature,
  });
  source.current = { data: cleanParams(initial), signature: initialSignature };
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  useEffect(() => {
    if (initialSignature === baselineSignature.current || submitting.current)
      return;
    const merged = mergeParameterDraft(
      formData,
      baseline.current,
      source.current.data,
    );
    setFormData(merged.data);
    setConflicts((previous) => [
      ...new Set([
        ...previous.filter(
          (key) =>
            JSON.stringify(merged.data[key]) !==
            JSON.stringify(source.current.data[key]),
        ),
        ...merged.conflicts,
      ]),
    ]);
    baseline.current = source.current.data;
    baselineSignature.current = initialSignature;
  }, [initialSignature, busy]);
  const schema = normalizeSchema(tool.schema);
  const { data: session } = useSession();
  const imageFields = Object.entries(schema.properties ?? {}).filter(
    ([, field]) =>
      typeof field === "object" &&
      (field.format === "badshop-image" ||
        (typeof field.items === "object" &&
          !Array.isArray(field.items) &&
          field.items.format === "badshop-image")),
  );
  const imageField = tool.name === "paste" ? "base" : imageFields[0]?.[0];
  const imageValue = imageField ? formData[imageField] : undefined;
  const reference = Array.isArray(imageValue) ? imageValue[0] : imageValue;
  const artifact =
    typeof reference === "string" ? session?.artifacts[reference] : undefined;
  const context: ToolFormContext = {
    coordinateImageId: artifact?.id ?? null,
    coordinateImageLabel: artifact?.label,
  };
  return (
    <Form
      schema={schema}
      uiSchema={schemaUI(schema)}
      validator={validator}
      fields={{ Coordinates }}
      formContext={context}
      widgets={{ ImagePicker, ColorPicker, Seed }}
      templates={{ ButtonTemplates: arrayButtons }}
      formData={formData}
      onChange={(event) => setFormData(event.formData ?? {})}
      onSubmit={(event) =>
        run(async () => {
          setBusy(true);
          submitting.current = true;
          const submitted = event.formData ?? {};
          const previousSource = source.current.signature;
          try {
            await onSubmit(submitted);
            setFormData(
              source.current.signature !== previousSource
                ? source.current.data
                : submitted,
            );
            baseline.current = source.current.data;
            baselineSignature.current = source.current.signature;
            setConflicts([]);
          } finally {
            submitting.current = false;
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
      {!!conflicts.length && (
        <div className="parameter-conflict" role="alert">
          <p>
            This step changed during replay. Your edits to{" "}
            {conflicts.join(", ")} are preserved. Choose which values to use
            before applying.
          </p>
          <div>
            <button
              type="button"
              onClick={() => {
                setFormData(source.current.data);
                setConflicts([]);
              }}
            >
              Use current parameters
            </button>
            <button type="button" onClick={() => setConflicts([])}>
              Keep my edits
            </button>
          </div>
        </div>
      )}
      {formData.model === "birefnet-general" && (
        <p className="model-memory-note">{BIREFNET_MEMORY_NOTE}</p>
      )}
      <button
        type="submit"
        className="primary form-run"
        disabled={disabled || busy || conflicts.length > 0}
      >
        {busy ? "Working…" : submitLabel}
      </button>
    </Form>
  );
}
