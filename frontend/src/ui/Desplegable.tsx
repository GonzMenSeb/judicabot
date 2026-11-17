import type { ComponentChildren } from "preact";
import { useEffect, useId, useLayoutEffect, useRef } from "preact/hooks";
import { cx } from "./clases";
import { bloquearFondo } from "./modal";

export interface PropsDesplegable {
  etiqueta: ComponentChildren;
  titulo: string;
  abierto: boolean;
  onAbrir: () => void;
  onCerrar: () => void;
  activo?: boolean;
  claseBoton?: string;
  ancho?: boolean;
  pie?: ComponentChildren;
  "aria-label"?: string;
  children?: ComponentChildren;
}

const FOCALIZABLE =
  'a[href], button:not([disabled]):not([data-cerrar]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const MOVIL = "(max-width: 960px)";

const esMovil = () => typeof window.matchMedia === "function" && window.matchMedia(MOVIL).matches;

export function Desplegable({ etiqueta, titulo, abierto, onAbrir, onCerrar, activo, claseBoton, ancho, pie, children, "aria-label": etiquetaAria }: PropsDesplegable) {
  const id = useId();
  const raiz = useRef<HTMLSpanElement>(null);
  const boton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = panel.current;
    if (!abierto || !el) return;
    el.classList.remove("derecha");
    if (!esMovil() && el.getBoundingClientRect().right > window.innerWidth - 8) el.classList.add("derecha");
  }, [abierto]);

  useEffect(() => {
    if (!abierto) return;
    const el = panel.current;
    const inicial = el?.querySelector<HTMLElement>(FOCALIZABLE) ?? el;
    inicial?.focus();
    const liberar = esMovil() ? bloquearFondo() : undefined;
    return () => {
      liberar?.();
      // Cerrado desde dentro (p. ej. «Listo»): el foco quedó en un nodo que ya no existe.
      if (document.activeElement === document.body) boton.current?.focus();
    };
  }, [abierto]);

  const cerrar = (devolverFoco: boolean) => {
    onCerrar();
    if (devolverFoco) boton.current?.focus();
  };

  const alTeclear = (e: KeyboardEvent) => {
    if (!abierto || e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    cerrar(true);
  };

  const alSalirFoco = (e: FocusEvent) => {
    const destino = e.relatedTarget;
    if (abierto && destino instanceof Node && !raiz.current?.contains(destino)) onCerrar();
  };

  return (
    <span class="desplegable" ref={raiz} onKeyDown={alTeclear} onFocusOut={alSalirFoco}>
      <button
        type="button"
        ref={boton}
        class={cx("desplegable-boton", activo && "activo", claseBoton)}
        aria-expanded={abierto}
        aria-haspopup="dialog"
        aria-controls={id}
        aria-label={etiquetaAria}
        onClick={abierto ? () => onCerrar() : onAbrir}
      >
        {etiqueta}
      </button>
      {abierto && (
        <>
          <button type="button" class="desplegable-velo" tabIndex={-1} aria-hidden="true" onClick={() => cerrar(true)} />
          <div id={id} ref={panel} class={cx("desplegable-panel", ancho && "ancho")} role="dialog" aria-label={titulo} tabIndex={-1}>
            <div class="desplegable-cab">
              <b>{titulo}</b>
              <button type="button" data-cerrar class="desplegable-x" aria-label="Cerrar" onClick={() => cerrar(true)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
            <div class="desplegable-cuerpo">{children}</div>
            {pie && <div class="desplegable-pie">{pie}</div>}
          </div>
        </>
      )}
    </span>
  );
}
