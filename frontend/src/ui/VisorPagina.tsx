import type { ComponentChildren } from "preact";
import { cx } from "./clases";

export interface PropsVisorPagina {
  numero?: number;
  total?: number;
  class?: string;
  children?: ComponentChildren;
}

export function VisorPagina({ numero, total, class: clase, children }: PropsVisorPagina) {
  const etiqueta =
    numero === undefined ? undefined : total === undefined ? `Página ${numero}` : `Página ${numero} de ${total}`;
  return (
    <section class={cx("visor-pagina", clase)} aria-label={etiqueta}>
      <div class="visor-cuerpo">{children}</div>
      {numero !== undefined && (
        <div class="visor-num" aria-hidden="true">
          {total === undefined ? numero : `${numero} / ${total}`}
        </div>
      )}
    </section>
  );
}
