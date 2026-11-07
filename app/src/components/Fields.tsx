import type { ComponentProps, ReactNode } from "react";

type Label = { label: ReactNode; labelClassName?: string; inputFirst?: boolean };
type Binding<T> = readonly [T, (value: T) => void];

function FieldLabel({ label, labelClassName, inputFirst, children }: Label & { children: ReactNode }) {
  return (
    <label className={labelClassName}>
      {inputFirst && children}
      {label}
      {!inputFirst && children}
    </label>
  );
}

export function InputField<T extends string | number | boolean>({
  label,
  labelClassName,
  inputFirst,
  bind,
  ...input
}: Label & ComponentProps<"input"> & { bind?: Binding<T> }) {
  const bound = bind
    ? {
        ...(typeof bind[0] === "boolean" ? { checked: bind[0] } : { value: bind[0] }),
        onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
          bind[1](
            (typeof bind[0] === "boolean"
              ? event.target.checked
              : typeof bind[0] === "number"
                ? Number(event.target.value)
                : event.target.value) as T,
          ),
      }
    : {};
  return (
    <FieldLabel {...{ label, labelClassName, inputFirst }}>
      <input {...input} {...bound} />
    </FieldLabel>
  );
}

export function TextAreaField({
  label,
  labelClassName,
  inputFirst,
  bind,
  ...input
}: Label & ComponentProps<"textarea"> & { bind?: Binding<string> }) {
  return (
    <FieldLabel {...{ label, labelClassName, inputFirst }}>
      <textarea {...input} {...(bind ? { value: bind[0], onChange: (e) => bind[1](e.target.value) } : {})} />
    </FieldLabel>
  );
}

export function SelectField<T extends string>({
  label,
  labelClassName,
  inputFirst,
  children,
  bind,
  options,
  ...input
}: Label &
  ComponentProps<"select"> & {
    bind?: Binding<T>;
    options?: readonly (string | readonly [string, ReactNode])[];
  }) {
  return (
    <FieldLabel {...{ label, labelClassName, inputFirst }}>
      <select {...input} {...(bind ? { value: bind[0], onChange: (e) => bind[1](e.target.value as T) } : {})}>
        {children}
        {options?.map((option) =>
          typeof option === "string" ? (
            <option key={option}>{option}</option>
          ) : (
            <option key={option[0]} value={option[0]}>
              {option[1]}
            </option>
          ),
        )}
      </select>
    </FieldLabel>
  );
}
