import type { ComponentChildren } from "preact";
import { useEffect, useId, useRef } from "preact/hooks";
import { cx } from "./clases";

const FOCALIZABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const CLASE_FONDO_BLOQUEADO = "dialogo-abierto";

let abiertos = 0;

function bloquearFondo(): () => void {
  abiertos += 1;
  document.documentElement.classList.add(CLASE_FONDO_BLOQUEADO);
  return () => {
    abiertos = Math.max(0, abiertos - 1);
    if (abiertos === 0) document.documentElement.classList.remove(CLASE_FONDO_BLOQUEADO);
  };
}

export interface PropsDialogo {
  abierto: boolean;
  titulo: string;
  onCerrar: () => void;
  acciones?: ComponentChildren;
  class?: string;
  children?: ComponentChildren;
}

function focalizables(raiz: HTMLElement): HTMLElement[] {
  return Array.from(raiz.querySelectorAll<HTMLElement>(FOCALIZABLE)).filter((e) => !e.closest("[hidden]"));
}

export function Dialogo({ abierto, titulo, onCerrar, acciones, class: clase, children }: PropsDialogo) {
  const ref = useRef<HTMLDialogElement>(null);
  const idTitulo = useId();
  const cerrar = useRef(onCerrar);
  cerrar.current = onCerrar;

  useEffect(() => {
    const dialogo = ref.current;
    if (!dialogo || !abierto) return;
    const previo = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
    if (typeof dialogo.showModal === "function") {
      if (!dialogo.open) dialogo.showModal();
    } else {
      dialogo.setAttribute("open", "");
    }
    const soltarFondo = bloquearFondo();
    const inicial = dialogo.querySelector<HTMLElement>("[autofocus], [data-enfoque]") ?? focalizables(dialogo)[0];
    (inicial ?? dialogo).focus();

    const alTeclear = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cerrar.current();
        return;
      }
      if (e.key !== "Tab") return;
      const lista = focalizables(dialogo);
      const primero = lista[0];
      const ultimo = lista[lista.length - 1];
      if (!primero || !ultimo) {
        e.preventDefault();
        dialogo.focus();
        return;
      }
      const activo = document.activeElement;
      if (e.shiftKey && (activo === primero || activo === dialogo)) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && activo === ultimo) {
        e.preventDefault();
        primero.focus();
      }
    };
    const alCancelar = (e: Event) => {
      e.preventDefault();
      cerrar.current();
    };
    dialogo.addEventListener("keydown", alTeclear);
    dialogo.addEventListener("cancel", alCancelar);
    return () => {
      dialogo.removeEventListener("keydown", alTeclear);
      dialogo.removeEventListener("cancel", alCancelar);
      if (typeof dialogo.close === "function") {
        if (dialogo.open) dialogo.close();
      } else {
        dialogo.removeAttribute("open");
      }
      soltarFondo();
      if (previo?.isConnected) previo.focus();
    };
  }, [abierto]);

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
