import type { ComponentChildren } from "preact";
import { cx } from "./clases";

export type TonoChip = "neutro" | "ok" | "alerta" | "mal" | "info" | "sello";

export interface PropsChip {
  tono?: TonoChip;
  title?: string;
  class?: string;
  children?: ComponentChildren;
}

export function Chip({ tono = "neutro", title, class: clase, children }: PropsChip) {
  return (
    <span class={cx("chip", tono !== "neutro" && tono, clase)} title={title}>
      {children}
    </span>
  );
}
