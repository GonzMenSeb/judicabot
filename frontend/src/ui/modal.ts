import type { RefObject } from "preact";
import { useEffect, useRef } from "preact/hooks";

const FOCALIZABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const CLASE_FONDO_BLOQUEADO = "dialogo-abierto";
const CLASE_CON_BARRA = "con-barra";

let abiertos = 0;

function bloquearFondo(): () => void {
  const raiz = document.documentElement;
  if (abiertos === 0) raiz.classList.toggle(CLASE_CON_BARRA, window.innerWidth > raiz.clientWidth);
  abiertos += 1;
  raiz.classList.add(CLASE_FONDO_BLOQUEADO);
  return () => {
    abiertos = Math.max(0, abiertos - 1);
    if (abiertos === 0) raiz.classList.remove(CLASE_FONDO_BLOQUEADO, CLASE_CON_BARRA);
  };
}

function focalizables(raiz: HTMLElement): HTMLElement[] {
  return Array.from(raiz.querySelectorAll<HTMLElement>(FOCALIZABLE)).filter((e) => !e.closest("[hidden]") && e.closest("dialog") === raiz);
}

export function useModal(ref: RefObject<HTMLDialogElement>, abierto: boolean, onCerrar: () => void, retorno?: string): void {
  const cerrar = useRef(onCerrar);
  cerrar.current = onCerrar;
  const destino = useRef(retorno);
  destino.current = retorno;

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
      if (e.target instanceof Element && e.target.closest("dialog") !== dialogo) return;
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
      const elegido = destino.current ? document.querySelector<HTMLElement>(destino.current) : null;
      const foco = elegido ?? previo;
      if (foco?.isConnected) foco.focus();
    };
  }, [abierto]);
}
