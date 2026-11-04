import { useEffect, useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { JobInicio } from "../../api/contrato";
import { Aviso, Boton, Dialogo } from "../../ui";
import type { CorreccionCuerpo } from "./tipos";

type Accion = CorreccionCuerpo["decision"]["accion"];

const OPCIONES: { valor: Accion; titulo: string; detalle: string }[] = [
  {
    valor: "rehacer_apertura",
    titulo: "Rehacer la apertura",
    detalle: "Asunto, antecedentes, sentencia impugnada e impugnación. Después se rehacen también las consideraciones.",
  },
  {
    valor: "rehacer_consideraciones",
    titulo: "Rehacer las consideraciones",
    detalle: "Solo la sección V. La apertura se conserva.",
  },
];

export interface PropsDialogoCorrecciones {
  abierto: boolean;
  caso: string;
  onCerrar: () => void;
  onEnviado: (jobId: string) => void;
}

export function DialogoCorrecciones({ abierto, caso, onCerrar, onEnviado }: PropsDialogoCorrecciones) {
  const [accion, setAccion] = useState<Accion | null>(null);
  const [instruccion, setInstruccion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [intentado, setIntentado] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!abierto) return;
    setAccion(null);
    setInstruccion("");
    setEnviando(false);
    setIntentado(false);
    setError(null);
  }, [abierto]);

  const faltaInstruccion = instruccion.trim() === "";
  const faltaAccion = accion === null;

  async function enviar() {
    setIntentado(true);
    if (accion === null) {
      document.querySelector<HTMLElement>('input[name="bor-accion"]')?.focus();
      return;
    }
    if (faltaInstruccion) {
      document.getElementById("bor-instruccion")?.focus();
      return;
    }
    setEnviando(true);
    setError(null);
    const cuerpo: CorreccionCuerpo = { cmd: "decidir", decision: { accion, instruccion: instruccion.trim() } };
    try {
      const { job_id } = await api.post<JobInicio>(`/api/casos/${encodeURIComponent(caso)}/run`, cuerpo);
      onEnviado(job_id);
    } catch (e) {
      setEnviando(false);
      setError(e instanceof ErrorApi ? e.message : "No se pudo enviar la solicitud. Revise la conexión e intente de nuevo.");
    }
  }

  return (
    <Dialogo
      abierto={abierto}
      titulo="Pedir correcciones al borrador"
      onCerrar={() => {
        if (!enviando) onCerrar();
      }}
      class="bor-dialogo"
      acciones={
        <>
          <Boton onClick={onCerrar} disabled={enviando}>
            Cancelar
          </Boton>
          <Boton variante="primario" cargando={enviando} onClick={() => void enviar()}>
            Rehacer
          </Boton>
        </>
      }
    >
      <p class="sub bor-dialogo-intro">El modelo vuelve a redactar la parte que elija, siguiendo su instrucción.</p>
      <fieldset class="bor-opciones" aria-describedby={intentado && faltaAccion ? "bor-err-accion" : undefined}>
        <legend>¿Qué parte quiere rehacer?</legend>
        {OPCIONES.map((o) => (
          <label key={o.valor} class="bor-opcion">
            <input type="radio" name="bor-accion" checked={accion === o.valor} onChange={() => setAccion(o.valor)} />
            <span>
              <b>{o.titulo}</b>
              <small>{o.detalle}</small>
            </span>
          </label>
        ))}
        {intentado && faltaAccion && (
          <p id="bor-err-accion" class="bor-error" role="alert">
            Elija qué parte rehacer.
          </p>
        )}
      </fieldset>
      <div class="campo">
        <label for="bor-instruccion">Qué debe corregir</label>
        <textarea
          id="bor-instruccion"
          data-enfoque
          rows={4}
          value={instruccion}
          placeholder="Por ejemplo: el a quo declaró improcedente, no negó."
          aria-required="true"
          aria-invalid={intentado && faltaInstruccion ? "true" : undefined}
          aria-describedby={intentado && faltaInstruccion ? "bor-err-instruccion" : undefined}
          onInput={(e) => setInstruccion(e.currentTarget.value)}
        />
        {intentado && faltaInstruccion && (
          <p id="bor-err-instruccion" class="bor-error" role="alert">
            Escriba la instrucción: sin ella el modelo no sabe qué corregir.
          </p>
        )}
      </div>
      {error && (
        <Aviso tipo="error" class="bor-dialogo-error">
          {error}
        </Aviso>
      )}
    </Dialogo>
  );
}
