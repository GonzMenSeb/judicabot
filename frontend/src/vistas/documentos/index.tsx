import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { api, cancelable, ErrorApi, esAbortado } from "../../api";
import { esDetalleDescarte } from "../../api/contrato";
import type { CasoResumen, JobInicio, ProveedorCaso, RunCuerpo, Termino, TerminoRespuesta } from "../../api/contrato";
import { cargarEstadoServidor, enumerar, estadoServidor, jobActual, casoActual, mostrarToast, nombreModelo, plural, proveedorDelCaso, proveedorSinClave, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Migas, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import "./estilos.css";
import { Barra } from "./Barra";
import { Cabeza } from "./Cabeza";
import { DialogoClave } from "./DialogoClave";
import { DialogoDescartar } from "./DialogoDescartar";
import { DialogoRevisar } from "./DialogoRevisar";
import { FilaDoc } from "./FilaDoc";
import { FormAuto } from "./FormAuto";
import { Generados } from "./Generados";
import { Progreso } from "./Progreso";
import { DIAS_MAXIMO, conRepartoEditado, cuerpoTermino, errorTermino, terminoEditado, valoresTermino } from "./termino";
import type { EdicionTermino } from "./termino";
import type { CampoTermino } from "./FormTermino";
import { cambiosAuto, cuerpoRevision, hayCambios, sinConfirmar } from "./revision";
import type { CambiosRoles, EdicionAuto } from "./revision";
import { OBLIGATORIOS, etiquetaRol, ingestaDe, salidasPrevias } from "./tipos";
import type { ClaveAuto, DatosAuto, DocResumen, EstadoCaso, JobEstado, ResumenIngesta, RolDoc } from "./tipos";

interface AvisoVista {
  tipo: "alerta" | "error" | "info";
  texto: string;
  enlace?: { texto: string; href: string };
}

interface Trabajo {
  id: string;
  cmd: JobEstado["cmd"];
}

/** Lo que el servidor se negó a descartar sin confirmación (409 «trabajo_previo»), a la espera de que el usuario confirme. */
interface Descarte {
  cmd: "nuevo" | "iniciar";
  mensaje: string;
}

const COPIA_EN_PAPELERA = "antes se guarda una copia del caso en la papelera, donde se puede recuperar durante 30 días";

const AUTO_VACIO: DatosAuto = { fecha: null, fecha_reparto: null, accionante: null, accionada: null, firmante: null, cargo_firmante: null };

const hrefEtapa = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

export default function Documentos({ caso }: PropsVista) {
  if (!caso) return <Vacio titulo="Falta indicar el caso" />;
  return <VistaDocumentos caso={caso} />;
}

function VistaDocumentos({ caso }: { caso: string }) {
  const [estado, setEstado] = useState<EstadoCaso | null>(null);
  const [info, setInfo] = useState<CasoResumen | null>(null);
  const [proveedor, setProveedor] = useState<ProveedorCaso | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [noExiste, setNoExiste] = useState(false);
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [cambios, setCambios] = useState<CambiosRoles>({});
  const [edicion, setEdicion] = useState<EdicionAuto>({});
  const [termino, setTermino] = useState<TerminoRespuesta | null>(null);
  const [edTermino, setEdTermino] = useState<EdicionTermino>({});
  const [abiertos, setAbiertos] = useState<ReadonlySet<string>>(new Set());
  const [aviso, setAviso] = useState<AvisoVista | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [guardandoTermino, setGuardandoTermino] = useState(false);
  const [iniciando, setIniciando] = useState(false);
  const [procesando, setProcesando] = useState(false);
  const [pidiendoClave, setPidiendoClave] = useState(false);
  const [confirmandoRevisar, setConfirmandoRevisar] = useState(false);
  const [descarte, setDescarte] = useState<Descarte | null>(null);
  const nuevaSenal = useRef(cancelable()).current;
  const iniciandoAhora = useRef(false);
  const descarteConfirmado = useRef(false);
  const base = `/api/casos/${encodeURIComponent(caso)}`;

  useTitulo(`Documentos · ${info?.nombre ?? caso}`);

  const cargar = useCallback(async () => {
    const signal = nuevaSenal();
    setErrorCarga(null);
    setNoExiste(false);
    try {
      const [est, resumen, plazo] = await Promise.all([
        api.get<EstadoCaso>(`${base}/estado`, { signal }),
        api.get<CasoResumen>(`${base}/resumen`, { signal }).catch(() => null),
        api.get<TerminoRespuesta>(`${base}/termino`, { signal }).catch(() => null),
      ]);
      let activo: Trabajo | null = null;
      if (est.job_activo) {
        const job = await api.get<JobEstado>(`/api/jobs/${encodeURIComponent(est.job_activo)}`, { signal }).catch(() => null);
        activo = { id: est.job_activo, cmd: job?.cmd ?? "iniciar" };
      }
      setEstado(est);
      setInfo(resumen);
      setTermino(plazo);
      setProveedor(est.proveedor_llm ?? null);
      setTrabajo(activo);
    } catch (error) {
      if (esAbortado(error)) return;
      if (error instanceof ErrorApi && error.estado === 404) setNoExiste(true);
      setErrorCarga(error instanceof ErrorApi ? error.message : "No se pudo cargar el caso.");
    }
  }, [base, caso, nuevaSenal]);

  useEffect(() => {
    setEstado(null);
    setCambios({});
    setEdicion({});
    setTermino(null);
    setEdTermino({});
    void cargar();
  }, [cargar]);

  const ingesta: ResumenIngesta | null = estado ? ingestaDe(estado) : null;
  const autoBase = ingesta?.auto ?? AUTO_VACIO;
  // Con el historial perdido el servidor ya no acepta cambiar los roles ni el auto (borraría el fallo): solo lectura.
  const editable = Boolean(estado && (estado.estado === "revision" || estado.estado === "incompleto") && !trabajo && !estado.historial_perdido);
  const cuerpo = cuerpoRevision(cambios, autoBase, edicion);
  const nRoles = Object.keys(cambios).length;
  const porConfirmar = ingesta ? sinConfirmar(ingesta.documentos, cambios) : [];
  const nAuto = Object.keys(cambiosAuto(autoBase, edicion)).length;
  // Mientras el término es el propuesto, "Recibido el" sigue a la fecha de reparto que se está editando.
  const terminoVista = termino && conRepartoEditado(termino, edicion.fecha_reparto);
  const terminoBase = terminoVista?.termino ?? null;
  const terminoEditable = Boolean(estado && estado.estado !== "terminado" && !trabajo);
  const terminoSucio = terminoVista !== null && terminoEditado(terminoBase, edTermino);
  const errTermino = terminoSucio ? errorTermino(valoresTermino(terminoBase, edTermino)) : null;
  const partes = [
    nRoles ? plural(nRoles, "rol cambiado", "roles cambiados") : null,
    nAuto ? "datos del auto editados" : null,
    terminoSucio ? "término editado" : null,
  ].filter((p): p is string => p !== null);
  const resumenCambios = partes.length ? `${partes.length > 1 ? `${partes.slice(0, -1).join(", ")} y ${partes[partes.length - 1]}` : partes[0]}.` : null;

  const avisarError = (error: unknown, porDefecto: string) => {
    if (error instanceof ErrorApi && error.estado === 409) {
      setAviso({
        tipo: "alerta",
        texto: "Ya hay una ejecución en curso para este caso.",
        enlace: { texto: "Ver el proceso", href: hrefEtapa(caso, "proceso") },
      });
      void cargar();
      return;
    }
    setAviso({ tipo: "error", texto: error instanceof ErrorApi ? error.message : porDefecto });
  };

  /** El 409 «trabajo_previo»: la pestaña estaba desactualizada. Recarga lo que hay y pide confirmar antes de descartarlo. */
  const pedirDescarte = (error: unknown, cmd: Descarte["cmd"]): boolean => {
    if (!(error instanceof ErrorApi && error.estado === 409 && esDetalleDescarte(error.detalle))) return false;
    void cargar();
    setDescarte({ cmd, mensaje: error.detalle.mensaje });
    return true;
  };

  const recargarTermino = async (): Promise<TerminoRespuesta | null> => {
    const plazo = await api.get<TerminoRespuesta>(`${base}/termino`).catch(() => null);
    if (plazo) setTermino(plazo);
    return plazo;
  };

  const guardarTermino = async (nuevo: Termino): Promise<boolean> => {
    try {
      setTermino(await api.put<TerminoRespuesta>(`${base}/termino`, nuevo));
      setEdTermino({});
      return true;
    } catch (error) {
      if (error instanceof ErrorApi && error.estado === 422 && typeof error.detalle !== "string") {
        setAviso({ tipo: "error", texto: `El término no es válido: indique el día de recibido y un plazo de 1 a ${DIAS_MAXIMO} días.` });
      } else {
        avisarError(error, "No se pudo guardar el término.");
      }
      return false;
    }
  };

  /** Guarda lo editado. Con confirmar (al iniciar la redacción) también fija el término propuesto si el usuario no lo tocó. */
  const guardarRevision = async (confirmar = false): Promise<EstadoCaso | null> => {
    if (!estado) return null;
    if (errTermino) {
      setAviso({ tipo: "error", texto: errTermino });
      return null;
    }
    let actual: EstadoCaso = estado;
    let revisionGuardada = false;
    if (hayCambios(cuerpo)) {
      try {
        const respuesta = await api.put<EstadoCaso>(`${base}/revision`, cuerpo);
        actual = { ...respuesta, job_activo: null };
        setEstado(actual);
        setCambios({});
        setEdicion({});
        revisionGuardada = true;
      } catch (error) {
        avisarError(error, "No se pudo guardar la revisión.");
        return null;
      }
    }
    let nuevoTermino = cuerpoTermino(terminoBase, edTermino);
    let vigente = termino;
    // Los roles y la fecha de reparto cambian el término propuesto: se vuelve a pedir si el usuario no lo editó.
    if (!nuevoTermino && revisionGuardada) vigente = (await recargarTermino()) ?? termino;
    if (!nuevoTermino && confirmar && vigente?.por_defecto && vigente.termino) nuevoTermino = vigente.termino;
    if (nuevoTermino && !(await guardarTermino(nuevoTermino))) return null;
    return actual;
  };

  const guardarSoloTermino = async () => {
    setAviso(null);
    if (errTermino) {
      setAviso({ tipo: "error", texto: errTermino });
      return;
    }
    const nuevoTermino = cuerpoTermino(terminoBase, edTermino);
    if (!nuevoTermino) return;
    setGuardandoTermino(true);
    try {
      if (await guardarTermino(nuevoTermino)) mostrarToast("Término guardado.", { tipo: "ok" });
    } finally {
      setGuardandoTermino(false);
    }
  };

  const guardar = async () => {
    setAviso(null);
    setGuardando(true);
    try {
      if (await guardarRevision()) mostrarToast("Cambios guardados.", { tipo: "ok" });
    } finally {
      setGuardando(false);
    }
  };

  const faltaClave = async (): Promise<boolean> => {
    await cargarEstadoServidor(true);
    return proveedorSinClave(estadoServidor.value, proveedor) !== null;
  };

  const iniciar = async () => {
    if (iniciandoAhora.current) return;
    iniciandoAhora.current = true;
    setAviso(null);
    // La confirmación del descarte solo sobrevive a la reentrada deliberada por el diálogo de la clave.
    let reentrada = false;
    try {
      if (estado?.historial_perdido && !descarteConfirmado.current) {
        const perdido = estado.trabajo_previo?.length ? enumerar(estado.trabajo_previo) : "trabajo generado";
        setDescarte({
          cmd: "iniciar",
          mensaje: `Este caso tiene ${perdido} de una redacción anterior cuyo historial se perdió. Iniciar la redacción los descarta; ${COPIA_EN_PAPELERA}.`,
        });
        return;
      }
      if (await faltaClave()) {
        reentrada = true;
        setPidiendoClave(true);
        return;
      }
      setIniciando(true);
      const guardado = await guardarRevision(true);
      if (!guardado) return;
      if (guardado.estado !== "revision") {
        const faltan = (ingestaDe(guardado)?.faltantes ?? []).map(etiquetaRol).join(", ");
        setAviso({ tipo: "alerta", texto: `Faltan piezas obligatorias${faltan ? `: ${faltan}` : ""}. Corrija los roles para iniciar la redacción.` });
        return;
      }
      const cuerpoRun: RunCuerpo = { cmd: "iniciar", ...(descarteConfirmado.current ? { descartar: true } : {}) };
      descarteConfirmado.current = false;
      const { job_id } = await api.post<JobInicio>(`${base}/run`, cuerpoRun);
      casoActual.value = caso;
      jobActual.value = job_id;
      navegar(hrefEtapa(caso, "proceso"));
    } catch (error) {
      if (!pedirDescarte(error, "iniciar")) avisarError(error, "No se pudo iniciar la redacción.");
    } finally {
      if (!reentrada) descarteConfirmado.current = false;
      iniciandoAhora.current = false;
      setIniciando(false);
    }
  };

  const solicitarInicio = () => {
    if (iniciandoAhora.current) return;
    if (porConfirmar.length) setConfirmandoRevisar(true);
    else void iniciar();
  };

  const procesar = async (descartar = false) => {
    setProcesando(true);
    setAviso(null);
    try {
      const cuerpoRun: RunCuerpo = { cmd: "nuevo", ...(descartar ? { descartar: true } : {}) };
      const { job_id } = await api.post<JobInicio>(`${base}/run`, cuerpoRun);
      jobActual.value = job_id;
      setTrabajo({ id: job_id, cmd: "nuevo" });
    } catch (error) {
      if (!pedirDescarte(error, "nuevo")) avisarError(error, "No se pudo iniciar la lectura del expediente.");
    } finally {
      setProcesando(false);
    }
  };

  const confirmarDescarte = () => {
    if (!descarte) return;
    setDescarte(null);
    if (descarte.cmd === "nuevo") {
      void procesar(true);
    } else {
      descarteConfirmado.current = true;
      void iniciar();
    }
  };

  const cancelarDescarte = () => {
    descarteConfirmado.current = false;
    setDescarte(null);
  };

  const alTerminarLectura = (job: JobEstado | null) => {
    setTrabajo(null);
    const copia = job?.resultado?.papelera;
    if (job?.estado === "error") setAviso({ tipo: "error", texto: job.error || "La lectura del expediente falló." });
    else if (copia) {
      mostrarToast(`Expediente leído. Lo anterior se descartó y una copia del caso quedó en la papelera durante 30 días (${copia}).`, { tipo: "ok", ms: 12000 });
    } else mostrarToast("Expediente leído.", { tipo: "ok" });
    void cargar();
  };

  const cambiarRol = (doc: DocResumen, rol: RolDoc) => {
    setCambios((previo) => {
      const siguiente = { ...previo };
      if (rol === doc.rol && !doc.ajeno && !doc.revisar) delete siguiente[doc.doc_id];
      else siguiente[doc.doc_id] = rol;
      return siguiente;
    });
  };

  const conservar = (doc: DocResumen, marcado: boolean) => {
    setCambios((previo) => {
      const siguiente = { ...previo };
      const actual = previo[doc.doc_id] ?? doc.rol;
      if (marcado || actual !== doc.rol) siguiente[doc.doc_id] = actual;
      else delete siguiente[doc.doc_id];
      return siguiente;
    });
  };

  const alternar = (doc: DocResumen) => {
    setAbiertos((previo) => {
      const siguiente = new Set(previo);
      if (!siguiente.delete(doc.doc_id)) siguiente.add(doc.doc_id);
      return siguiente;
    });
  };

  const cambiarAuto = (clave: ClaveAuto, valor: string) => setEdicion((previo) => ({ ...previo, [clave]: valor }));
  const cambiarTermino = (campo: CampoTermino, valor: string) => setEdTermino((previo) => ({ ...previo, [campo]: valor }));

  const cabeza = <Cabeza caso={caso} info={info} nDocs={ingesta?.documentos.length} />;
  // El diálogo del descarte va aquí y no en una rama: tras el 409 la pantalla se recarga y puede cambiar de rama.
  const raiz = (hijos: ComponentChildren) => (
    <div data-vista="documentos" class="docs">
      {cabeza}
      {hijos}
      <DialogoDescartar
        abierto={descarte !== null}
        cmd={descarte?.cmd ?? "nuevo"}
        mensaje={descarte?.mensaje ?? ""}
        onCancelar={cancelarDescarte}
        onConfirmar={confirmarDescarte}
      />
    </div>
  );

  if (!estado && noExiste) {
    return (
      <div data-vista="documentos" class="docs">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        <CasoNoEncontrado />
      </div>
    );
  }

  if (!estado) {
    return raiz(
      errorCarga ? (
        <Aviso tipo="error" acciones={<Boton onClick={() => void cargar()}>Reintentar</Boton>}>
          {errorCarga}
        </Aviso>
      ) : (
        <Cargando texto="Cargando los documentos…" />
      ),
    );
  }

  const avisoActual = aviso && (
    <Aviso
      tipo={aviso.tipo}
      acciones={aviso.enlace && <Boton href={aviso.enlace.href}>{aviso.enlace.texto}</Boton>}
    >
      {aviso.texto}
    </Aviso>
  );

  if (trabajo?.cmd === "nuevo") {
    return raiz(
      <>
        {avisoActual}
        <Progreso jobId={trabajo.id} onFin={alTerminarLectura} />
      </>,
    );
  }

  if (!ingesta) {
    const nInsumos = info?.n_insumos;
    return raiz(
      <>
        {avisoActual}
        {estado.error && !trabajo && <Aviso tipo="error">{estado.error}</Aviso>}
        {trabajo ? (
          <Aviso tipo="info" acciones={<Boton href={hrefEtapa(caso, "proceso")}>Ver el proceso</Boton>}>
            Hay una ejecución en curso para este caso.
          </Aviso>
        ) : nInsumos === 0 ? (
          <Vacio titulo="Este caso no tiene archivos">Suba la carpeta del expediente desde la lista de casos.</Vacio>
        ) : (
          <section class="docs-bloque docs-inicio" aria-labelledby="docs-leer-t">
            <h2 id="docs-leer-t">Los documentos aún no se han leído</h2>
            <p class="sub">
              {nInsumos ? `El caso tiene ${plural(nInsumos, "archivo")}. ` : ""}Al procesarlos se lee y clasifica cada documento y se genera el auto que asume el
              conocimiento.
            </p>
            <Boton variante="primario" grande cargando={procesando} onClick={() => void procesar()}>
              Procesar los documentos
            </Boton>
          </section>
        )}
      </>,
    );
  }

  const faltantes = ingesta.faltantes;
  const esperados = ingesta.esperados_faltantes;
  const alertas = ingesta.alertas;
  const modelo = estadoServidor.value ? nombreModelo(estadoServidor.value.modelo) : null;
  const previas = salidasPrevias(estado.salidas ?? []);

  return raiz(
    <>
      {avisoActual}
      {estado.error && estado.estado === "error" && !trabajo && (
        <Aviso tipo="error" acciones={<Boton href={hrefEtapa(caso, "proceso")}>Ver el proceso</Boton>}>
          {estado.error}
        </Aviso>
      )}
      {trabajo && (
        <Aviso tipo="info" acciones={<Boton href={hrefEtapa(caso, "proceso")}>Ver el proceso</Boton>}>
          Hay una ejecución en curso para este caso.
        </Aviso>
      )}
      {estado.historial_perdido && !trabajo && (
        <Aviso
          tipo="alerta"
          titulo="Este caso perdió su historial de redacción"
          acciones={
            <Boton onClick={() => void procesar()} cargando={procesando}>
              Volver a procesar los documentos
            </Boton>
          }
        >
          Tiene {enumerar(estado.trabajo_previo ?? [])} de una redacción anterior, pero el historial que los produjo ya no está disponible. Iniciar la redacción o volver
          a procesar los documentos los descarta ({COPIA_EN_PAPELERA}); mientras tanto no se pueden cambiar los roles ni los datos del auto.
        </Aviso>
      )}
      {!editable && !trabajo && !estado.historial_perdido && <Aviso>La redacción ya inició; la clasificación de los documentos no se puede cambiar.</Aviso>}
      <div class="docs-avisos">
        <Aviso
          tipo={faltantes.length ? "alerta" : "ok"}
          titulo={faltantes.length ? "Faltan piezas obligatorias" : "Están las piezas obligatorias"}
        >
          <span class="docs-piezas">
            {OBLIGATORIOS.map((rol) => (
              <span key={rol}>
                <span aria-hidden="true">{faltantes.includes(rol) ? "✗" : "✓"}</span>
                <span class="solo-lectura">{faltantes.includes(rol) ? "Falta: " : "Está: "}</span> {etiquetaRol(rol)}
              </span>
            ))}
          </span>
          {faltantes.length > 0 && editable && (
            <span class="docs-nota">Si algún documento está mal clasificado, corrija su rol.</span>
          )}
        </Aviso>
        {esperados.length > 0 && (
          <Aviso titulo="No se encontró (se continúa sin ello)">{esperados.map(etiquetaRol).join(", ")}.</Aviso>
        )}
        {alertas.length > 0 && (
          <Aviso tipo="alerta" titulo="Alertas de la lectura">
            <ul class="docs-alertas">
              {alertas.map((texto) => (
                <li key={texto}>{texto}</li>
              ))}
            </ul>
          </Aviso>
        )}
      </div>
      <ul class="docs-lista" aria-label="Documentos del expediente">
        {ingesta.documentos.map((doc) => (
          <FilaDoc
            key={doc.doc_id}
            doc={doc}
            rol={(cambios[doc.doc_id] as RolDoc | undefined) ?? doc.rol}
            tocado={doc.doc_id in cambios}
            editable={editable}
            abierto={abiertos.has(doc.doc_id)}
            onRol={cambiarRol}
            onConservar={conservar}
            onAlternar={alternar}
          />
        ))}
      </ul>
      {nRoles > 0 && <p class="docs-ayuda">Los roles cambiados se aplican al guardar; entonces se vuelve a revisar si están las piezas obligatorias.</p>}
      <FormAuto
        base={autoBase}
        edicion={edicion}
        editable={editable}
        onCambio={cambiarAuto}
        termino={terminoVista}
        edicionTermino={edTermino}
        onCambioTermino={cambiarTermino}
        terminoEditable={terminoEditable}
        onGuardarTermino={() => void guardarSoloTermino()}
        guardandoTermino={guardandoTermino}
      />
      <Generados caso={caso} salidas={previas} />
      <Barra
        caso={caso}
        estado={estado.estado}
        enCurso={Boolean(trabajo)}
        resumenCambios={resumenCambios}
        modelo={modelo}
        guardando={guardando}
        iniciando={iniciando}
        onGuardar={() => void guardar()}
        onIniciar={solicitarInicio}
      />
      <DialogoClave
        abierto={pidiendoClave}
        proveedor={estadoServidor.value ? proveedorDelCaso(estadoServidor.value, proveedor) : "anthropic"}
        onCerrar={() => {
          setPidiendoClave(false);
          descarteConfirmado.current = false;
        }}
        onGuardada={() => {
          setPidiendoClave(false);
          void iniciar();
        }}
      />
      <DialogoRevisar
        abierto={confirmandoRevisar}
        documentos={porConfirmar}
        onVolver={() => setConfirmandoRevisar(false)}
        onContinuar={() => {
          setConfirmandoRevisar(false);
          void iniciar();
        }}
      />
    </>,
  );
}
