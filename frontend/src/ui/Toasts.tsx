import { cerrarToast, toasts } from "../estado/toasts";
import { cx } from "./clases";

export function Toasts() {
  return (
    <div class="toasts" role="status" aria-live="polite">
      {toasts.value.map((t) => (
        <div key={t.id} class={cx("toast", t.tipo !== "info" && t.tipo)}>
          <span>{t.texto}</span>
          <button type="button" aria-label="Cerrar aviso" onClick={() => cerrarToast(t.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
