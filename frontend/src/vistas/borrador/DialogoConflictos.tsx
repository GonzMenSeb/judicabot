import { useEffect, useId, useRef, useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { ConflictoEdicion, EdicionesRespuesta, ResolverCuerpo, TrozoConflicto } from "../../api/contrato";
import { Boton, Dialogo } from "../../ui";
import "./editor.css";

type Eleccion = ResolverCuerpo["elecciones"][number];

export interface PropsDialogoConflictos {
  abierto: boolean;
  caso: string;
  conflictos: ConflictoEdicion[];
  recargar: () => Promise<void>;
  onCerrar: () => void;
}

const EXPLICACION_MIO =
  "Su versión cambia las citas respecto de la corrección —los números de cita pueden haberse reasignado—; elija la versión de la corrección.";
const FICHA = /(⟦[^⟧]*⟧)/;

const conflictivos = (c: ConflictoEdicion): TrozoConflicto[] => c.trozos.filter((t): t is TrozoConflicto => t.tipo === "conflicto");

function Parrafos({ parrafos, vacio }: { parrafos: string[]; vacio?: string }) {
  if (parrafos.length === 0) return <p class="bor-conf-vacio">{vacio}</p>;
  return (
    <>
      {parrafos.map((p, i) => (
        <p key={i}>
          {p.split(FICHA).map((parte, j) => (j % 2 ? <span key={j} class="bor-ficha">{parte}</span> : parte))}
        </p>
      ))}
    </>
  );
}

function SeccionConflicto({ conflicto, caso, recargar }: { conflicto: ConflictoEdicion; caso: string; recargar: () => Promise<void> }) {
  const id = useId();
  const pendientes = conflictivos(conflicto);
  const [elegidas, setElegidas] = useState<(Eleccion | null)[]>([]);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const volver = useRef<HTMLElement | null>(null);
  const valores = pendientes.map((_, k) => elegidas[k] ?? null);
  const completo = valores.every((v) => v !== null);
  const ruta = `/api/casos/${encodeURIComponent(caso)}/ediciones/${encodeURIComponent(conflicto.pieza)}`;

  useEffect(() => {
    if (ocupado || !volver.current) return;
    const activo = document.activeElement;
    if (!activo || activo === document.body) volver.current.focus();
    volver.current = null;
  }, [ocupado]);

  async function enviar(origen: HTMLElement, peticion: () => Promise<EdicionesRespuesta>) {
    volver.current = null;
    setOcupado(true);
    setError(null);
    try {
      await peticion();
    } catch (e) {
      volver.current = origen;
      setOcupado(false);
      setError(e instanceof ErrorApi ? e.message : "No se pudo enviar la solicitud. Revise la conexión e intente de nuevo.");
      if (e instanceof ErrorApi && e.estado === 409) await recargar();
      return;
    }
    await recargar();
    setOcupado(false);
  }

  const elegir = (k: number, valor: Eleccion) => setElegidas(pendientes.map((_, i) => (i === k ? valor : (elegidas[i] ?? null))));
  const aplicar = (origen: HTMLElement) => {
    if (!completo) return;
    const cuerpo: ResolverCuerpo = { elecciones: valores.filter((v): v is Eleccion => v !== null) };
    void enviar(origen, () => api.post<EdicionesRespuesta>(`${ruta}/resolver`, cuerpo));
  };

  let k = 0;
  return (
    <section class="bor-conf" aria-labelledby={`${id}-titulo`}>
      <h3 id={`${id}-titulo`}>{conflicto.etiqueta}</h3>
      {conflicto.huerfana ? (
        <>
          <p class="bor-conf-nota">Este texto ya no existe en el borrador, pero conserva una edición suya. Solo puede descartarla.</p>
          {conflicto.trozos.some((t) => t.tipo === "ok" && t.parrafos.length > 0) && (
            <>
              <p class="bor-conf-nota">Su texto, por si quiere copiarlo antes de descartarlo:</p>
              {conflicto.trozos.map((trozo, i) =>
                trozo.tipo === "ok" ? (
                  <div key={i} class="bor-conf-texto">
                    <Parrafos parrafos={trozo.parrafos} />
                  </div>
                ) : null,
              )}
            </>
          )}
          <div class="bor-conf-acciones">
            <Boton cargando={ocupado} onClick={(e) => void enviar(e.currentTarget, () => api.delete<EdicionesRespuesta>(ruta))} aria-describedby={`${id}-titulo`}>
              Descartar mi edición
            </Boton>
          </div>
        </>
      ) : (
        <>
          {conflicto.trozos.map((trozo, i) => {
            if (trozo.tipo === "ok") {
              return (
                <div key={i} class="bor-conf-ok">
                  <Parrafos parrafos={trozo.parrafos} />
                </div>
              );
            }
            const n = k++;
            const nombre = `${id}-${n}`;
            return (
              <fieldset key={i} class="bor-conf-trozo">
                <legend>{pendientes.length === 1 ? "Conflicto" : `Conflicto ${n + 1} de ${pendientes.length}`}</legend>
                <div class="bor-conf-lados">
                  <div class="bor-conf-lado">
                    <label>
                      <input
                        type="radio"
                        name={nombre}
                        value="mio"
                        checked={valores[n] === "mio"}
                        disabled={!trozo.mio_permitido || ocupado}
                        aria-describedby={`${nombre}-mio${trozo.mio_permitido ? "" : ` ${nombre}-no`}`}
                        onChange={() => elegir(n, "mio")}
                      />
                      <b>Su versión</b>
                    </label>
                    <div id={`${nombre}-mio`} class="bor-conf-texto">
                      <Parrafos parrafos={trozo.mio} vacio="Sin texto: se elimina este párrafo." />
                    </div>
                  </div>
                  <div class="bor-conf-lado">
                    <label>
                      <input
                        type="radio"
                        name={nombre}
                        value="nuevo"
                        checked={valores[n] === "nuevo"}
                        disabled={ocupado}
                        aria-describedby={`${nombre}-nuevo`}
                        onChange={() => elegir(n, "nuevo")}
                      />
                      <b>Versión de la corrección</b>
                    </label>
                    <div id={`${nombre}-nuevo`} class="bor-conf-texto">
                      <Parrafos parrafos={trozo.nuevo} vacio="Sin texto: se elimina este párrafo." />
                    </div>
                  </div>
                </div>
                {!trozo.mio_permitido && (
                  <p id={`${nombre}-no`} class="bor-conf-nota">
                    {EXPLICACION_MIO}
                  </p>
                )}
              </fieldset>
            );
          })}
          <div class="bor-conf-acciones">
            <Boton variante="primario" cargando={ocupado} disabled={!completo} onClick={(e) => aplicar(e.currentTarget)} aria-describedby={`${id}-titulo`}>
              Aplicar
            </Boton>
          </div>
        </>
      )}
      {error && (
        <p class="bor-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export function DialogoConflictos({ abierto, caso, conflictos, recargar, onCerrar }: PropsDialogoConflictos) {
  useEffect(() => {
    if (abierto && conflictos.length === 0) onCerrar();
  }, [abierto, conflictos.length]);

  return (
    <Dialogo abierto={abierto} titulo="Resolver conflictos de edición" onCerrar={onCerrar} class="bor-dialogo bor-dialogo-conflictos" acciones={<Boton onClick={onCerrar}>Cerrar</Boton>}>
      <p class="sub bor-dialogo-intro">
        Editó estos textos y la corrección de la IA cambió los mismos párrafos. Elija qué versión conservar en cada conflicto.
      </p>
      {conflictos.map((c) => (
        <SeccionConflicto key={`${c.pieza}|${JSON.stringify(c)}`} conflicto={c} caso={caso} recargar={recargar} />
      ))}
    </Dialogo>
  );
}
