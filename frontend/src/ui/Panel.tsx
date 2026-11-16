import type { ComponentChildren } from "preact";
import { useEffect, useId, useRef } from "preact/hooks";
import { cx } from "./clases";
import { useModal } from "./modal";
import { Toasts } from "./Toasts";

export interface ItemPanel {
  href: string;
  texto: string;
  detalle?: ComponentChildren;
  actual?: boolean;
}

export interface PropsPanel {
  abierto: boolean;
  titulo: string;
  items: ItemPanel[];
  encabezado: string;
  onCerrar: () => void;
  retorno?: string;
  class?: string;
  children?: ComponentChildren;
}

const enMinuscula = (texto: string) => texto.charAt(0).toLowerCase() + texto.slice(1);

export function Panel({ abierto, titulo, items, encabezado, onCerrar, retorno, class: clase, children }: PropsPanel) {
  const ref = useRef<HTMLDialogElement>(null);
  const contenido = useRef<HTMLDivElement>(null);
  const desdeFondo = useRef(false);
  const idTitulo = useId();
  useModal(ref, abierto, onCerrar, retorno);

  useEffect(() => {
    if (contenido.current) contenido.current.scrollTop = 0;
  }, [encabezado]);

  return (
    <dialog
      ref={ref}
      class={cx("panel", clase)}
      aria-labelledby={idTitulo}
      tabIndex={-1}
      onMouseDown={(e) => {
        desdeFondo.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (desdeFondo.current && e.target === e.currentTarget) onCerrar();
        desdeFondo.current = false;
      }}
    >
      {abierto && (
        <div class="panel-caja">
          <p class="panel-titulo" id={idTitulo}>
            {titulo}
          </p>
          <nav class="panel-nav" aria-label={`Secciones de ${enMinuscula(titulo)}`}>
            <ul>
              {items.map((item) => (
                <li key={item.href}>
                  <a href={item.href} aria-current={item.actual ? "page" : undefined} data-enfoque={item.actual ? "" : undefined}>
                    <span>{item.texto}</span> {item.detalle && <small>{item.detalle}</small>}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <h1 class="panel-encabezado">{encabezado}</h1>
          <button type="button" class="panel-cerrar" aria-label={`Cerrar ${enMinuscula(titulo)}`} onClick={onCerrar}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
          <div class="panel-contenido" ref={contenido}>
            {children}
          </div>
          <Toasts />
        </div>
      )}
    </dialog>
  );
}
