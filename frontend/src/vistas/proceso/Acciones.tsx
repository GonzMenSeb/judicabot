import { useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { JobInicio, Proveedor, ProveedorCaso, RunCuerpo } from "../../api/contrato";
import { cargarEstadoServidor, casoActual, estadoServidor, jobActual, mostrarToast, proveedorSinClave } from "../../estado";
import { Aviso, Boton, Dialogo } from "../../ui";
import { DialogoClave } from "../documentos/DialogoClave";
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
  tope?: boolean;
  proveedor?: ProveedorCaso | null;
  alNuevoJob: (jobId: string) => void;
  alReintentar: () => void;
}

export function BloqueError({ caso, mensaje, cmd, tope = false, proveedor = null, alNuevoJob, alReintentar }: PropsError) {
  const [cargando, setCargando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  // Guarda si el intento que pidió la clave era forzado, para repetirlo igual al guardarla.
  const [pidiendoClave, setPidiendoClave] = useState<{ proveedor: Proveedor; forzar: boolean } | null>(null);

  const lanzar = async (forzar: boolean) => {
    setCargando(true);
    try {
      await cargarEstadoServidor(true);
      const sinClave = proveedorSinClave(estadoServidor.value, proveedor);
      if (sinClave) {
        setConfirmando(false);
        setPidiendoClave({ proveedor: sinClave, forzar });
        return;
      }
      const cuerpo: RunCuerpo = forzar ? { cmd: "continuar", forzar: true } : { cmd: "continuar" };
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
      setConfirmando(false);
    }
  };

  const haciaDecision = cmd === "decidir";
  return (
    <>
      <Aviso
        class="tz-aviso"
        tipo="error"
        titulo="La ejecución se detuvo"
        acciones={
          <>
            {tope ? (
              <Boton variante="primario" onClick={() => setConfirmando(true)}>
                Reintentar de todos modos
              </Boton>
            ) : (
              <Boton variante="primario" cargando={cargando} onClick={() => void lanzar(false)}>
                Continuar
              </Boton>
            )}
            {/Inteligencia artificial/.test(mensaje) && <Boton href="#/configuracion/ia">Ir a Inteligencia artificial</Boton>}
            <Boton href={`${baseCaso(caso)}/${haciaDecision ? "decision" : "documentos"}`}>
              {haciaDecision ? "Volver a la decisión" : "Volver a documentos"}
            </Boton>
          </>
        }
      >
        {mensaje}
      </Aviso>
      <Dialogo
        abierto={confirmando}
        titulo="¿Reintentar de todos modos?"
        onCerrar={() => {
          if (!cargando) setConfirmando(false);
        }}
        acciones={
          <>
            <Boton onClick={() => setConfirmando(false)} disabled={cargando}>
              Cancelar
            </Boton>
            <Boton variante="primario" cargando={cargando} onClick={() => void lanzar(true)}>
              Reintentar
            </Boton>
          </>
        }
      >
        <p>
          La IA ya falló varias veces seguidas en este paso. Un nuevo intento vuelve a enviar el expediente al proveedor y puede volver a
          cobrarse. Hágalo solo si ya corrigió la causa (por ejemplo, la clave o el modelo en Inteligencia artificial) o si el proveedor ya
          se recuperó.
        </p>
      </Dialogo>
      <DialogoClave
        abierto={pidiendoClave !== null}
        proveedor={pidiendoClave?.proveedor ?? "anthropic"}
        onCerrar={() => setPidiendoClave(null)}
        onGuardada={() => {
          const forzar = pidiendoClave?.forzar ?? false;
          setPidiendoClave(null);
          void lanzar(forzar);
        }}
      />
    </>
  );
}
