import { useEffect, useMemo, useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { ApoderadosRespuesta, CasoResumen, JobInicio, ProveedorCaso } from "../../api/contrato";
import { DATOS_PROVEEDOR, estadoServidor, jobActual, proveedorSinClave, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Dialogo, Migas, Pasos, Vacio } from "../../ui";
import { bloqueantes, listaNombres } from "../borrador/apoderados";
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
  leerHallazgos,
  moverClave,
  resumenCorto,
} from "./formulario";
import { Resuelve } from "./Resuelve";
import type { Cambiar } from "./Secciones";
import { Derechos, Ordenes, Otras, QueDecide, Reparos, Salida } from "./Secciones";
import type { Causal, ConfigCaso, Formulario, Hallazgo, PayloadDecision, RespuestaEstado } from "./tipos";
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

const EN_CURSO = "Ya hay una ejecución en curso para este caso.";
const RECHAZADA = "Su decisión no se aplicó: corrija los campos marcados y vuelva a enviarla.";
const esBloqueoApoderados = (mensaje: string) => mensaje.startsWith("Hay apoderados no verificados");

function accionDelError(mensaje: string, base: string) {
  if (mensaje === RECHAZADA) return undefined; // no hay proceso que ver: la decisión no llegó a aplicarse
  if (mensaje.startsWith("Falta la clave de la API")) return <Boton href="#/configuracion/ia">Ir a Inteligencia artificial</Boton>;
  if (mensaje.startsWith("Hay conflictos de edición")) return <Boton href={`${base}/borrador`}>Resolver en el borrador</Boton>;
  if (esBloqueoApoderados(mensaje)) return <Boton href={`${base}/borrador`}>Ir al borrador</Boton>;
  return <Boton href={`${base}/proceso`}>Ver el proceso</Boton>;
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
    return <Editor caso={caso} payload={estado.payload} proveedor={estado.proveedor_llm ?? null} config={datos.config} bloqueado={Boolean(estado.job_activo)} base={base} />;
  }
  // Una ejecución en curso manda sobre el estado: el hilo a medias se lee como «error» o «terminado».
  const enCurso = Boolean(estado.job_activo) || estado.estado === "corriendo";
  const perdido = !enCurso && Boolean(estado.historial_perdido);
  const terminado = !enCurso && !perdido && estado.estado === "terminado";
  const mensaje = enCurso
    ? "Hay una ejecución en curso para este caso."
    : perdido
      ? "Este caso perdió su historial de redacción: no hay una decisión pendiente. Vuelva a Documentos para iniciar la redacción de nuevo."
      : terminado
      ? "La decisión ya fue enviada y el fallo está generado."
      : estado.estado === "error"
        ? "El proceso quedó a medias. La decisión ya está guardada: continúe desde la vista del proceso, no hace falta enviarla otra vez."
        : "No hay una decisión pendiente. Genere primero el borrador previo.";
  return (
    <Vacio
      titulo="Decisión"
      accion={
        <Boton variante={terminado ? "sello" : "secundario"} href={`${base}/${terminado ? "fallo" : perdido ? "documentos" : "proceso"}`}>
          {terminado ? "Ver el fallo" : perdido ? "Ir a documentos" : "Ir al proceso"}
        </Boton>
      }
    >
      {mensaje}
      {estado.error && !terminado && !enCurso && !perdido && <span> {estado.error}</span>}
    </Vacio>
  );
}

interface PropsEditor {
  caso: string;
  payload: PayloadDecision;
  proveedor: ProveedorCaso | null;
  config: ConfigCaso | null;
  bloqueado: boolean;
  base: string;
}

function Editor({ caso, payload, proveedor, config, bloqueado, base }: PropsEditor) {
  const [f, setF] = useState<Formulario>(
    () => leerBorrador(caso, payload) ?? formularioInicial(payload, config?.despacho?.juez ?? ""),
  );
  const erroresServidor = payload.errores ?? [];
  const [mostrar, setMostrar] = useState(erroresServidor.length > 0);
  const [confirmar, setConfirmar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [errorEnvio, setErrorEnvio] = useState<string | null>(null);
  const [rechazo, setRechazo] = useState<{ cuerpo: string; hallazgos: Hallazgo[] } | null>(null);
  const [apoderados, setApoderados] = useState<ApoderadosRespuesta | null>(null);
  const [consultaApoderados, setConsultaApoderados] = useState(0);
  const cambiar: Cambiar = (fn) => setF(fn);

  useEffect(() => {
    const control = new AbortController();
    api.get<ApoderadosRespuesta>(`/api/casos/${codificar(caso)}/apoderados`, { signal: control.signal }).then(setApoderados, () => {});
    return () => control.abort();
  }, [caso, consultaApoderados]);

  const sinRevisar = bloqueantes(apoderados);
  const nombresSinRevisar = [...new Set(sinRevisar.map((a) => a.nombre))];

  useEffect(() => {
    guardarBorrador(caso, f);
  }, [caso, f]);

  const decision = useMemo(() => aDecision(f), [f]);
  const cuerpoActual = useMemo(() => JSON.stringify(decision), [decision]);
  const vista = useVistaPrevia(caso, decision, f.resultado !== "");
  // Lo que el servidor rechazó solo vale mientras el formulario siga igual: al editar, vuelve a mandar la vista previa.
  const rechazados = useMemo(
    () => (rechazo && rechazo.cuerpo === cuerpoActual ? rechazo.hallazgos : []),
    [rechazo, cuerpoActual],
  );
  const hallazgos = useMemo(
    () => combinar(hallazgosLocales(f), [...(vista.pendiente ? [] : (vista.datos?.faltantes ?? [])), ...rechazados]),
    [f, vista.pendiente, vista.datos, rechazados],
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
  const estado =
    sinRevisar.length > 0
      ? "Revise en el borrador los apoderados no verificados antes de enviar."
      : cortos.length
        ? `Para enviar falta: ${cortos.join(", ")}.`
        : "Listo para enviar.";
  const faltanteServidor = hallazgos.map((h) => h.mensaje).filter((m, i, l) => l.indexOf(m) === i);

  const mostrarErrores = (lista: Hallazgo[] = hallazgos) => {
    setMostrar(true);
    const primero = lista.find((h) => idDeCampo(f, h.campo));
    requestAnimationFrame(() => enfocar(primero ? idDeCampo(f, primero.campo) : "dec-resumen-errores"));
  };

  // La vista previa puede llegar con faltantes cuando el diálogo ya está abierto: se cierra y se muestran los motivos.
  useEffect(() => {
    if (confirmar && !enviando && hallazgos.length > 0) {
      setConfirmar(false);
      mostrarErrores();
    }
  }, [confirmar, enviando, hallazgos]);

  const intentar = () => {
    if (hallazgos.length) {
      mostrarErrores();
      return;
    }
    const sinClave = proveedorSinClave(estadoServidor.value, proveedor);
    if (sinClave) {
      setErrorEnvio(`Falta la clave de la API de ${DATOS_PROVEEDOR[sinClave].corto}: configúrela en Inteligencia artificial antes de enviar la decisión.`);
      return;
    }
    setErrorEnvio(null);
    setConfirmar(true);
  };

  const enviar = async () => {
    if (hallazgos.length) {
      setConfirmar(false);
      mostrarErrores();
      return;
    }
    setEnviando(true);
    try {
      const { job_id } = await api.post<JobInicio>(`/api/casos/${codificar(caso)}/run`, { cmd: "decidir", decision });
      jobActual.value = job_id;
      navegar(`${base}/proceso`);
    } catch (e) {
      setConfirmar(false);
      setEnviando(false);
      const rechazadosPorElServidor = e instanceof ErrorApi && e.estado === 422 ? leerHallazgos(e.detalle) : null;
      if (rechazadosPorElServidor) {
        setRechazo({ cuerpo: cuerpoActual, hallazgos: rechazadosPorElServidor });
        setErrorEnvio(RECHAZADA);
        mostrarErrores(combinar(hallazgos, rechazadosPorElServidor));
        return;
      }
      if (e instanceof ErrorApi && e.estado === 409) {
        // El servidor explica el 409 (conflictos de edición, apoderados sin revisar o una ejecución en curso).
        setErrorEnvio(typeof e.detalle === "string" && e.message ? e.message : EN_CURSO);
        setConsultaApoderados((n) => n + 1);
      } else {
        setErrorEnvio(mensajeDe(e));
      }
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
      {sinRevisar.length > 0 && (
        <Aviso tipo="error" titulo="Hay apoderados no verificados sin revisar" acciones={<Boton href={`${base}/borrador`}>Ir al borrador</Boton>}>
          {`${listaNombres(nombresSinRevisar)}: ${nombresSinRevisar.length === 1 ? "márquelo como revisado" : "márquelos como revisados"} en la pestaña Apoderados del borrador para poder enviar la decisión.`}
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
          acciones={accionDelError(errorEnvio, base)}
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
          <Boton variante="sello" grande onClick={intentar} disabled={bloqueado || sinRevisar.length > 0} cargando={enviando} aria-describedby="dec-estado">
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
            <Boton variante="sello" cargando={enviando} disabled={hallazgos.length > 0} onClick={() => void enviar()} data-enfoque>
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
