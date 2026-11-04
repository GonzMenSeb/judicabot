import { CLAVES_AUTO } from "./tipos";
import type { ClaveAuto, DatosAuto } from "./tipos";
import type { EdicionAuto } from "./revision";

const CAMPOS: Record<ClaveAuto, { etiqueta: string; tipo: "date" | "text" }> = {
  fecha: { etiqueta: "Fecha del auto", tipo: "date" },
  fecha_reparto: { etiqueta: "Fecha de reparto", tipo: "date" },
  accionante: { etiqueta: "Accionante", tipo: "text" },
  accionada: { etiqueta: "Accionada", tipo: "text" },
};

const ORDEN: readonly ClaveAuto[] = ["fecha", ...CLAVES_AUTO.filter((c) => c !== "fecha")];

export interface PropsFormAuto {
  base: DatosAuto;
  edicion: EdicionAuto;
  editable: boolean;
  onCambio: (clave: ClaveAuto, valor: string) => void;
}

export function FormAuto({ base, edicion, editable, onCambio }: PropsFormAuto) {
  return (
    <section class="docs-bloque" aria-labelledby="docs-auto-t">
      <h2 id="docs-auto-t">Datos del auto que asume el conocimiento</h2>
      <p class="sub">Se leyeron del expediente. Corríjalos si alguno está mal.</p>
      <div class="docs-rejilla">
        {ORDEN.map((clave) => {
          const { etiqueta, tipo } = CAMPOS[clave];
          return (
            <div class="campo" key={clave}>
              <label for={`auto-${clave}`}>{etiqueta}</label>
              <input
                id={`auto-${clave}`}
                type={tipo}
                value={edicion[clave] ?? base[clave] ?? ""}
                disabled={!editable}
                onInput={(e) => onCambio(clave, e.currentTarget.value)}
              />
            </div>
          );
        })}
      </div>
      {editable && (
        <p class="docs-ayuda">
          Si deja vacía la fecha del auto, al guardar se propone el siguiente día hábil después del reparto (sin fines de semana ni festivos).
        </p>
      )}
    </section>
  );
}
