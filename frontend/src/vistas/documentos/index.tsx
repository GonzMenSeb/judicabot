import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { api, cancelable, ErrorApi, esAbortado } from "../../api";
import type { CasoResumen, JobInicio } from "../../api/contrato";
import { cargarEstadoServidor, estadoServidor, jobActual, casoActual, mostrarToast, nombreModelo, plural, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Migas, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import "./estilos.css";
import { Barra } from "./Barra";
import { Cabeza } from "./Cabeza";
import { DialogoClave } from "./DialogoClave";
import { DialogoRevisar } from "./DialogoRevisar";
import { FilaDoc } from "./FilaDoc";
import { FormAuto } from "./FormAuto";
import { Generados } from "./Generados";
import { Progreso } from "./Progreso";
import { cambiosAuto, cuerpoRevision, hayCambios, sinConfirmar } from "./revision";
import type { CambiosRoles, EdicionAuto } from "./revision";
import { OBLIGATORIOS, etiquetaRol, ingestaDe, salidasPrevias } from "./tipos";
import type { ClaveAuto, ConfigCaso, DatosAuto, DocResumen, EstadoCaso, JobEstado, ResumenIngesta, RolDoc } from "./tipos";

interface AvisoVista {
  tipo: "alerta" | "error" | "info";
  texto: string;
  enlace?: { texto: string; href: string };
}

interface Trabajo {
  id: string;
  cmd: JobEstado["cmd"];
}

const AUTO_VACIO: DatosAuto = { fecha: null, fecha_reparto: null, accionante: null, accionada: null, firmante: null, cargo_firmante: null };

const hrefEtapa = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

export default function Documentos({ caso }: PropsVista) {
  if (!caso) return <Vacio titulo="Falta indicar el caso" />;
  return <VistaDocumentos caso={caso} />;
}

function VistaDocumentos({ caso }: { caso: string }) {
  const [estado, setEstado] = useState<EstadoCaso | null>(null);
  const [info, setInfo] = useState<CasoResumen | null>(null);
  const [proveedor, setProveedor] = useState<string | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [noExiste, setNoExiste] = useState(false);
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [cambios, setCambios] = useState<CambiosRoles>({});
  const [edicion, setEdicion] = useState<EdicionAuto>({});
  const [abiertos, setAbiertos] = useState<ReadonlySet<string>>(new Set());
  const [aviso, setAviso] = useState<AvisoVista | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [iniciando, setIniciando] = useState(false);
  const [procesando, setProcesando] = useState(false);
  const [pidiendoClave, setPidiendoClave] = useState(false);
  const [confirmandoRevisar, setConfirmandoRevisar] = useState(false);
  const nuevaSenal = useRef(cancelable()).current;
  const iniciandoAhora = useRef(false);
  const base = `/api/casos/${encodeURIComponent(caso)}`;

  useTitulo(`Documentos · ${info?.nombre ?? caso}`);

  const cargar = useCallback(async () => {
    const signal = nuevaSenal();
    setErrorCarga(null);
    setNoExiste(false);
    try {
      const [est, resumen, cfg] = await Promise.all([
        api.get<EstadoCaso>(`${base}/estado`, { signal }),
        api.get<CasoResumen>(`${base}/resumen`, { signal }).catch(() => null),
        api.get<ConfigCaso>(`${base}/config`, { signal }).catch(() => null),
      ]);
      let activo: Trabajo | null = null;
      if (est.job_activo) {
        const job = await api.get<JobEstado>(`/api/jobs/${encodeURIComponent(est.job_activo)}`, { signal }).catch(() => null);
        activo = { id: est.job_activo, cmd: job?.cmd ?? "iniciar" };
      }
      setEstado(est);
      setInfo(resumen);
      setProveedor(cfg?.llm?.proveedor ?? null);
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
    void cargar();
  }, [cargar]);

  const ingesta: ResumenIngesta | null = estado ? ingestaDe(estado) : null;
  const autoBase = ingesta?.auto ?? AUTO_VACIO;
  const editable = Boolean(estado && (estado.estado === "revision" || estado.estado === "incompleto") && !trabajo);
  const cuerpo = cuerpoRevision(cambios, autoBase, edicion);
  const nRoles = Object.keys(cambios).length;
  const porConfirmar = ingesta ? sinConfirmar(ingesta.documentos, cambios) : [];
  const nAuto = Object.keys(cambiosAuto(autoBase, edicion)).length;
  const partes = [nRoles ? plural(nRoles, "rol cambiado", "roles cambiados") : null, nAuto ? "datos del auto editados" : null].filter(Boolean);
  const resumenCambios = partes.length ? `${partes.join(" y ")}.` : null;

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

  const guardarRevision = async (): Promise<EstadoCaso | null> => {
    if (!estado) return null;
    if (!hayCambios(cuerpo)) return estado;
    try {
      const respuesta = await api.put<EstadoCaso>(`${base}/revision`, cuerpo);
      const nuevo = { ...respuesta, job_activo: null };
      setEstado(nuevo);
      setCambios({});
      setEdicion({});
      return nuevo;
    } catch (error) {
      avisarError(error, "No se pudo guardar la revisión.");
      return null;
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
    const servidor = estadoServidor.value;
    return Boolean(servidor) && !servidor?.api_key && proveedor !== "fake";
  };

  const iniciar = async () => {
    if (iniciandoAhora.current) return;
    iniciandoAhora.current = true;
    setAviso(null);
    try {
      if (await faltaClave()) {
        setPidiendoClave(true);
        return;
      }
      setIniciando(true);
      const guardado = await guardarRevision();
      if (!guardado) return;
      if (guardado.estado !== "revision") {
        const faltan = (ingestaDe(guardado)?.faltantes ?? []).map(etiquetaRol).join(", ");
        setAviso({ tipo: "alerta", texto: `Faltan piezas obligatorias${faltan ? `: ${faltan}` : ""}. Corrija los roles para iniciar la redacción.` });
        return;
      }
      const { job_id } = await api.post<JobInicio>(`${base}/run`, { cmd: "iniciar" });
      casoActual.value = caso;
      jobActual.value = job_id;
      navegar(hrefEtapa(caso, "proceso"));
    } catch (error) {
      avisarError(error, "No se pudo iniciar la redacción.");
    } finally {
      iniciandoAhora.current = false;
      setIniciando(false);
    }
  };

  const solicitarInicio = () => {
    if (iniciandoAhora.current) return;
    if (porConfirmar.length) setConfirmandoRevisar(true);
    else void iniciar();
  };

  const procesar = async () => {
    setProcesando(true);
    setAviso(null);
    try {
      const { job_id } = await api.post<JobInicio>(`${base}/run`, { cmd: "nuevo" });
      jobActual.value = job_id;
      setTrabajo({ id: job_id, cmd: "nuevo" });
    } catch (error) {
      avisarError(error, "No se pudo iniciar la lectura del expediente.");
    } finally {
      setProcesando(false);
    }
  };

  const alTerminarLectura = (job: JobEstado | null) => {
    setTrabajo(null);
    if (job?.estado === "error") setAviso({ tipo: "error", texto: job.error || "La lectura del expediente falló." });
    else mostrarToast("Expediente leído.", { tipo: "ok" });
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

  const cabeza = <Cabeza caso={caso} info={info} nDocs={ingesta?.documentos.length} />;
  const raiz = (hijos: ComponentChildren) => (
    <div data-vista="documentos" class="docs">
      {cabeza}
      {hijos}
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
      {estado.error && estado.estado === "error" && (
        <Aviso tipo="error" acciones={<Boton href={hrefEtapa(caso, "proceso")}>Ver el proceso</Boton>}>
          {estado.error}
        </Aviso>
      )}
      {trabajo && (
        <Aviso tipo="info" acciones={<Boton href={hrefEtapa(caso, "proceso")}>Ver el proceso</Boton>}>
          Hay una ejecución en curso para este caso.
        </Aviso>
      )}
      {!editable && !trabajo && <Aviso>La redacción ya inició; la clasificación de los documentos no se puede cambiar.</Aviso>}
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
      <FormAuto base={autoBase} edicion={edicion} editable={editable} onCambio={cambiarAuto} />
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
        onCerrar={() => setPidiendoClave(false)}
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
