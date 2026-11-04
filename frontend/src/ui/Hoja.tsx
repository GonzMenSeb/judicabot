import type { ComponentChildren } from "preact";
import { cx } from "./clases";

export interface PropsHoja {
  etiqueta?: string;
  class?: string;
  children?: ComponentChildren;
}

export function Hoja({ etiqueta, class: clase, children }: PropsHoja) {
  return (
    <article class={cx("hoja", clase)} aria-label={etiqueta}>
      {children}
    </article>
  );
}
