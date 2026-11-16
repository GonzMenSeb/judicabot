import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado, esCasoNoEncontrado } from "../../api";
import type { Vista } from "../../api/contrato";
import { casoActual, jobActual, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Chip, Migas, Pasos, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import "./estilos.css";
import {
  claveRevisados,
  comportamientoScroll,
  construirIndice,
  construirRevision,
  dividirMotivos,
  filasJev,
  guardarRevisados,
  irA,
  leerRevisados,
  limitePasos,
  marcasDelIndice,
  redaccionPorNodo,
  seccionesDeCitas,
  tituloDelCaso,
} from "./datos";
import { DialogoCorrecciones } from "./DialogoCorrecciones";
import { Dock } from "./Dock";
import { Documento } from "./Documento";
import { Indice } from "./Indice";
import { PanelRevision } from "./PanelRevision";
import { PopoverCita } from "./PopoverCita";
import type { EstadoCaso } from "./tipos";
import { useEspia } from "./useEspia";

type Fase = "cargando" | "listo" | "no_existe" | "error";

const enlaceEtapa = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

const ESPERA_DESPLAZAMIENTO = 380;
const VACIO: ReadonlySet<string> = new Set();

function motivoNoCorregir(estado: EstadoCaso | null, cargado: boolean): string | null {
  if (!cargado) return "No se pudo comprobar el estado del caso.";
  if (!estado) return null;
  if (estado.job_activo || estado.estado === "corriendo") return "Hay una redacción en curso para este caso.";
  if (estado.estado !== "esperando_decision") return "Solo se pueden pedir correcciones mientras el caso espera su decisión.";
  return null;
}

function IconoNumeral() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
      <path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16" />
    </svg>
  );
}

function IconoJuzgado() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M3 21h18M5 21V10M19 21V10M9 21v-7M15 21v-7M2 10l10-6 10 6z" />
    </svg>
  );
}

export default function Borrador({ caso }: PropsVista) {
  const [fase, setFase] = useState<Fase>("cargando");
  const [vista, setVista] = useState<Vista | null>(null);
  const [errorVista, setErrorVista] = useState<string | null>(null);
  const [estado, setEstado] = useState<EstadoCaso | null>(null);
  const [estadoFallo, setEstadoFallo] = useState(false);
  const [sinCaso, setSinCaso] = useState(false);
  const [intento, setIntento] = useState(0);
  const [seleccionada, setSeleccionada] = useState<string | null>(null);
  const [ancla, setAncla] = useState<HTMLElement | null>(null);
  const [plantilla, setPlantilla] = useState(true);
  const [guardados, setGuardados] = useState<{ clave: string; revisados: ReadonlySet<string> } | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [indiceAbierto, setIndiceAbierto] = useState(false);
  const [panelAbierto, setPanelAbierto] = useState(false);
  const [corrigiendo, setCorrigiendo] = useState(false);
  const tituloDetalle = useRef<HTMLHeadingElement>(null);
  const disparador = useRef<HTMLElement | null>(null);
  const columna = useRef<HTMLDivElement>(null);
  const botonIndice = useRef<HTMLButtonElement>(null);
  const botonPanel = useRef<HTMLButtonElement>(null);
  const espera = useRef(0);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    const base = `/api/casos/${encodeURIComponent(caso)}`;
    setFase("cargando");
    setEstado(null);
    setEstadoFallo(false);
    setSinCaso(false);
    setSeleccionada(null);
    setAncla(null);
    setAbierta(null);
    api.get<Vista>(`${base}/vista/borrador`, { signal: control.signal }).then(
      (datos) => {
        setVista(datos);
        setFase("listo");
      },
      (e: unknown) => {
        if (esAbortado(e)) return;
        if (esCasoNoEncontrado(e)) setSinCaso(true);
        if (e instanceof ErrorApi && e.estado === 404) {
          setFase("no_existe");
          return;
        }
        setErrorVista(e instanceof ErrorApi ? e.message : "No se pudo conectar con el servidor.");
        setFase("error");
      },
    );
    api.get<EstadoCaso>(`${base}/estado`, { signal: control.signal }).then(
      (datos) => setEstado(datos),
      (e: unknown) => {
        if (esAbortado(e)) return;
        if (e instanceof ErrorApi && e.estado === 404) setSinCaso(true);
        else setEstadoFallo(true);
      },
    );
    return () => control.abort();
  }, [caso, intento]);

  useEffect(() => () => window.clearTimeout(espera.current), []);

  const resumen = estado?.resumen ?? null;
  const metadatos = resumen?.metadatos ?? null;
  const nombre = caso ? tituloDelCaso(caso, metadatos) : "";
  useTitulo(caso ? `Borrador · ${nombre}` : null);

  const citas = vista?.citas;
  const citasPorId = useMemo(() => new Map((citas ?? []).map((c) => [c.id, c])), [citas]);
  const entradas = useMemo(() => (vista ? construirIndice(vista) : []), [vista]);
  const idsIndice = useMemo(() => entradas.map((e) => e.id), [entradas]);
  const marcas = useMemo(() => (vista ? marcasDelIndice(vista) : {}), [vista]);
  const secciones = useMemo(() => (vista ? seccionesDeCitas(vista) : {}), [vista]);
  const activa = useEspia(idsIndice);
  const filas = useMemo(() => filasJev(resumen?.jev_metadatos, metadatos), [resumen, metadatos]);
  const items = useMemo(() => construirRevision(citas ?? [], resumen?.alertas, filas, secciones), [citas, resumen, filas, secciones]);
  const redaccion = useMemo(() => redaccionPorNodo(resumen?.bitacora), [resumen]);

  const clave = caso && vista ? claveRevisados(caso, vista.sha256) : null;
  const revisados = useMemo(
    () => (guardados && guardados.clave === clave ? guardados.revisados : clave ? leerRevisados(clave) : VACIO),
    [guardados, clave],
  );
  const pendientes = items.filter((i) => i.nivel !== "ok");
  const hechos = pendientes.filter((i) => revisados.has(i.clave)).length;
  const quedan = pendientes.length - hechos;

  const cita = seleccionada ? (citasPorId.get(seleccionada) ?? null) : null;
  const motivos = useMemo(() => dividirMotivos(cita?.detalle ?? null), [cita]);

  const alRevisar = useCallback(
    (k: string) => {
      if (!clave) return;
      const siguiente = new Set(revisados);
      if (!siguiente.delete(k)) siguiente.add(k);
      guardarRevisados(clave, siguiente);
      setGuardados({ clave, revisados: siguiente });
    },
    [clave, revisados],
  );

  const elegirCita = useCallback(
    (id: string, desde: HTMLElement) => {
      window.clearTimeout(espera.current);
      disparador.current = desde;
      if (seleccionada === id && ancla === desde) {
        setSeleccionada(null);
        setAncla(null);
        return;
      }
      setSeleccionada(id);
      setAncla(desde);
    },
    [seleccionada, ancla],
  );

  const verEnTexto = useCallback((id: string, desde: HTMLElement) => {
    window.clearTimeout(espera.current);
    disparador.current = desde;
    const marcasTexto = columna.current?.querySelectorAll<HTMLElement>("[data-cita]") ?? [];
    const marca = Array.from(marcasTexto).find((m) => m.dataset["cita"] === id) ?? null;
    const enCajon = desde.closest("#bor-panel.abierto") !== null;
    setSeleccionada(marca ? id : null);
    setAncla(null);
    if (enCajon) {
      setPanelAbierto(false);
      (marca ?? botonPanel.current)?.focus({ preventScroll: true });
    }
    if (!marca) return;
    irA(marca, "center");
    const retraso = comportamientoScroll() === "smooth" ? ESPERA_DESPLAZAMIENTO : 0;
    espera.current = window.setTimeout(() => {
      marca.classList.remove("destello");
      void marca.offsetWidth;
      marca.classList.add("destello");
      setAncla(marca);
    }, retraso);
  }, []);

  const cerrarDetalle = useCallback(
    (devolverFoco: boolean) => {
      window.clearTimeout(espera.current);
      const destino = ancla?.isConnected ? ancla : disparador.current?.isConnected ? disparador.current : null;
      setSeleccionada(null);
      setAncla(null);
      if (devolverFoco) destino?.focus({ preventScroll: true });
    },
    [ancla],
  );

  const cerrarPanel = useCallback((devolverFoco: boolean) => {
    setPanelAbierto(false);
    if (devolverFoco) botonPanel.current?.focus();
  }, []);

  useEffect(() => {
    if (cita && ancla) tituloDetalle.current?.focus({ preventScroll: true });
  }, [cita, ancla]);

  useEffect(() => {
    if (panelAbierto) document.querySelector<HTMLElement>("#bor-panel .bor-panel-cerrar")?.focus();
  }, [panelAbierto]);

  useEffect(() => {
    const alTeclado = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (seleccionada) cerrarDetalle(true);
      else if (indiceAbierto) {
        setIndiceAbierto(false);
        botonIndice.current?.focus();
      } else if (panelAbierto) cerrarPanel(true);
    };
    const alClic = (e: MouseEvent) => {
      const destino = e.target instanceof Element ? e.target : null;
      if (!destino) return;
      if (seleccionada && !destino.closest("#bor-detalle, [data-cita], #bor-panel")) cerrarDetalle(false);
      if (indiceAbierto && !destino.closest("#bor-indice, [aria-controls='bor-indice']")) setIndiceAbierto(false);
    };
    document.addEventListener("keydown", alTeclado);
    document.addEventListener("click", alClic);
    return () => {
      document.removeEventListener("keydown", alTeclado);
      document.removeEventListener("click", alClic);
    };
  }, [seleccionada, indiceAbierto, panelAbierto, cerrarDetalle, cerrarPanel]);

  useEffect(() => {
    if (!panelAbierto && !indiceAbierto) return;
    const alRedimensionar = () => {
      if (window.innerWidth >= 1024) {
        if (document.activeElement?.closest("#bor-panel")) document.getElementById("bor-panel-titulo")?.focus({ preventScroll: true });
        setPanelAbierto(false);
      }
      if (window.innerWidth >= 1280) setIndiceAbierto(false);
    };
    window.addEventListener("resize", alRedimensionar);
    return () => window.removeEventListener("resize", alRedimensionar);
  }, [panelAbierto, indiceAbierto]);

  useEffect(() => {
    if (!indiceAbierto) return;
    const lista = document.querySelectorAll<HTMLElement>("#bor-indice .bor-indice-lista button");
    (Array.from(lista).find((b) => b.getAttribute("aria-current") === "location") ?? lista[0])?.focus({ preventScroll: true });
  }, [indiceAbierto]);

  const alSeccion = useCallback((id: string) => {
    setIndiceAbierto(false);
    if (window.innerWidth < 1280) botonIndice.current?.focus({ preventScroll: true });
    irA(document.getElementById(`b-${id}`));
  }, []);

  if (!caso) return <Vacio titulo="Falta el caso">Abra el borrador desde la lista de casos.</Vacio>;

  const sinEstado = estado === null;
  const motivo = motivoNoCorregir(estado, !estadoFallo);
  const corrigible = !sinEstado && motivo === null;
  const enCurso = Boolean(estado?.job_activo) || estado?.estado === "corriendo";
  const radicado = metadatos?.cui_2a || metadatos?.cui_1a;

  const cabecera = (
    <>
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <div class="bor-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {(radicado || metadatos?.juzgado_a_quo) && (
          <div class="bor-meta">
            {radicado && (
              <span>
                <IconoNumeral />
                Radicado {radicado}
              </span>
            )}
            {metadatos?.juzgado_a_quo && (
              <span>
                <IconoJuzgado />
                {metadatos.juzgado_a_quo}
              </span>
            )}
          </div>
        )}
      </div>
      <Pasos caso={caso} actual="borrador" limite={limitePasos(estado)} detalles={{ borrador: "Revise antes de decidir" }} />
    </>
  );

  if (fase === "cargando") {
    return (
      <div data-vista="borrador" class="borrador">
        {cabecera}
        <Cargando texto="Cargando el borrador…" />
      </div>
    );
  }

  if (sinCaso && (fase === "no_existe" || fase === "error")) {
    return (
      <div data-vista="borrador" class="borrador">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        <CasoNoEncontrado />
      </div>
    );
  }

  if (fase === "no_existe" || fase === "error" || !vista) {
    const sinBorrador = fase === "no_existe";
    return (
      <div data-vista="borrador" class="borrador">
        {cabecera}
        {sinBorrador ? (
          <Vacio
            titulo="El borrador aún no está listo"
            accion={
              <>
                <Boton variante="primario" href={enlaceEtapa(caso, "proceso")}>
                  Ver el proceso
                </Boton>
                <Boton href={enlaceEtapa(caso, "documentos")}>Volver a documentos</Boton>
              </>
            }
          >
            Se genera cuando termina la redacción de las secciones I a V.
          </Vacio>
        ) : (
          <Aviso
            tipo="error"
            titulo="No se pudo cargar el borrador"
            acciones={<Boton onClick={() => setIntento(intento + 1)}>Reintentar</Boton>}
          >
            {errorVista}
          </Aviso>
        )}
      </div>
    );
  }

  const indiceActual = entradas.findIndex((e) => e.id === activa);
  const actual = indiceActual >= 0 ? entradas[indiceActual] : undefined;
  const padre = actual?.sub ? entradas.slice(0, indiceActual).reverse().find((e) => !e.sub) : undefined;

  return (
    <div data-vista="borrador" class="borrador">
      {cabecera}
      {enCurso && (
        <Aviso
          tipo="info"
          class="bor-aviso"
          acciones={
            <Boton href={enlaceEtapa(caso, "proceso")} variante="primario">
              Ver el proceso
            </Boton>
          }
        >
          Hay una redacción en curso para este caso. El borrador puede cambiar cuando termine.
        </Aviso>
      )}
      <div class="bor-mesa">
        <Indice entradas={entradas} marcas={marcas} activa={activa} alSeccion={alSeccion} redaccion={redaccion} abierto={indiceAbierto} />
        <div class="bor-col-doc" ref={columna}>
          <div class="bor-doc-barra">
            <button
              type="button"
              class="bor-boton-icono bor-solo-medio"
              ref={botonIndice}
              aria-expanded={indiceAbierto}
              aria-controls="bor-indice"
              onClick={() => setIndiceAbierto((a) => !a)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                <path d="M4 6h16M4 12h16M4 18h10" />
              </svg>
              Contenido
            </button>
            <span class="bor-doc-actual">
              {actual && (padre ? <><b>{padre.titulo}</b> · {actual.titulo}</> : <b>{actual.titulo}</b>)}
            </span>
            <label
              class="bor-interruptor"
              title="Marca el texto fijo que sale de la plantilla. Lo que queda sin marca lo redactó el modelo a partir del expediente."
            >
              <input type="checkbox" role="switch" aria-label="Marcar texto de plantilla" checked={plantilla} onChange={(e) => setPlantilla(e.currentTarget.checked)} />
              <span class="bor-pista" aria-hidden="true" />
              <span class="bor-muestra" aria-hidden="true" />
              <span>
                <span class="bor-txt-largo">Marcar texto de</span> plantilla
              </span>
            </label>
            <button
              type="button"
              class="bor-boton-icono bor-solo-angosto"
              ref={botonPanel}
              aria-expanded={panelAbierto}
              aria-controls="bor-panel"
              onClick={() => setPanelAbierto(true)}
            >
              Revisión <Chip tono={quedan > 0 ? "alerta" : "ok"}>{quedan}</Chip>
            </button>
          </div>
          <h2 class="solo-lectura">Texto del borrador</h2>
          <Documento vista={vista} citas={citasPorId} seleccionada={seleccionada} plantilla={plantilla} alCita={elegirCita} />
          {cita && ancla && columna.current && (
            <PopoverCita
              cita={cita}
              motivos={motivos}
              ancla={ancla}
              contenedor={columna.current}
              titulo={tituloDetalle}
              onCerrar={() => cerrarDetalle(true)}
            />
          )}
        </div>
        <PanelRevision
          items={items}
          revisados={revisados}
          alRevisar={alRevisar}
          abierta={abierta}
          alAbrir={setAbierta}
          seleccionada={seleccionada}
          alVerEnTexto={verEnTexto}
          umbralJev={resumen?.jev_metadatos?.umbral}
          alertasLeidas={estado !== null}
          avisoEstado={estadoFallo ? "No se pudieron leer las alertas del caso; se muestran solo las citas." : null}
          abiertoMovil={panelAbierto}
          onCerrarMovil={() => cerrarPanel(true)}
        />
      </div>
      <div class="bor-velo" hidden={!panelAbierto} onClick={() => cerrarPanel(true)} />
      <Dock
        pendientes={quedan}
        revisados={hechos}
        total={pendientes.length}
        alertas={estado ? "listo" : estadoFallo ? "fallo" : "cargando"}
        enCurso={enCurso}
        hrefDecision={enlaceEtapa(caso, "decision")}
        puedeCorregir={corrigible}
        motivoNoCorregir={motivo}
        alCorregir={() => setCorrigiendo(true)}
      />
      <DialogoCorrecciones
        abierto={corrigiendo}
        caso={caso}
        onCerrar={() => setCorrigiendo(false)}
        onEnviado={(jobId) => {
          casoActual.value = caso;
          jobActual.value = jobId;
          setCorrigiendo(false);
          navegar(enlaceEtapa(caso, "proceso"));
        }}
      />
    </div>
  );
}
