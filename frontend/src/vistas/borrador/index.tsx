import type { ComponentType } from "preact";
import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado, esCasoNoEncontrado } from "../../api";
import type { AjusteCuerpo, EdicionesRespuesta, Vista } from "../../api/contrato";
import { casoActual, jobActual, mostrarToast, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Chip, cx, Dialogo, Migas, Pasos, Vacio } from "../../ui";
import { useGuardiaSalida } from "../formato/guardia";
import type { PropsVista } from "../tipos";
import "./estilos.css";
import {
  apoderadosEnTexto,
  bloqueantes,
  claveApoderado,
  type DocumentoConocido,
  documentosConocidos,
  idDeClave,
  itemsApoderados,
  mensajeBloqueo,
  puedeReintentar,
  revisadosDelServidor,
} from "./apoderados";
import { mensajeError } from "../casos/subida";
import type { PropsDialogoAjuste } from "./DialogoAjuste";
import {
  claveRevisados,
  comportamientoScroll,
  construirIndice,
  construirRevision,
  dividirMotivos,
  filasJev,
  guardarCorreccionVista,
  guardarRevisados,
  irA,
  leerCorreccionVista,
  leerRevisados,
  limitePasos,
  marcasDelIndice,
  redaccionPorNodo,
  resumirInstruccion,
  seccionesDeCitas,
  tituloDelCaso,
} from "./datos";
import type { PropsDialogoConflictos } from "./DialogoConflictos";
import type { PropsDialogoCorrecciones } from "./DialogoCorrecciones";
import "./dialogo.css";
import { Dock } from "./Dock";
import { Documento } from "./Documento";
import { Indice } from "./Indice";
import { PanelRevision } from "./PanelRevision";
import type { PropsPopoverApoderado } from "./PopoverApoderado";
import { PopoverCita } from "./PopoverCita";
import type { EstadoCaso, PedidoAjuste, PedidoVisor, Pestana, Seleccion } from "./tipos";
import { useApoderados } from "./useApoderados";
import { useEspia } from "./useEspia";
import type { PropsVisorEvidencia } from "./VisorEvidencia";

type Fase = "cargando" | "listo" | "no_existe" | "error";

const enlaceEtapa = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

const ESPERA_DESPLAZAMIENTO = 380;
const VACIO: ReadonlySet<string> = new Set();
const MARCAS_TEXTO = "[data-cita],[data-apoderado]";

const mismaSeleccion = (a: Seleccion | null, b: Seleccion): boolean => a !== null && a.tipo === b.tipo && a.id === b.id;

/** Un componente que viaja en su propio chunk: se descarga la primera vez que se pide y, si falla, el próximo intento lo vuelve a pedir. */
function perezoso<P>(importar: () => Promise<ComponentType<P>>): () => Promise<ComponentType<P>> {
  let pendiente: Promise<ComponentType<P>> | null = null;
  return () =>
    (pendiente ??= importar().catch((e: unknown) => {
      pendiente = null;
      throw e;
    }));
}

// El visor de evidencia (con su hoja de estilos), el detalle de un abogado y los diálogos de corregir viajan aparte:
// solo se descargan al abrirlos (el detalle, en cuanto el texto tiene nombres marcados).
const cargarDetalleApoderado = perezoso(() => import("./PopoverApoderado").then((m) => m.PopoverApoderado));
const cargarVisor = perezoso(() => import("./VisorEvidencia").then((m) => m.default));
const cargarAjuste = perezoso(() => import("./DialogoAjuste").then((m) => m.default));
const cargarCorrecciones = perezoso(() => import("./DialogoCorrecciones").then((m) => m.DialogoCorrecciones));
const cargarConflictos = perezoso(() => import("./DialogoConflictos").then((m) => m.DialogoConflictos));

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
  const [seleccionada, setSeleccionada] = useState<Seleccion | null>(null);
  const [ancla, setAncla] = useState<HTMLElement | null>(null);
  const [plantilla, setPlantilla] = useState(true);
  const [guardados, setGuardados] = useState<{ clave: string; revisados: ReadonlySet<string> } | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [indiceAbierto, setIndiceAbierto] = useState(false);
  const [panelAbierto, setPanelAbierto] = useState(false);
  const [corrigiendo, setCorrigiendo] = useState(false);
  const [pestana, setPestana] = useState<Pestana>("citas");
  const [visor, setVisor] = useState<PedidoVisor | null>(null);
  const [Visor, setVisorCargado] = useState<ComponentType<PropsVisorEvidencia> | null>(null);
  const [errorVisor, setErrorVisor] = useState(false);
  const [ajuste, setAjuste] = useState<PedidoAjuste | null>(null);
  const [DialogoAjuste, setDialogoAjuste] = useState<ComponentType<PropsDialogoAjuste> | null>(null);
  const [DialogoCorrecciones, setDialogoCorrecciones] = useState<ComponentType<PropsDialogoCorrecciones> | null>(null);
  const [DialogoConflictos, setDialogoConflictos] = useState<ComponentType<PropsDialogoConflictos> | null>(null);
  const [PopoverApoderado, setPopoverApoderado] = useState<ComponentType<PropsPopoverApoderado> | null>(null);
  const [ediciones, setEdiciones] = useState<EdicionesRespuesta | null>(null);
  const [editando, setEditando] = useState(false);
  const [resolviendo, setResolviendo] = useState(false);
  const [sucio, setSucio] = useState(false);
  const [apagando, setApagando] = useState(false);
  // La corrección cuyo aviso se cerró en esta pantalla; además queda guardada en el navegador (si este lo permite).
  const [correccionCerrada, setCorreccionCerrada] = useState<{ caso: string; fecha: string } | null>(null);
  const guardia = useGuardiaSalida(sucio);
  const recarga = useRef<AbortController | null>(null);
  // Vuelve a leer el borrador previo, las ediciones y el estado sin pasar por la pantalla de carga: tras guardar una
  // edición, resolver un conflicto o identificar a los apoderados de un caso anterior (el previo sale con los nombres marcados).
  const recargar = useCallback(async () => {
    if (!caso) return;
    const base = `/api/casos/${encodeURIComponent(caso)}`;
    recarga.current?.abort();
    const control = new AbortController();
    recarga.current = control;
    const { signal } = control;
    const [nueva, edicion, actual] = await Promise.allSettled([
      api.get<Vista>(`${base}/vista/borrador`, { signal }),
      api.get<EdicionesRespuesta>(`${base}/ediciones`, { signal }),
      api.get<EstadoCaso>(`${base}/estado`, { signal }),
    ]);
    if (signal.aborted) return;
    if (nueva.status === "fulfilled") setVista(nueva.value);
    if (edicion.status === "fulfilled") setEdiciones(edicion.value);
    if (actual.status === "fulfilled") {
      setEstado(actual.value);
      setEstadoFallo(false);
    }
  }, [caso]);
  const apoderados = useApoderados(caso, recargar);
  const abridorAjuste = useRef<HTMLElement | null>(null);
  const documentosVistos = useRef(new Map<string, DocumentoConocido>());
  const tituloDetalle = useRef<HTMLHeadingElement>(null);
  const disparador = useRef<HTMLElement | null>(null);
  const abridorVisor = useRef<HTMLElement | null>(null);
  const columna = useRef<HTMLDivElement>(null);
  const botonIndice = useRef<HTMLButtonElement>(null);
  const botonPanel = useRef<HTMLButtonElement>(null);
  const espera = useRef(0);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    const base = `/api/casos/${encodeURIComponent(caso)}`;
    recarga.current?.abort();
    setFase("cargando");
    setEstado(null);
    setEstadoFallo(false);
    setSinCaso(false);
    setSeleccionada(null);
    setAncla(null);
    setAbierta(null);
    setVisor(null);
    setAjuste(null);
    documentosVistos.current = new Map();
    setEdiciones(null);
    setEditando(false);
    setResolviendo(false);
    setApagando(false);
    setSucio(false);
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
    api.get<EdicionesRespuesta>(`${base}/ediciones`, { signal: control.signal }).then(
      (datos) => setEdiciones(datos),
      () => undefined,
    );
    return () => {
      control.abort();
      recarga.current?.abort();
    };
  }, [caso, intento]);

  useEffect(() => () => window.clearTimeout(espera.current), []);

  useEffect(() => {
    if (!corrigiendo || DialogoCorrecciones) return;
    cargarCorrecciones().then(
      (componente) => setDialogoCorrecciones(() => componente),
      () => {
        setCorrigiendo(false);
        mostrarToast("No se pudo abrir el pedido de correcciones. Revise la conexión y vuelva a intentarlo.", { tipo: "error" });
      },
    );
  }, [corrigiendo, DialogoCorrecciones]);

  // Con conflictos pendientes el diálogo para resolverlos se descarga de antemano: el aviso invita a abrirlo.
  const hayConflictos = ediciones?.editable === true && ediciones.conflictos.length > 0;
  useEffect(() => {
    if ((!hayConflictos && !resolviendo) || DialogoConflictos) return;
    cargarConflictos().then(
      (componente) => setDialogoConflictos(() => componente),
      () => {
        if (!resolviendo) return;
        setResolviendo(false);
        mostrarToast("No se pudo abrir la resolución de conflictos. Revise la conexión y vuelva a intentarlo.", { tipo: "error" });
      },
    );
  }, [hayConflictos, resolviendo, DialogoConflictos]);

  const resumen = estado?.resumen ?? null;
  const metadatos = resumen?.metadatos ?? null;
  const nombre = caso ? tituloDelCaso(caso, metadatos) : "";
  useTitulo(caso ? `Borrador · ${nombre}` : null);

  const citas = vista?.citas;
  const citasPorId = useMemo(() => new Map((citas ?? []).map((c) => [c.id, c])), [citas]);
  const entradas = useMemo(() => (vista ? construirIndice(vista) : []), [vista]);
  const idsIndice = useMemo(() => entradas.map((e) => e.id), [entradas]);
  const datosApoderados = apoderados.datos;
  const apoderadosPorId = useMemo(() => new Map((datosApoderados?.apoderados ?? []).map((a) => [a.id, a])), [datosApoderados]);
  const marcas = useMemo(() => (vista ? marcasDelIndice(vista, apoderadosPorId) : {}), [vista, apoderadosPorId]);
  const secciones = useMemo(() => (vista ? seccionesDeCitas(vista) : {}), [vista]);
  const activa = useEspia(idsIndice);
  const filas = useMemo(() => filasJev(resumen?.jev_metadatos, metadatos), [resumen, metadatos]);
  const enTexto = useMemo(() => (vista ? apoderadosEnTexto(vista) : VACIO), [vista]);
  // Un nombre solo se marca cuando /apoderados trajo a su abogado: sin marcas no hay nada que explicar.
  const conMarcas = useMemo(() => [...enTexto].some((id) => apoderadosPorId.has(id)), [enTexto, apoderadosPorId]);
  const items = useMemo(
    () => [...construirRevision(citas ?? [], resumen?.alertas, filas, secciones), ...itemsApoderados(datosApoderados)],
    [citas, resumen, filas, secciones, datosApoderados],
  );
  const redaccion = useMemo(() => redaccionPorNodo(resumen?.bitacora), [resumen]);

  const clave = caso ? claveRevisados(caso) : null;
  const alertasLeidas = estado?.resumen?.alertas != null;
  const vigentes = useMemo(() => (alertasLeidas ? new Set(items.map((i) => i.clave)) : undefined), [alertasLeidas, items]);
  const locales = useMemo(
    () => (guardados && guardados.clave === clave ? guardados.revisados : clave ? leerRevisados(clave, vigentes) : VACIO),
    [guardados, clave, vigentes],
  );
  const revisados = useMemo(() => {
    const delServidor = revisadosDelServidor(datosApoderados);
    return delServidor.length === 0 ? locales : new Set([...locales, ...delServidor]);
  }, [locales, datosApoderados]);
  const pendientes = items.filter((i) => i.nivel !== "ok");
  const hechos = pendientes.filter((i) => revisados.has(i.clave)).length;
  const quedan = pendientes.length - hechos;

  const cita = seleccionada?.tipo === "cita" ? (citasPorId.get(seleccionada.id) ?? null) : null;
  const abogado = seleccionada?.tipo === "apoderado" ? (apoderadosPorId.get(seleccionada.id) ?? null) : null;
  const motivos = useMemo(() => dividirMotivos(cita?.detalle ?? null), [cita]);
  const apoderadosEditables = datosApoderados?.editable ?? false;

  const revisarApoderado = apoderados.revisar;
  const subirCertificado = apoderados.subir;
  const { ajustar, consultar } = apoderados;
  // Los documentos que el borrador vio en las evidencias, también los de un poder ya descartado: entre ellos se elige el poder a mano.
  for (const d of documentosConocidos(datosApoderados)) documentosVistos.current.set(d.doc_id, d);
  const alRevisar = useCallback(
    (k: string) => {
      const id = idDeClave(k);
      if (id !== null) {
        const apoderado = datosApoderados?.apoderados.find((a) => a.id === id);
        if (apoderado && datosApoderados?.editable) revisarApoderado(id, !apoderado.revisado);
        return;
      }
      if (!clave) return;
      const siguiente = new Set(locales);
      if (!siguiente.delete(k)) siguiente.add(k);
      guardarRevisados(clave, siguiente, vigentes);
      setGuardados({ clave, revisados: siguiente });
    },
    [clave, locales, vigentes, datosApoderados, revisarApoderado],
  );

  const elegirMarca = useCallback(
    (marca: Seleccion, desde: HTMLElement) => {
      window.clearTimeout(espera.current);
      disparador.current = desde;
      if (mismaSeleccion(seleccionada, marca) && ancla === desde) {
        setSeleccionada(null);
        setAncla(null);
        return;
      }
      setSeleccionada(marca);
      setAncla(desde);
      setPestana(marca.tipo === "cita" ? "citas" : "apoderados");
      // Al pulsar un nombre, su fila del panel se abre con el detalle y las acciones.
      if (marca.tipo === "apoderado") setAbierta(claveApoderado(marca.id));
    },
    [seleccionada, ancla],
  );
  const alCita = useCallback((id: string, desde: HTMLElement) => elegirMarca({ tipo: "cita", id }, desde), [elegirMarca]);
  const alApoderado = useCallback((id: string, desde: HTMLElement) => elegirMarca({ tipo: "apoderado", id }, desde), [elegirMarca]);

  const verEnTexto = useCallback((buscada: Seleccion, desde: HTMLElement) => {
    window.clearTimeout(espera.current);
    disparador.current = desde;
    const marcasTexto = columna.current?.querySelectorAll<HTMLElement>(MARCAS_TEXTO) ?? [];
    const marca = Array.from(marcasTexto).find((m) => (buscada.tipo === "cita" ? m.dataset["cita"] : m.dataset["apoderado"]) === buscada.id) ?? null;
    const enCajon = desde.closest("#bor-panel.abierto") !== null;
    setSeleccionada(marca ? buscada : null);
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

  const verEvidencia = useCallback((pedido: PedidoVisor, desde: HTMLElement) => {
    abridorVisor.current = desde;
    setErrorVisor(false);
    setVisor(pedido);
    cargarVisor().then(
      (componente) => setVisorCargado(() => componente),
      () => {
        setVisor(null);
        setErrorVisor(true);
      },
    );
  }, []);

  const cerrarVisor = useCallback(() => setVisor(null), []);

  const corregir = useCallback((pedido: PedidoAjuste, desde: HTMLElement) => {
    abridorAjuste.current = desde;
    setAjuste(pedido);
    cargarAjuste().then(
      (componente) => setDialogoAjuste(() => componente),
      () => {
        setAjuste(null);
        mostrarToast("No se pudo abrir la corrección. Revise la conexión y vuelva a intentarlo.", { tipo: "error" });
      },
    );
  }, []);

  /** Si el foco cayó en <body> (el botón que lo tenía ya no está), lo lleva al detalle abierto o a la fila del abogado. */
  const recuperarFoco = useCallback((apoderado: string | null, abridor: HTMLElement | null = null) => {
    requestAnimationFrame(() => {
      const activo = document.activeElement;
      if (activo && activo !== document.body && activo.isConnected) return;
      const destino = abridor?.isConnected
        ? abridor
        : (document.getElementById("bor-detalle-titulo") ??
          (apoderado ? document.querySelector<HTMLElement>(`#bor-panel li[data-clave="${claveApoderado(apoderado)}"] .bor-fila-boton`) : null));
      destino?.focus({ preventScroll: true });
    });
  }, []);

  const cerrarAjuste = useCallback(() => {
    const pedido = ajuste;
    setAjuste(null);
    // Con la corrección el abogado puede cambiar de grupo y el botón que la abrió ya no estar: el foco va a su fila o al detalle.
    recuperarFoco(pedido?.apoderado ?? null, abridorAjuste.current);
  }, [ajuste, recuperarFoco]);

  const restaurarPoder = useCallback(
    (id: string) => {
      ajustar(id, { poder_descartado: false }).then(
        (vista) => {
          // «Deshacer el descarte» desaparece con el descarte: el foco no debe quedar en <body>.
          recuperarFoco(id);
          mostrarToast(
            vista.poder.estado === "sin_poder" || vista.poder.estado === "descartado"
              ? `Ya no hay un poder que respalde a ${vista.nombre}: señálelo a mano.`
              : "Se volvió a tomar el poder hallado.",
          );
        },
        (e: unknown) => mostrarToast(mensajeError(e, "No se pudo deshacer el descarte del poder."), { tipo: "error" }),
      );
    },
    [ajustar, recuperarFoco],
  );

  // Al cerrar el visor el foco vuelve al botón que lo abrió (en el detalle o en la fila del panel).
  useEffect(() => {
    if (visor) return;
    const abridor = abridorVisor.current;
    abridorVisor.current = null;
    if (abridor?.isConnected) abridor.focus({ preventScroll: true });
  }, [visor]);

  // Con nombres marcados el detalle se descarga de antemano; si falla, se vuelve a intentar al pulsar un nombre.
  const apoderadoElegido = seleccionada?.tipo === "apoderado";
  useEffect(() => {
    if ((!conMarcas && !apoderadoElegido) || PopoverApoderado) return;
    cargarDetalleApoderado().then(
      (componente) => setPopoverApoderado(() => componente),
      () => {
        if (!apoderadoElegido) return;
        setSeleccionada((actual) => (actual?.tipo === "apoderado" ? null : actual));
        mostrarToast("No se pudo abrir el detalle del abogado. Revise la conexión y vuelva a intentarlo.", { tipo: "error" });
      },
    );
  }, [conMarcas, apoderadoElegido, PopoverApoderado]);

  // El título se enfoca al abrir el detalle, no cada vez que el sondeo de /apoderados trae un objeto nuevo.
  const claveSeleccion = seleccionada ? `${seleccionada.tipo}:${seleccionada.id}` : null;
  const hayDetalle = cita !== null || (abogado !== null && PopoverApoderado !== null);
  useEffect(() => {
    if (hayDetalle && ancla) tituloDetalle.current?.focus({ preventScroll: true });
  }, [claveSeleccion, hayDetalle, ancla]);

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
      if (seleccionada && !destino.closest("#bor-detalle, [data-cita], [data-apoderado], #bor-panel, dialog[open]")) cerrarDetalle(false);
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
  const editable = ediciones?.editable === true;
  const modoEdicion = editando && editable;
  const conflictos = editable ? (ediciones?.conflictos ?? []) : [];
  const radicado = metadatos?.cui_2a || metadatos?.cui_1a;
  // Qué se rehízo con la última corrección: el servidor la guarda en `resumen.decision` y su fecha la identifica para no repetir el aviso.
  const ultimaDecision = estado?.estado === "esperando_decision" && !enCurso ? resumen?.decision : null;
  const fechaCorreccion = typeof ultimaDecision?.fecha === "string" && ultimaDecision.fecha !== "" ? ultimaDecision.fecha : null;
  const correccionRehecha =
    fechaCorreccion !== null &&
    (ultimaDecision?.accion === "rehacer_apertura" || ultimaDecision?.accion === "rehacer_consideraciones") &&
    !(correccionCerrada?.caso === caso && correccionCerrada.fecha === fechaCorreccion) &&
    leerCorreccionVista(caso) !== fechaCorreccion
      ? ultimaDecision
      : null;
  const entenderCorreccion = () => {
    if (fechaCorreccion === null) return;
    guardarCorreccionVista(caso, fechaCorreccion);
    setCorreccionCerrada({ caso, fecha: fechaCorreccion });
  };

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

  const visorAbierto = visor ? (apoderadosPorId.get(visor.apoderado) ?? null) : null;
  const corrigiendoAbogado = ajuste ? (apoderadosPorId.get(ajuste.apoderado) ?? null) : null;
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
      {correccionRehecha && (
        <Aviso tipo="info" class="bor-aviso" acciones={<Boton onClick={entenderCorreccion}>Entendido</Boton>}>
          {correccionRehecha.accion === "rehacer_apertura"
            ? `Se rehicieron las secciones I a IV según su corrección: «${resumirInstruccion(correccionRehecha.instruccion ?? "")}» y, después, las consideraciones desde cero (sin esta instrucción). El texto fijo de la plantilla no cambia con una corrección.`
            : `Se rehizo la sección V según su corrección: «${resumirInstruccion(correccionRehecha.instruccion ?? "")}». El resto del borrador, incluido el texto fijo de la plantilla, quedó igual.`}
        </Aviso>
      )}
      {errorVisor && (
        <Aviso tipo="error" class="bor-aviso" acciones={<Boton onClick={() => setErrorVisor(false)}>Cerrar</Boton>}>
          No se pudo abrir el visor de evidencia. Revise la conexión y vuelva a intentarlo.
        </Aviso>
      )}
      {conflictos.length > 0 && (
        <Aviso
          tipo="alerta"
          class="bor-aviso"
          acciones={
            <Boton variante="primario" onClick={() => setResolviendo(true)}>
              Resolver
            </Boton>
          }
        >
          {conflictos.length === 1
            ? "Hay 1 conflicto entre sus ediciones y la corrección de la IA"
            : `Hay ${conflictos.length} conflictos entre sus ediciones y la corrección de la IA`}
        </Aviso>
      )}
      <div class="bor-mesa">
        <Indice entradas={entradas} marcas={marcas} activa={activa} alSeccion={alSeccion} redaccion={redaccion} abierto={indiceAbierto} />
        <div class="bor-col-doc" ref={columna}>
          <div class={cx("bor-doc-barra", conMarcas && "con-leyenda")}>
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
              title="Marca el texto de plantilla: el texto fijo del sistema (Competencia, procedibilidad general, transición) y los datos que salen del expediente (encabezado, Asunto). Una corrección no cambia el texto fijo; el Asunto sí se rehace con «Rehacer la apertura». Lo que queda sin marca lo redactó el modelo."
            >
              <input type="checkbox" role="switch" aria-label="Marcar texto de plantilla" checked={plantilla} onChange={(e) => setPlantilla(e.currentTarget.checked)} />
              <span class="bor-pista" aria-hidden="true" />
              <span class="bor-muestra" aria-hidden="true" />
              <span>
                <span class="bor-txt-largo">Marcar texto de</span> plantilla
              </span>
            </label>
            {editable && (
              <label class="bor-interruptor" title="Permite corregir a mano el texto que redactó el modelo. Las citas, las imágenes y la plantilla no se pueden cambiar.">
                <input
                  type="checkbox"
                  role="switch"
                  aria-label="Editar texto"
                  checked={editando}
                  onChange={(e) => {
                    if (!e.currentTarget.checked && sucio) {
                      e.currentTarget.checked = true;
                      setApagando(true);
                      return;
                    }
                    setEditando(e.currentTarget.checked);
                  }}
                />
                <span class="bor-pista" aria-hidden="true" />
                <span>Editar texto</span>
              </label>
            )}
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
            {conMarcas && (
              // El subrayado verde sólido de un abogado se parece al de una cita: la leyenda dice qué es cada trazo.
              <span class="bor-leyenda" role="note" aria-label="Leyenda de apoderados">
                <span>
                  <span class="bor-ley-m v">Abogado</span> verificado
                </span>
                <span>
                  <span class="bor-ley-m a">Abogado</span> por revisar
                </span>
                <span>
                  <span class="bor-ley-m m">Abogado</span> no verificado
                </span>
              </span>
            )}
          </div>
          <h2 class="solo-lectura">Texto del borrador</h2>
          <Documento
            vista={vista}
            citas={citasPorId}
            apoderados={apoderadosPorId}
            seleccionada={seleccionada}
            plantilla={plantilla}
            alCita={alCita}
            alApoderado={alApoderado}
            edicion={ediciones && editable ? { caso, activa: modoEdicion, piezas: ediciones.piezas, conflictos: conflictos.map((c) => c.pieza), recargar, alSucio: setSucio } : undefined}
          />
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
          {abogado && ancla && columna.current && PopoverApoderado && (
            <PopoverApoderado
              apoderado={abogado}
              editable={apoderadosEditables}
              ancla={ancla}
              contenedor={columna.current}
              titulo={tituloDetalle}
              onCerrar={() => cerrarDetalle(true)}
              alRevisar={(revisado) => revisarApoderado(abogado.id, revisado)}
              alVerEvidencia={verEvidencia}
              alSubir={(archivo) => subirCertificado(abogado.id, archivo)}
              alReintentar={puedeReintentar(abogado, datosApoderados?.consulta) ? () => consultar([abogado.id], true) : undefined}
              alCorregir={(tipo, desde) => corregir({ tipo, apoderado: abogado.id }, desde)}
              alRestaurarPoder={() => restaurarPoder(abogado.id)}
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
          alVerEvidencia={verEvidencia}
          alCorregir={corregir}
          alRestaurarPoder={restaurarPoder}
          apoderadosEnTexto={enTexto}
          umbralJev={resumen?.jev_metadatos?.umbral}
          alertasLeidas={estado !== null}
          avisoEstado={estadoFallo ? "No se pudieron leer las alertas del caso; se muestran solo las citas." : null}
          abiertoMovil={panelAbierto}
          onCerrarMovil={() => cerrarPanel(true)}
          pestana={pestana}
          alPestana={setPestana}
          apoderados={apoderados}
        />
      </div>
      <div class="bor-velo" hidden={!panelAbierto} onClick={() => cerrarPanel(true)} />
      <Dock
        pendientes={quedan}
        revisados={hechos}
        total={pendientes.length}
        alertas={estado ? "listo" : estadoFallo ? "fallo" : "cargando"}
        enCurso={enCurso}
        bloqueo={mensajeBloqueo(bloqueantes(datosApoderados))}
        hrefDecision={enlaceEtapa(caso, "decision")}
        puedeCorregir={corrigible}
        motivoNoCorregir={motivo}
        alCorregir={() => setCorrigiendo(true)}
        conflictos={conflictos.length}
      />
      {visor &&
        visorAbierto &&
        (Visor ? (
          <Visor
            casoId={caso}
            apoderado={visorAbierto}
            evidencia={visor.evidencia}
            titulo={visor.titulo}
            subtitulo={visor.subtitulo}
            editable={apoderadosEditables}
            revisado={visorAbierto.revisado}
            alRevisar={(revisado) => revisarApoderado(visorAbierto.id, revisado)}
            alNoEsCorrecto={() => {
              // El descarte se confirma en su propio diálogo; el foco vuelve después a quien abrió el visor.
              const abridor = abridorVisor.current;
              abridorVisor.current = null;
              setVisor(null);
              if (abridor) corregir({ tipo: "descartar", apoderado: visorAbierto.id }, abridor);
            }}
            alCerrar={cerrarVisor}
          />
        ) : (
          <p class="bor-abriendo" role="status">
            <span class="giro" aria-hidden="true" />
            Abriendo el visor de evidencia…
          </p>
        ))}
      {ajuste &&
        corrigiendoAbogado &&
        DialogoAjuste && (
          <DialogoAjuste
            key={`${ajuste.tipo}:${ajuste.apoderado}`}
            tipo={ajuste.tipo}
            apoderado={corrigiendoAbogado}
            documentos={[...documentosVistos.current.values()].sort((a, b) => a.doc_id.localeCompare(b.doc_id))}
            alGuardar={(cuerpo: AjusteCuerpo) => ajustar(corrigiendoAbogado.id, cuerpo)}
            alCerrar={cerrarAjuste}
          />
        )}
      <Dialogo
        abierto={apagando || guardia.destino !== null}
        titulo="Hay texto sin guardar"
        onCerrar={() => {
          setApagando(false);
          guardia.quedarse();
        }}
        acciones={
          <>
            <Boton
              data-enfoque
              onClick={() => {
                setApagando(false);
                guardia.quedarse();
              }}
            >
              Seguir editando
            </Boton>
            <Boton
              variante="peligro"
              onClick={() => {
                if (apagando) {
                  setApagando(false);
                  setEditando(false);
                } else guardia.salir();
              }}
            >
              Descartar el texto
            </Boton>
          </>
        }
      >
        <p>Tiene un párrafo con cambios sin guardar. Si continúa, pierde lo que escribió.</p>
      </Dialogo>
      {DialogoConflictos && (
        <DialogoConflictos abierto={resolviendo} caso={caso} conflictos={conflictos} recargar={recargar} onCerrar={() => setResolviendo(false)} />
      )}
      {DialogoCorrecciones && (
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
      )}
    </div>
  );
}
