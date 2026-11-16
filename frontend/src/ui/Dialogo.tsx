import type { ComponentChildren } from "preact";
import { useId, useRef } from "preact/hooks";
import { cx } from "./clases";
import { useModal } from "./modal";

export { CLASE_FONDO_BLOQUEADO } from "./modal";

export interface PropsDialogo {
  abierto: boolean;
  titulo: string;
  onCerrar: () => void;
  acciones?: ComponentChildren;
  class?: string;
  children?: ComponentChildren;
}

export function Dialogo({ abierto, titulo, onCerrar, acciones, class: clase, children }: PropsDialogo) {
  const ref = useRef<HTMLDialogElement>(null);
  const idTitulo = useId();
  useModal(ref, abierto, onCerrar);

  return (
    <dialog
      ref={ref}
      class={cx("dialogo", clase)}
      aria-labelledby={idTitulo}
      tabIndex={-1}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCerrar();
      }}
    >
      {abierto && (
        <div class="dialogo-cuerpo">
          <h2 id={idTitulo}>{titulo}</h2>
          {children}
          {acciones && <div class="acciones">{acciones}</div>}
        </div>
      )}
    </dialog>
  );
}
