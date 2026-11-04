import { Boton, Chip } from "../../ui";
import type { TonoChip } from "../../ui";
import { nombreArchivo, urlSalida, urlZip } from "./datos";
import type { AvisosFallo, EstadoCaso, GrupoSalidas } from "./tipos";

interface Props {
  caso: string;
  principal: string | null;
  grupos: GrupoSalidas[];
  avisos: AvisosFallo;
  estado: EstadoCaso | null;
}

const ETIQUETA_ESTADO: Record<EstadoCaso["estado"], string> = {
  sin_iniciar: "Caso sin iniciar",
  revision: "Documentos en revisión",
  incompleto: "Documentos incompletos",
  esperando_decision: "Esperando su decisión",
  terminado: "Fallo generado",
  error: "Proceso con error",
};

function estadoChip(estado: EstadoCaso | null): { tono: TonoChip; texto: string } {
  if (!estado || (estado.estado === "terminado" && !estado.job_activo)) return { tono: "ok", texto: "Fallo generado" };
  if (estado.job_activo) return { tono: "info", texto: "Proceso en curso" };
  return { tono: estado.estado === "error" ? "mal" : "alerta", texto: ETIQUETA_ESTADO[estado.estado] };
}

export function Descargas({ caso, principal, grupos, avisos, estado }: Props) {
  const chip = estadoChip(estado);
  const hayAvisos = avisos.revise.length > 0 || avisos.recuerde.length > 0 || avisos.citasVerificadas > 0;
  return (
    <aside class="res-lat" aria-label="Descargas">
      <section aria-labelledby="fallo-titulo-descarga">
        <Chip tono={chip.tono}>{chip.texto}</Chip>
        <h2 id="fallo-titulo-descarga">Fallo de segunda instancia</h2>
        {principal && <p class="sub archivo-principal">{nombreArchivo(principal)}</p>}
        <div class="acciones">
          {principal && (
            <Boton variante="primario" grande href={urlSalida(caso, principal)} download={nombreArchivo(principal)}>
              Descargar fallo
            </Boton>
          )}
          <Boton href={urlZip(caso)} download={`${caso}.zip`}>
            Descargar todo (.zip)
          </Boton>
        </div>
      </section>

      {hayAvisos && (
        <section aria-label="Antes de firmar">
          <ul class="antes-firmar">
            {avisos.revise.map((a) => (
              <li key={a.clave}>
                <Chip tono="alerta">Revise</Chip>
                <span>
                  {a.texto}
                  {a.detalle && (
                    <details class="detalle-avisos">
                      <summary>Ver las alertas</summary>
                      <ul>
                        {a.detalle.map((d, i) => (
                          <li key={i}>{d}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </span>
              </li>
            ))}
            {avisos.revise.length === 0 && avisos.citasVerificadas > 0 && (
              <li>
                <Chip tono="ok">Citas</Chip>
                <span>
                  {avisos.citasVerificadas === 1
                    ? "La cita del fallo quedó verificada."
                    : `Las ${avisos.citasVerificadas} citas del fallo quedaron verificadas.`}
                </span>
              </li>
            )}
            {avisos.recuerde.map((a) => (
              <li key={a.clave}>
                <Chip tono="info">Recuerde</Chip>
                <span>{a.texto}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {grupos.length > 0 && (
        <section class="otros" aria-labelledby="fallo-titulo-otros">
          <h2 id="fallo-titulo-otros">Demás archivos del caso</h2>
          {grupos.map((grupo) => (
            <div key={grupo.clave} role="group" aria-labelledby={`fallo-grupo-${grupo.clave}`}>
              <h3 id={`fallo-grupo-${grupo.clave}`}>{grupo.titulo}</h3>
              {grupo.salidas.map((salida) => (
                <div class="otro" key={salida.ruta}>
                  <span>
                    {salida.nombre}
                    <small>{salida.archivo}</small>
                  </span>
                  <Boton href={urlSalida(caso, salida.ruta)} download={salida.archivo} aria-label={`Descargar ${salida.nombre}`}>
                    Descargar
                  </Boton>
                </div>
              ))}
            </div>
          ))}
        </section>
      )}
    </aside>
  );
}
