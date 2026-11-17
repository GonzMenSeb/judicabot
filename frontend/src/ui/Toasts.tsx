import { useRef } from "preact/hooks";
import { cerrarToast, pausarToast, reanudarToast, toasts, type Toast } from "../estado/toasts";
import { cx } from "./clases";

export function Toasts() {
  return (
    <div class="toasts" role="status" aria-live="polite">
      {toasts.value.map((t) => (
        <ItemToast key={t.id} toast={t} />
      ))}
    </div>
  );
}

/** Con acción no se cierra por tiempo mientras el foco o el puntero están dentro (WCAG 2.2.1); al salir vuelve a contar. */
function ItemToast({ toast: t }: { toast: Toast }) {
  const dentro = useRef({ foco: false, puntero: false });
  const marcar = (motivo: "foco" | "puntero", si: boolean) => {
    if (!t.accion) return;
    const antes = dentro.current.foco || dentro.current.puntero;
    dentro.current[motivo] = si;
    const ahora = dentro.current.foco || dentro.current.puntero;
    if (ahora && !antes) pausarToast(t.id);
    else if (!ahora && antes) reanudarToast(t.id);
  };
  const accion = t.accion;
  return (
    <div
      class={cx("toast", t.tipo !== "info" && t.tipo)}
      onPointerEnter={() => marcar("puntero", true)}
      onPointerLeave={() => marcar("puntero", false)}
      onFocusIn={() => marcar("foco", true)}
      onFocusOut={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) marcar("foco", false);
      }}
    >
      <span>{t.texto}</span>
      {accion && (
        <button
          type="button"
          class="accion"
          onClick={(e) => {
            // El botón se va con el aviso: el foco pasa al contenido en vez de caer en <body>.
            if (document.activeElement === e.currentTarget) document.getElementById("contenido")?.focus({ preventScroll: true });
            cerrarToast(t.id);
            accion.alHacer();
          }}
        >
          {accion.texto}
        </button>
      )}
      <button type="button" aria-label="Cerrar aviso" onClick={() => cerrarToast(t.id)}>
        ×
      </button>
    </div>
  );
}
