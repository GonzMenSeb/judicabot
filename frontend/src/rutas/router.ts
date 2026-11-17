import { signal } from "@preact/signals";
import type { ComponentType } from "preact";
import type { PropsVista } from "../vistas/tipos";

export const ETAPAS = ["documentos", "proceso", "borrador", "decision", "fallo"] as const;
export type Etapa = (typeof ETAPAS)[number];
export type NombreVista = "inicio" | "casos" | Etapa;
export interface Ruta {
  vista: NombreVista;
  params: PropsVista;
}

type Cargador = () => Promise<{ default: ComponentType<PropsVista> }>;

export const SECCIONES_CONFIGURACION = [
  { id: "formato", titulo: "Formato de documentos", cargar: () => import("../vistas/formato") },
  { id: "ia", titulo: "Inteligencia artificial", cargar: () => import("../vistas/ia") },
  { id: "extension", titulo: "Extensión de la relatoría", cargar: () => import("../vistas/extension") },
] as const satisfies readonly { id: string; titulo: string; cargar: Cargador }[];
export type SeccionConfiguracion = (typeof SECCIONES_CONFIGURACION)[number]["id"];

export interface RutaHash extends Ruta {
  configuracion?: SeccionConfiguracion;
}

const INICIO: Ruta = { vista: "inicio", params: {} };
const ANTIGUAS: readonly SeccionConfiguracion[] = ["formato", "ia"];
const esEtapa = (s: string | undefined): s is Etapa => ETAPAS.includes(s as Etapa);
const esAntigua = (s: string | undefined): s is SeccionConfiguracion => ANTIGUAS.includes(s as SeccionConfiguracion);
const esSeccion = (s: string | undefined): s is SeccionConfiguracion => SECCIONES_CONFIGURACION.some((x) => x.id === s);

function decodificar(parte: string): string {
  try {
    return decodeURIComponent(parte);
  } catch {
    return parte;
  }
}

export function separar(hash: string): [camino: string, consulta: string] {
  const i = hash.indexOf("?");
  return i < 0 ? [hash, ""] : [hash.slice(0, i), hash.slice(i + 1)];
}

export function coincidir(hash: string): RutaHash {
  const partes = separar(hash)[0].replace(/^#\/?/, "").split("/").filter(Boolean).map(decodificar);
  const [seccion, caso, etapa] = partes;
  if (partes.length === 0) return INICIO;
  if (partes.length === 1 && esAntigua(seccion)) return { ...INICIO, configuracion: seccion };
  if (seccion === "configuracion" && partes.length <= 2) {
    const elegida = caso ?? SECCIONES_CONFIGURACION[0].id;
    return esSeccion(elegida) ? { ...INICIO, configuracion: elegida } : INICIO;
  }
  if (seccion !== "segunda") return INICIO;
  if (partes.length === 1) return { vista: "casos", params: {} };
  if (partes.length === 3 && caso && esEtapa(etapa)) return { vista: etapa, params: { caso } };
  return INICIO;
}

export const hashConfiguracion = (seccion: SeccionConfiguracion) => `#/configuracion/${seccion}`;

export function hashDe({ vista, params }: Ruta): string {
  if (vista === "inicio") return "#/";
  if (vista === "casos") return "#/segunda";
  return `#/segunda/${encodeURIComponent(params.caso ?? "")}/${vista}`;
}

const conConsulta = (hash: string, q: string) => (q ? `${hash}?${q}` : hash);

export const claveDe = ({ vista, params }: Ruta) => `${vista}:${params.caso ?? ""}`;

function perezosas<K extends string>(cargadores: Record<K, Cargador>) {
  const cargadas = signal<Partial<Record<K, ComponentType<PropsVista>>>>({});
  const fallida = signal<K | null>(null);
  const pendientes = new Map<K, Promise<void>>();
  const precargar = (clave: K): Promise<void> => {
    let promesa = pendientes.get(clave);
    if (!promesa) {
      promesa = cargadores[clave]().then(
        (modulo) => {
          fallida.value = null;
          cargadas.value = { ...cargadas.value, [clave]: modulo.default };
        },
        () => {
          pendientes.delete(clave);
          fallida.value = clave;
        },
      );
      pendientes.set(clave, promesa);
    }
    return promesa;
  };
  return { cargadas, fallida, precargar };
}

const vistas = perezosas<NombreVista>({
  inicio: () => import("../vistas/inicio"),
  casos: () => import("../vistas/casos"),
  documentos: () => import("../vistas/documentos"),
  proceso: () => import("../vistas/proceso"),
  borrador: () => import("../vistas/borrador"),
  decision: () => import("../vistas/decision"),
  fallo: () => import("../vistas/fallo"),
});

const secciones = perezosas(
  Object.fromEntries(SECCIONES_CONFIGURACION.map((s): [string, Cargador] => [s.id, s.cargar])) as Record<SeccionConfiguracion, Cargador>,
);

export const ruta = signal<Ruta>(INICIO);
export const consulta = signal<string>("");
export const configuracion = signal<SeccionConfiguracion | null>(null);
export const { cargadas, fallida } = vistas;
export const { cargadas: seccionesCargadas, fallida: seccionFallida, precargar: precargarSeccion } = secciones;

export const hashActual = () => conConsulta(hashDe(ruta.value), consulta.value);

export function reemplazarConsulta(q: string): void {
  consulta.value = q;
  if (configuracion.value !== null) return;
  const hash = conConsulta(hashDe(ruta.value), q);
  if (hash !== location.hash) history.replaceState(history.state, "", hash);
}

export function precargar(vista: NombreVista = ruta.value.vista): Promise<void> {
  return vistas.precargar(vista);
}

type Guardia = (destino: string) => boolean;
const guardias = new Set<Guardia>();

export function protegerSalida(guardia: Guardia): () => void {
  guardias.add(guardia);
  return () => {
    guardias.delete(guardia);
  };
}

interface MarcaPanel {
  profundidad: number;
  desdePagina: boolean;
}

interface Salida {
  destino: string;
  reemplazar: boolean;
}

let marca: MarcaPanel | null = null;
let primera = true;
let salida: Salida | null = null;

export const saliendoDelPanel = () => salida !== null;

function salirDelPanel(destino: string): void {
  const { profundidad, desdePagina } = marca ?? { profundidad: 0, desdePagina: false };
  const pasos = desdePagina ? profundidad + 1 : profundidad;
  if (pasos === 0) {
    history.replaceState(null, "", destino);
    sincronizar();
    return;
  }
  salida = { destino, reemplazar: !desdePagina };
  history.go(-pasos);
}

export function navegarDirecto(destino: string): void {
  for (const guardia of guardias) if (guardia(destino)) return;
  if (configuracion.value !== null && !coincidir(destino).configuracion) salirDelPanel(destino);
  else location.hash = destino;
}

export function navegar(destino: string): void {
  const { configuracion: seccion, ...pagina } = coincidir(destino);
  if (configuracion.value === null || seccion) navegarDirecto(destino);
  else {
    consulta.value = separar(destino)[1];
    if (claveDe(pagina) !== claveDe(ruta.value)) ruta.value = pagina;
  }
}

const mismoHash = (a: string, b: string) => a === b || new URL(a, location.href).hash === new URL(b, location.href).hash;

function marcarEntrada(abierta: boolean): void {
  const previa = configuracion.value !== null ? marca : null;
  if (!abierta) {
    marca = null;
    return;
  }
  const guardada = (history.state as { panel?: MarcaPanel } | null)?.panel;
  if (guardada) {
    marca = guardada;
    return;
  }
  marca = previa ? { profundidad: previa.profundidad + 1, desdePagina: previa.desdePagina } : { profundidad: 0, desdePagina: !primera };
  history.replaceState({ ...history.state, panel: marca }, "");
}

export function sincronizar(): void {
  if (salida) {
    const { destino, reemplazar } = salida;
    if (!reemplazar && !mismoHash(destino, location.hash)) {
      location.hash = destino;
      return;
    }
    salida = null;
    if (reemplazar) history.replaceState(null, "", destino);
  }
  const { configuracion: pedida } = coincidir(location.hash);
  if (pedida && location.hash !== hashConfiguracion(pedida)) history.replaceState(history.state, "", hashConfiguracion(pedida));
  const { configuracion: seccion, ...pagina } = coincidir(location.hash);
  marcarEntrada(seccion !== undefined);
  primera = false;
  configuracion.value = seccion ?? null;
  if (seccion) return;
  consulta.value = separar(location.hash)[1];
  if (claveDe(pagina) !== claveDe(ruta.value)) ruta.value = pagina;
}

sincronizar();
addEventListener("hashchange", sincronizar);
