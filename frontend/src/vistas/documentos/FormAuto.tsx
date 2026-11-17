import { CLAVES_AUTO } from "./tipos";
import type { ClaveAuto, DatosAuto } from "./tipos";
import type { TerminoRespuesta } from "../../api/contrato";
import { FormTermino } from "./FormTermino";
import type { CampoTermino } from "./FormTermino";
import type { EdicionAuto } from "./revision";
import type { EdicionTermino } from "./termino";

const CAMPOS: Record<ClaveAuto, { etiqueta: string; tipo: "date" | "text" }> = {
  fecha: { etiqueta: "Fecha del auto", tipo: "date" },
  fecha_reparto: { etiqueta: "Fecha de reparto", tipo: "date" },
  accionante: { etiqueta: "Accionante", tipo: "text" },
  accionada: { etiqueta: "Accionada", tipo: "text" },
  firmante: { etiqueta: "Firmante", tipo: "text" },
  cargo_firmante: { etiqueta: "Cargo del firmante", tipo: "text" },
};

const ORDEN: readonly ClaveAuto[] = ["fecha", ...CLAVES_AUTO.filter((c) => c !== "fecha")];

export interface PropsFormAuto {
  base: DatosAuto;
  edicion: EdicionAuto;
  editable: boolean;
  onCambio: (clave: ClaveAuto, valor: string) => void;
  /** El término para fallar; null si no se pudo leer (entonces no se muestra el grupo). */
  termino?: TerminoRespuesta | null;
  edicionTermino?: EdicionTermino;
  onCambioTermino?: (campo: CampoTermino, valor: string) => void;
  /** El término se puede editar aunque el resto del formulario no (caso ya redactado, salvo terminado o en curso). */
  terminoEditable?: boolean;
  onGuardarTermino?: () => void;
  guardandoTermino?: boolean;
}

export function FormAuto({ base, edicion, editable, onCambio, termino = null, edicionTermino = {}, onCambioTermino = () => {}, terminoEditable = editable, onGuardarTermino, guardandoTermino }: PropsFormAuto) {
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
      {termino && (
        <FormTermino
          respuesta={termino}
          edicion={edicionTermino}
          editable={terminoEditable}
          onCambio={onCambioTermino}
          onGuardar={editable ? undefined : onGuardarTermino}
          guardando={guardandoTermino}
        />
      )}
      {editable && (
        <>
          <p class="docs-ayuda">
            Si deja vacía la fecha del auto, al guardar se propone el siguiente día hábil después del reparto (sin fines de semana ni festivos).
          </p>
          <p class="docs-ayuda">Si deja vacíos el firmante y su cargo, el auto sale firmado por el juez y el cargo configurados para el despacho.</p>
        </>
      )}
    </section>
  );
}
