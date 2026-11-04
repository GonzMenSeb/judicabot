import { useEffect, useMemo, useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { CasoResumen, JobInicio } from "../../api/contrato";
import { estadoServidor, jobActual, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Dialogo, Migas, Pasos, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import { borrarBorrador, guardarBorrador, leerBorrador } from "./almacen";
import {
  aClaveApi,
  aClaveInterna,
  aDecision,
  advertenciasLocales,
  CAUSALES,
  clavesOrdenadas,
  combinar,
  esPlaceholderDecididoPor,
  fechaLarga,
  formularioInicial,
  hallazgosLocales,
  idDeCampo,
  moverClave,
  resumenCorto,
} from "./formulario";
import { Resuelve } from "./Resuelve";
import type { Cambiar } from "./Secciones";
import { Derechos, Ordenes, Otras, QueDecide, Reparos, Salida } from "./Secciones";
import type { Causal, ConfigCaso, Formulario, PayloadDecision, RespuestaEstado } from "./tipos";
import { useVistaPrevia } from "./useVistaPrevia";
import "./estilos.css";

interface Datos {
  estado: RespuestaEstado & { job_activo?: string | null };
  config: ConfigCaso | null;
}

const codificar = encodeURIComponent;

const CAUSAL_TEXTO: Record<Causal, string> = Object.fromEntries(CAUSALES) as Record<Causal, string>;

function enfocar(id: string | null): boolean {
  const el = id ? document.getElementById(id) : null;
  const objetivo = el?.matches("input, textarea, select, button") ? el : el?.querySelector<HTMLElement>("input, textarea, select, button");
  if (!objetivo) return false;
  objetivo.focus();
  objetivo.scrollIntoView?.({ block: "center" });
  return true;
}

function mensajeDe(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "No se pudo completar la operación.";
}

export default function Decision({ caso }: PropsVista) {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [resumen, setResumen] = useState<CasoResumen | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sinCaso, setSinCaso] = useState(false);
  const [intento, setIntento] = useState(0);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    const base = `/api/casos/${codificar(caso)}`;
    setError(null);
    setSinCaso(false);
    Promise.all([
      api.get<Datos["estado"]>(`${base}/estado`, { signal: control.signal }),
      api.get<ConfigCaso>(`${base}/config`, { signal: control.signal }).catch(() => null),
    ]).then(
      ([estado, config]) => {
        if (control.signal.aborted) return;
        if (estado.estado === "terminado") borrarBorrador(caso);
        setDatos({ estado, config });
      },
      (e: unknown) => {
        if (control.signal.aborted) return;
        if (e instanceof ErrorApi && e.estado === 404) setSinCaso(true);
        else setError(mensajeDe(e));
      },
    );
    return () => control.abort();
  }, [caso, intento]);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    setResumen(null);
    api.get<CasoResumen>(`/api/casos/${codificar(caso)}/resumen`, { signal: control.signal }).then(setResumen, () => {});
    return () => control.abort();
  }, [caso]);

  const nombre = resumen?.nombre ?? caso ?? "";
  useTitulo(nombre ? `Decisión · ${nombre}` : "Decisión");

  if (!caso) return <Vacio titulo="Falta el caso">Elija un caso desde la lista de casos de segunda instancia.</Vacio>;

  if (sinCaso) {
    return (
      <div data-vista="decision">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        <CasoNoEncontrado />
      </div>
    );
  }

  const base = `#/segunda/${codificar(caso)}`;

  return (
    <div data-vista="decision">
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <div class="dec-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {resumen && (
          <div class="dec-meta">
            {resumen.radicado && <span>Radicado {resumen.radicado}</span>}
            {resumen.juzgado_a_quo && <span>{resumen.juzgado_a_quo}</span>}
          </div>
        )}
      </div>
      <Pasos caso={caso} actual="decision" limite={resumen && resumen.etapa >= 3 ? "fallo" : "decision"} />
      {error && (
        <Aviso tipo="error" titulo="No se pudo cargar la decisión" acciones={<Boton onClick={() => setIntento((n) => n + 1)}>Reintentar</Boton>}>
          {error}
        </Aviso>
      )}
      {!error && !datos && <Cargando texto="Cargando la decisión…" />}
      {datos && <Contenido caso={caso} datos={datos} base={base} />}
    </div>
  );
}

function Contenido({ caso, datos, base }: { caso: string; datos: Datos; base: string }) {
  const { estado } = datos;
  if (estado.estado === "esperando_decision" && estado.payload) {
    return <Editor caso={caso} payload={estado.payload} config={datos.config} bloqueado={Boolean(estado.job_activo)} base={base} />;
  }
  const terminado = estado.estado === "terminado";
  const enCurso = Boolean(estado.job_activo);
  const mensaje = terminado
    ? "La decisión ya fue enviada y el fallo está generado."
    : estado.estado === "error"
      ? "El proceso quedó a medias. La decisión ya está guardada: continúe desde la vista del proceso, no hace falta enviarla otra vez."
      : enCurso
        ? "Hay una ejecución en curso para este caso."
        : "No hay una decisión pendiente. Genere primero el borrador previo.";
  return (
    <Vacio
      titulo="Decisión"
      accion={
        <Boton variante={terminado ? "sello" : "secundario"} href={`${base}/${terminado ? "fallo" : "proceso"}`}>
          {terminado ? "Ver el fallo" : "Ir al proceso"}
        </Boton>
      }
    >
      {mensaje}
      {estado.error && !terminado && <span> {estado.error}</span>}
    </Vacio>
  );
}

interface PropsEditor {
  caso: string;
  payload: PayloadDecision;
  config: ConfigCaso | null;
  bloqueado: boolean;
  base: string;
}

function Editor({ caso, payload, config, bloqueado, base }: PropsEditor) {
  const [f, setF] = useState<Formulario>(
    () => leerBorrador(caso, payload) ?? formularioInicial(payload, config?.despacho?.juez ?? ""),
  );
  const erroresServidor = payload.errores ?? [];
  const [mostrar, setMostrar] = useState(erroresServidor.length > 0);
  const [confirmar, setConfirmar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [errorEnvio, setErrorEnvio] = useState<string | null>(null);
  const cambiar: Cambiar = (fn) => setF(fn);

  useEffect(() => {
    guardarBorrador(caso, f);
  }, [caso, f]);

  const decision = useMemo(() => aDecision(f), [f]);
  const vista = useVistaPrevia(caso, decision, f.resultado !== "");
  const hallazgos = useMemo(
    () => combinar(hallazgosLocales(f), vista.pendiente ? [] : (vista.datos?.faltantes ?? [])),
    [f, vista.pendiente, vista.datos],
  );
  const err = (campo: string) => (mostrar ? hallazgos.find((h) => h.campo === campo)?.mensaje : undefined);
  const vistaLista = vista.datos && !vista.pendiente && !vista.error ? vista.datos : null;
  const avisos = useMemo(() => combinar(advertenciasLocales(f), vistaLista?.advertencias ?? []), [f, vistaLista]);

  const numerales = useMemo(() => {
    const base = vista.datos?.numerales ?? [];
    if (!vista.pendiente || !f.reordenado) return base;
    const orden = clavesOrdenadas(f).map((k) => aClaveApi(f, k));
    const rango = (c: string) => (orden.includes(c) ? orden.indexOf(c) : orden.length);
    return [...base].sort((a, b) => rango(a.clave) - rango(b.clave));
  }, [vista.datos, vista.pendiente, f]);

  const mover = (clave: string, delta: number) =>
    cambiar((x) => {
      const interna = aClaveInterna(x, clave);
      return interna ? moverClave(x, interna, delta) : x;
    });
  const soltar = (origen: string, destino: string) =>
    cambiar((x) => {
      const o = aClaveInterna(x, origen);
      const d = aClaveInterna(x, destino);
      return o && d ? moverClave(x, o, d) : x;
    });

  const cortos = [...new Set(hallazgos.map(resumenCorto))];
  const estado = cortos.length ? `Para enviar falta: ${cortos.join(", ")}.` : "Listo para enviar.";
  const faltanteServidor = hallazgos.map((h) => h.mensaje).filter((m, i, l) => l.indexOf(m) === i);

  const intentar = () => {
    if (hallazgos.length) {
      setMostrar(true);
      const primero = hallazgos.find((h) => idDeCampo(f, h.campo));
      requestAnimationFrame(() => enfocar(primero ? idDeCampo(f, primero.campo) : "dec-resumen-errores"));
      return;
    }
    if (config?.llm?.proveedor === "anthropic" && estadoServidor.value?.api_key === false) {
      setErrorEnvio("Falta la API key de Anthropic: configúrela en Inteligencia artificial antes de enviar la decisión.");
      return;
    }
    setErrorEnvio(null);
    setConfirmar(true);
  };

  const enviar = async () => {
    setEnviando(true);
    try {
      const { job_id } = await api.post<JobInicio>(`/api/casos/${codificar(caso)}/run`, { cmd: "decidir", decision });
      jobActual.value = job_id;
      navegar(`${base}/proceso`);
    } catch (e) {
      setConfirmar(false);
      setEnviando(false);
      setErrorEnvio(e instanceof ErrorApi && e.estado === 409 ? "Ya hay una ejecución en curso para este caso." : mensajeDe(e));
    }
  };

  const mensajesGenerales = [...new Set([...erroresServidor, ...(mostrar ? faltanteServidor : [])])];

  return (
    <>
      <Contexto payload={payload} />
      {bloqueado && (
        <Aviso tipo="info" acciones={<Boton href={`${base}/proceso`}>Ver el proceso</Boton>}>
          Hay una ejecución en curso para este caso. Espere a que termine para enviar la decisión.
        </Aviso>
      )}
      {mostrar && mensajesGenerales.length > 0 && (
        <div id="dec-resumen-errores" tabIndex={-1} class="dec-resumen-errores">
          <Aviso tipo="error" titulo="Revise la decisión antes de enviarla">
            <ul>
              {mensajesGenerales.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </Aviso>
        </div>
      )}
      {avisos.length > 0 && (
        <div id="dec-avisos" class="dec-avisos">
          <Aviso tipo="alerta" titulo="Avisos que no impiden enviar la decisión">
            <ul>
              {avisos.map((a) => (
                <li key={`${a.campo}|${a.mensaje}`}>{a.mensaje}</li>
              ))}
            </ul>
          </Aviso>
        </div>
      )}
      {errorEnvio && (
        <Aviso
          tipo="error"
          titulo="No se pudo enviar la decisión"
          acciones={errorEnvio.startsWith("Falta la API key") ? <Boton href="#/ia">Ir a Inteligencia artificial</Boton> : <Boton href={`${base}/proceso`}>Ver el proceso</Boton>}
        >
          {errorEnvio}
        </Aviso>
      )}
      <div class="dec-dos">
        <form class="dec-form" onSubmit={(e) => e.preventDefault()} noValidate aria-label="Decisión del juez">
          <QueDecide f={f} cambiar={cambiar} err={err} />
          <Reparos f={f} cambiar={cambiar} err={err} payload={payload} />
          <Derechos f={f} cambiar={cambiar} err={err} />
          <Ordenes f={f} cambiar={cambiar} err={err} />
          <Otras f={f} cambiar={cambiar} err={err} />
          <Salida f={f} cambiar={cambiar} err={err} fechaHoy={vistaLista?.fecha_por_defecto ? vistaLista.fecha_fallo : undefined} avisaDecididoPor={avisos.some((a) => a.campo === "decidido_por")} />
        </form>
        <Resuelve
          numerales={numerales}
          vacio={f.resultado === ""}
          pendiente={vista.pendiente}
          error={vista.error}
          cierre={config?.despacho?.cierre_fallo ?? ""}
          mensajes={vista.pendiente ? [] : (vista.datos?.errores ?? [])}
          onReintentar={vista.reintentar}
          onMover={mover}
          onSoltar={soltar}
        />
      </div>
      <div class="dec-barra">
        <div>
          <span class="dec-estado" id="dec-estado" role="status" aria-live="polite">
            {estado}
          </span>
          <Boton href={`${base}/borrador`}>Volver al borrador</Boton>
          <Boton variante="sello" grande onClick={intentar} disabled={bloqueado} cargando={enviando} aria-describedby="dec-estado">
            Enviar decisión y redactar
          </Boton>
        </div>
      </div>
      <Dialogo
        abierto={confirmar}
        titulo="¿Enviar la decisión?"
        onCerrar={() => {
          if (!enviando) setConfirmar(false);
        }}
        acciones={
          <>
            <Boton disabled={enviando} onClick={() => setConfirmar(false)}>
              Revisar
            </Boton>
            <Boton variante="sello" cargando={enviando} onClick={() => void enviar()} data-enfoque>
              Enviar decisión
            </Boton>
          </>
        }
      >
        <p>Con esto se redacta el caso concreto y se genera el fallo. Después de enviarla, la decisión no se puede cambiar desde esta pantalla.</p>
        <ul class="dec-confirmacion">
          {decision.resultado && <li>Resultado: {decision.resultado}</li>}
          {decision.sustitutiva && <li>En su lugar: {decision.sustitutiva.replace(/_/g, " ").toLowerCase()}</li>}
          {decision.causal && <li>Causal: {CAUSAL_TEXTO[decision.causal]}</li>}
          {decision.ordenes.length > 0 && <li>Órdenes: {decision.ordenes.length}</li>}
          {vistaLista && <li>Numerales del RESUELVE: {vistaLista.numerales.length}</li>}
          {vistaLista?.encabezado && (
            <li>
              Encabezado: <b>{vistaLista.encabezado}</b>
            </li>
          )}
          {vistaLista && (
            <li>
              Fecha del fallo: {fechaLarga(vistaLista.fecha_fallo)}
              {vistaLista.fecha_por_defecto && <span class="dec-defecto"> (por defecto)</span>}
            </li>
          )}
          {!vistaLista && (
            <li role="status">{vista.pendiente ? "Calculando el encabezado y la fecha…" : "No se pudo calcular el encabezado ni la fecha efectiva."}</li>
          )}
          <li>Formato Factor Calidad: {decision.generar_formato ? "se genera, con los puntajes en blanco" : "no se genera"}</li>
          <li>
            Decidido por:{" "}
            {decision.decidido_por ? (
              <span class={esPlaceholderDecididoPor(decision.decidido_por) ? "dec-defecto" : undefined}>{decision.decidido_por}</span>
            ) : (
              <span class="dec-defecto">sin nombre (constará «no consta»)</span>
            )}
          </li>
        </ul>
        {avisos.length > 0 && (
          <Aviso tipo="alerta" titulo="Revise antes de enviar">
            <ul>
              {avisos.map((a) => (
                <li key={`${a.campo}|${a.mensaje}`}>{a.mensaje}</li>
              ))}
            </ul>
          </Aviso>
        )}
      </Dialogo>
    </>
  );
}

function Contexto({ payload }: { payload: PayloadDecision }) {
  const impugnantes = (payload.impugnantes ?? []).filter(Boolean);
  const quien =
    impugnantes.length > 1
      ? impugnantes.join(", ")
      : payload.impugnante
        ? `${payload.impugnante}${payload.impugnante_rol ? ` (${payload.impugnante_rol})` : ""}`
        : "";
  const pruebas = payload.pruebas_nuevas_2a ?? [];
  if (!quien && !payload.decision_a_quo && pruebas.length === 0) return null;
  return (
    <div class="dec-contexto">
      {quien && (
        <div>
          <b>{impugnantes.length > 1 ? "Impugnan" : "Impugna"}</b>
          {quien}
        </div>
      )}
      {payload.decision_a_quo && (
        <div>
          <b>Decisión del a quo</b>
          {payload.decision_a_quo}
        </div>
      )}
      <div>
        <b>Pruebas nuevas</b>
        {pruebas.length ? pruebas.join("; ") : "Ninguna en segunda instancia"}
      </div>
    </div>
  );
}
