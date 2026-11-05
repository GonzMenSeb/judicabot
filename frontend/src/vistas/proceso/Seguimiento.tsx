import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, cancelable, esAbortado, useEventos } from "../../api";
import type { Evento } from "../../api/contrato";
import { estadoServidor, nombreModelo, plural } from "../../estado";
import { Aviso, Boton, Cargando, cx } from "../../ui";
import { AccionFinal, BloqueError, baseCaso } from "./Acciones";
import { IconoEtapa, IconoTipo } from "./iconos";
import {
  ETAPAS,
  ETIQUETA_TIPO,
  agrupar,
  datosEtapa,
  duracionEventos,
  estadoEtapas,
  formatearTiempo,
  marcaDe,
  mensajeError,
} from "./modelo";
import type { EstadoEtapa, EtapaProceso } from "./modelo";
import type { EstadoCaso } from "./tipos";
import "./estilos.css";

const MARGEN_PEGADO = 48;

const TEXTO_ESTADO: Record<EstadoEtapa, string> = {
  hecho: " (completada)",
  actual: " (en curso)",
  espera: " (pendiente)",
  error: " (con error)",
};

export interface PropsSeguimientoCompleto {
  incrustado?: false;
  jobId: string;
  caso: string;
  cmd: string | null;
  alNuevoJob: (jobId: string) => void;
  alReintentar: () => void;
  alEstado: (estado: EstadoCaso) => void;
}

export interface PropsSeguimientoIncrustado {
  incrustado: true;
  jobId: string;
}

export type PropsSeguimiento = PropsSeguimientoCompleto | PropsSeguimientoIncrustado;

function useTranscurrido(eventos: readonly Evento[], corriendo: boolean): number {
  const [ahora, setAhora] = useState(() => Date.now());
  const ultimo = eventos[eventos.length - 1]?.n ?? 0;
  const llegada = useRef({ n: ultimo, t: Date.now() });
  if (llegada.current.n !== ultimo) llegada.current = { n: ultimo, t: Date.now() };

  useEffect(() => {
    if (!corriendo) return undefined;
    const id = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(id);
  }, [corriendo]);

  return duracionEventos(eventos) + (corriendo ? Math.max(0, ahora - llegada.current.t) : 0);
}

function Fila({ evento, inicio }: { evento: Evento; inicio: number }) {
  return (
    <li class={`tz-l tz-${evento.tipo}`}>
      <span class="tz-t">{marcaDe(evento, inicio)}</span>
      <span class="tz-k">
        <IconoTipo tipo={evento.tipo} />
        <span class="tz-kt">{ETIQUETA_TIPO[evento.tipo]}</span>
      </span>
      <span class="tz-x">{evento.texto}</span>
    </li>
  );
}

export function Seguimiento(props: PropsSeguimiento) {
  const { jobId } = props;
  const completo = props.incrustado ? null : props;
  const { eventos, fin, conexion } = useEventos(`/api/jobs/${encodeURIComponent(jobId)}/eventos`);
  const { porEtapa, huerfanos, activa } = useMemo(() => agrupar(eventos), [eventos]);
  const hayRazona = useMemo(() => eventos.some((e) => e.tipo === "razona"), [eventos]);
  const estados = estadoEtapas(activa, fin);
  const fallido = conexion === "fallido";
  const terminada = fin !== null || fallido;
  const corriendo = !terminada;

  const [fijada, setFijada] = useState<EtapaProceso | null>(null);
  const siguiendo = fijada === null || fijada === activa;
  const visible: EtapaProceso = fijada ?? activa ?? ETAPAS[0]!.id;
  const sinEtapa = activa === null && fijada === null && huerfanos.length > 0;
  const lista = sinEtapa ? huerfanos : porEtapa[visible];
  const datos = datosEtapa(visible);
  const primero = eventos[0];
  const inicio = primero ? Date.parse(primero.t) : Number.NaN;

  const transcurrido = useTranscurrido(eventos, corriendo);

  const [final, setFinal] = useState<EstadoCaso | null>(null);
  const [falloFinal, setFalloFinal] = useState(false);
  const senal = useRef(cancelable()).current;
  const consultar = () => {
    if (!completo) return;
    setFalloFinal(false);
    api.get<EstadoCaso>(`/api/casos/${encodeURIComponent(completo.caso)}/estado`, { signal: senal() }).then(
      (estado) => {
        setFinal(estado);
        completo.alEstado(estado);
      },
      (error) => {
        if (!esAbortado(error)) setFalloFinal(true);
      },
    );
  };
  useEffect(() => {
    if (terminada) consultar();
  }, [terminada]);
  useEffect(() => () => void senal(), []);

  const yaAbierto = useRef(false);
  if (conexion === "abierto") yaAbierto.current = true;
  let textoConexion: string;
  if (fin) textoConexion = fin.estado === "error" ? "Ejecución detenida por un error" : "Ejecución terminada";
  else if (fallido) textoConexion = "Sin conexión con el servidor";
  else if (conexion === "conectando") textoConexion = yaAbierto.current ? "Reconectando…" : "Conectando…";
  else textoConexion = activa ? `Conectado · ${datosEtapa(activa).titulo}` : "Conectado · esperando el primer paso";
  const claveConexion = fin ? "cerrado" : conexion;

  const panel = useRef<HTMLDivElement>(null);
  const pegado = useRef(true);
  const [separado, setSeparado] = useState(false);

  useLayoutEffect(() => {
    const el = panel.current;
    pegado.current = siguiendo;
    setSeparado(false);
    if (el) el.scrollTop = siguiendo ? el.scrollHeight : 0;
  }, [visible, siguiendo]);

  useLayoutEffect(() => {
    const el = panel.current;
    if (el && siguiendo && pegado.current) el.scrollTop = el.scrollHeight;
  }, [lista.length]);

  const alDesplazar = () => {
    const el = panel.current;
    if (!el) return;
    const lejos = el.scrollHeight - el.scrollTop - el.clientHeight > MARGEN_PEGADO;
    pegado.current = !lejos;
    setSeparado(lejos && siguiendo);
  };

  const irAlFinal = () => {
    const el = panel.current;
    if (el) el.scrollTop = el.scrollHeight;
    pegado.current = true;
    setSeparado(false);
  };

  const elegir = (id: EtapaProceso) => setFijada(id === activa ? null : id);

  const errorFin = fin?.estado === "error" || (fin !== null && final?.estado === "error");
  const modelo = estadoServidor.value?.modelo;
  const estadoVisible = estados[visible];
  const sinEventos = eventos.length === 0;

  return (
    <>
      <div class="tz-top">
        <span>
          Tiempo <b>{formatearTiempo(transcurrido)}</b>
        </span>
        {modelo && (
          <span>
            Modelo <b>{nombreModelo(modelo)}</b>
          </span>
        )}
        <span>
          Pasos <b>{eventos.length}</b>
        </span>
        <span class="tz-conexion" role="status" data-conexion={claveConexion}>
          <i class="tz-punto" aria-hidden="true" />
          {textoConexion}
        </span>
      </div>

      {completo && errorFin && (
        <BloqueError
          caso={completo.caso}
          mensaje={fin?.estado === "error" ? mensajeError(fin, eventos) : (final?.error ?? mensajeError(fin, eventos))}
          cmd={completo.cmd}
          alNuevoJob={completo.alNuevoJob}
          alReintentar={completo.alReintentar}
        />
      )}
      {completo && fin && !errorFin && !final && !falloFinal && <Cargando texto="Comprobando el estado del caso…" />}
      {fin && !errorFin && falloFinal && (
        <Aviso
          class="tz-aviso"
          tipo="alerta"
          titulo="No se pudo comprobar el estado del caso"
          acciones={<Boton onClick={consultar}>Reintentar</Boton>}
        >
          La ejecución terminó. Use los pasos del caso para continuar.
        </Aviso>
      )}
      {completo && fin && !errorFin && final && <AccionFinal caso={completo.caso} estado={final.estado} />}
      {completo && fin && !errorFin && final && final.estado !== "esperando_decision" && final.estado !== "terminado" && (
        <div class="tz-fin" role="status">
          <b>La ejecución terminó.</b>
          <Boton variante="primario" href={`${baseCaso(completo.caso)}/documentos`}>
            Ir a documentos
          </Boton>
        </div>
      )}
      {completo && fallido && !fin && (
        <Aviso
          class="tz-aviso"
          tipo="alerta"
          titulo="Se perdió la conexión con el servidor"
          acciones={<Boton onClick={completo.alReintentar}>Reintentar</Boton>}
        >
          La ejecución puede seguir en el servidor.
        </Aviso>
      )}
      {completo && fallido && !fin && final && <AccionFinal caso={completo.caso} estado={final.estado} />}

      <div class="tz">
        <ol class="tz-izq" aria-label="Etapas del proceso">
          {ETAPAS.map((etapa) => {
            const estado = estados[etapa.id];
            const n = porEtapa[etapa.id].length;
            const detalle =
              estado === "espera" ? etapa.detalle : `${n === 0 ? "Sin pasos en esta ejecución" : plural(n, "paso")}. ${etapa.detalle}`;
            return (
              <li key={etapa.id}>
                <button
                  type="button"
                  class={cx("tz-et", estado)}
                  aria-pressed={visible === etapa.id && !sinEtapa}
                  aria-current={etapa.id === activa && !terminada ? "step" : undefined}
                  onClick={() => elegir(etapa.id)}
                >
                  <IconoEtapa estado={estado} />
                  <span>
                    <b>
                      {etapa.titulo}
                      <span class="solo-lectura">{TEXTO_ESTADO[estado]}</span>
                    </b>
                    <small>{detalle}</small>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <div
          class="tz-der"
          ref={panel}
          onScroll={alDesplazar}
          role="region"
          aria-label={`Pasos de la etapa: ${sinEtapa ? "mensajes del sistema" : datos.titulo}`}
          tabIndex={0}
        >
          <h2>{sinEtapa ? "Mensajes del sistema" : datos.titulo}</h2>
          {!sinEtapa && <p class="tz-sub">{datos.detalle}</p>}
          {!siguiendo && !fin && (
            <p class="tz-seguir">
              <Boton variante="fantasma" onClick={() => setFijada(null)}>
                Volver a lo que ocurre ahora
              </Boton>
            </p>
          )}
          {lista.length > 0 ? (
            <ol class="tz-lineas">
              {lista.map((evento) => (
                <Fila key={evento.n} evento={evento} inicio={inicio} />
              ))}
              {siguiendo && estadoVisible === "actual" && !sinEtapa && (
                <li class="tz-vivo">
                  <span class="giro" aria-hidden="true" />
                  Esperando el siguiente paso…
                </li>
              )}
            </ol>
          ) : sinEventos && corriendo ? (
            <Cargando texto="Esperando el primer paso del servidor…" />
          ) : (
            <p class="tz-espera-texto">
              {estadoVisible === "hecho"
                ? "Esta etapa se completó en una ejecución anterior."
                : "Esta etapa empieza cuando termine la anterior."}
            </p>
          )}
          <p class="tz-nota">
            {hayRazona
              ? "Resumen del razonamiento del modelo y de los pasos del sistema. Los textos finales no se modifican aquí."
              : "Pasos registrados por el sistema. Los textos finales no se modifican aquí."}
          </p>
          {separado && (
            <div class="tz-ir">
              <Boton onClick={irAlFinal}>Ir al último paso</Boton>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
