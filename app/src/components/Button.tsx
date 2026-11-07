import type { ComponentProps, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

type Props = ComponentProps<"button"> & {
  label?: ReactNode;
  icon?: LucideIcon;
  iconSize?: number;
};

/** Keep the icon before the visible label; native button semantics and events pass through. */
export function Button({ label, icon: Icon, iconSize, children, ...button }: Props) {
  return (
    <button {...button}>
      {Icon && <Icon size={iconSize} />}
      {label}
      {children}
    </button>
  );
}
