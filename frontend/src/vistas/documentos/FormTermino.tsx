import { Boton, Chip } from "../../ui";
import type { TerminoRespuesta, UnidadTermino } from "../../api/contrato";
import { DIAS_MAXIMO, errorTermino, fechaLarga, terminoEditado, textoRestantes, valoresTermino } from "./termino";
import type { EdicionTermino } from "./termino";

export type CampoTermino = keyof EdicionTermino;

export interface PropsFormTermino {
  respuesta: TerminoRespuesta;
  edicion: EdicionTermino;
  editable: boolean;
  onCambio: (campo: CampoTermino, valor: string) => void;
  /** Guarda solo el término; se pasa cuando la barra de abajo no ofrece guardar (el caso ya no está en revisión). */
  onGuardar?: () => void;
  guardando?: boolean;
}

export function FormTermino({ respuesta, edicion, editable, onCambio, onGuardar, guardando = false }: PropsFormTermino) {
  const base = respuesta.termino;
  const valores = valoresTermino(base, edicion);
  const editado = terminoEditado(base, edicion);
  const error = editado ? errorTermino(valores) : null;
  const faltaInicio = error !== null && !valores.inicio;
  const faltaDias = error !== null && !faltaInicio;
  const vence = !editado && respuesta.vence ? fechaLarga(respuesta.vence) : null;
  const restantes = vence ? textoRestantes(respuesta) : null;
  return (
    <fieldset class="docs-termino">
      <legend>
        Término para fallar {respuesta.por_defecto && !editado && <Chip tono="info">por defecto</Chip>}
      </legend>
      <div class="docs-rejilla">
        <div class="campo">
          <label for="termino-inicio">Recibido el</label>
          <input
            id="termino-inicio"
            type="date"
            value={valores.inicio}
            disabled={!editable}
            aria-invalid={faltaInicio || undefined}
            aria-describedby={faltaInicio ? "termino-error" : undefined}
            onInput={(e) => onCambio("inicio", e.currentTarget.value)}
          />
        </div>
        <div class="campo">
          <label for="termino-dias">Plazo (días)</label>
          <input
            id="termino-dias"
            type="number"
            inputMode="numeric"
            min={1}
            max={DIAS_MAXIMO}
            step={1}
            value={valores.dias}
            disabled={!editable}
            aria-invalid={faltaDias || undefined}
            aria-describedby={faltaDias ? "termino-error" : undefined}
            onInput={(e) => onCambio("dias", e.currentTarget.value)}
          />
        </div>
        <div class="campo">
          <label for="termino-unidad">Se cuentan en días</label>
          <select
            id="termino-unidad"
            value={valores.unidad}
            disabled={!editable}
            onChange={(e) => onCambio("unidad", e.currentTarget.value as UnidadTermino)}
          >
            <option value="habiles">hábiles</option>
            <option value="calendario">calendario</option>
          </select>
        </div>
      </div>
      {error && (
        <p id="termino-error" class="docs-ayuda docs-error">
          {error}
        </p>
      )}
      {vence && (
        <p class="docs-vence">
          <b>Vence el {vence}</b>
          {restantes && ` · ${restantes}`}
        </p>
      )}
      {!base && !editado && <p class="docs-ayuda">Sin fecha de reparto no se puede calcular el plazo.</p>}
      {editado && !error && editable && <p class="docs-ayuda">El vencimiento se calcula al guardar.</p>}
      {onGuardar && editable && editado && (
        <Boton onClick={onGuardar} cargando={guardando} disabled={error !== null}>
          Guardar término
        </Boton>
      )}
      {respuesta.por_defecto && !editado && editable && (
        <p class="docs-ayuda">Propuesto desde la fecha de reparto. Si no es el plazo del despacho, cámbielo y guarde.</p>
      )}
    </fieldset>
  );
}
