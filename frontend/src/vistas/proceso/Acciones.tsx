import { useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { JobInicio, RunCuerpo } from "../../api/contrato";
import { casoActual, jobActual, mostrarToast } from "../../estado";
import { Aviso, Boton } from "../../ui";
import type { EstadoCaso } from "./tipos";

export const baseCaso = (caso: string) => `#/segunda/${encodeURIComponent(caso)}`;

export function AccionFinal({ caso, estado }: { caso: string; estado: EstadoCaso["estado"] }) {
  if (estado === "esperando_decision") {
    return (
      <div class="tz-fin" role="status">
        <b>El borrador está listo. Faltan sus decisiones.</b>
        <Boton variante="sello" grande href={`${baseCaso(caso)}/borrador`}>
          Ver el borrador
        </Boton>
      </div>
    );
  }
  if (estado === "terminado") {
    return (
      <div class="tz-fin" role="status">
        <b>El fallo y los documentos están listos.</b>
        <Boton variante="primario" grande href={`${baseCaso(caso)}/fallo`}>
          Ver el fallo
        </Boton>
      </div>
    );
  }
  return null;
}

interface PropsError {
  caso: string;
  mensaje: string;
  cmd: string | null;
  alNuevoJob: (jobId: string) => void;
  alReintentar: () => void;
}

export function BloqueError({ caso, mensaje, cmd, alNuevoJob, alReintentar }: PropsError) {
  const [cargando, setCargando] = useState(false);

  const continuar = async () => {
    setCargando(true);
    try {
      const cuerpo: RunCuerpo = { cmd: "continuar" };
      const { job_id } = await api.post<JobInicio>(`/api/casos/${encodeURIComponent(caso)}/run`, cuerpo);
      casoActual.value = caso;
      jobActual.value = job_id;
      alNuevoJob(job_id);
    } catch (error) {
      if (error instanceof ErrorApi && error.estado === 409) {
        mostrarToast("Ya hay una ejecución en curso para este caso.", { tipo: "alerta" });
        alReintentar();
      } else {
        mostrarToast(error instanceof Error ? error.message : "No se pudo continuar la ejecución.", { tipo: "error" });
      }
    } finally {
      setCargando(false);
    }
  };

  const haciaDecision = cmd === "decidir";
  return (
    <Aviso
      class="tz-aviso"
      tipo="error"
      titulo="La ejecución se detuvo"
      acciones={
        <>
          <Boton variante="primario" cargando={cargando} onClick={() => void continuar()}>
            Continuar
          </Boton>
          <Boton href={`${baseCaso(caso)}/${haciaDecision ? "decision" : "documentos"}`}>
            {haciaDecision ? "Volver a la decisión" : "Volver a documentos"}
          </Boton>
        </>
      }
    >
      {mensaje}
    </Aviso>
  );
}
