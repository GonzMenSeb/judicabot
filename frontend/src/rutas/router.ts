import { signal } from "@preact/signals";
import type { ComponentType } from "preact";
import type { PropsVista } from "../vistas/tipos";

export const ETAPAS = ["documentos", "proceso", "borrador", "decision", "fallo"] as const;
export type Etapa = (typeof ETAPAS)[number];
export type NombreVista = "inicio" | "casos" | "formato" | "ia" | Etapa;
export interface Ruta {
  vista: NombreVista;
  params: PropsVista;
}

const INICIO: Ruta = { vista: "inicio", params: {} };
const esEtapa = (s: string | undefined): s is Etapa => ETAPAS.includes(s as Etapa);

function decodificar(parte: string): string {
  try {
    return decodeURIComponent(parte);
  } catch {
    return parte;
  }
}

export function coincidir(hash: string): Ruta {
  const partes = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodificar);
  const [seccion, caso, etapa] = partes;
  if (partes.length === 0) return INICIO;
  if (partes.length === 1 && (seccion === "formato" || seccion === "ia")) return { vista: seccion, params: {} };
  if (seccion !== "segunda") return INICIO;
  if (partes.length === 1) return { vista: "casos", params: {} };
  if (partes.length === 3 && caso && esEtapa(etapa)) return { vista: etapa, params: { caso } };
  return INICIO;
}

type Cargador = () => Promise<{ default: ComponentType<PropsVista> }>;

const cargadores: Record<NombreVista, Cargador> = {
  inicio: () => import("../vistas/inicio"),
  casos: () => import("../vistas/casos"),
  documentos: () => import("../vistas/documentos"),
  proceso: () => import("../vistas/proceso"),
  borrador: () => import("../vistas/borrador"),
  decision: () => import("../vistas/decision"),
  fallo: () => import("../vistas/fallo"),
  formato: () => import("../vistas/formato"),
  ia: () => import("../vistas/ia"),
};

export const ruta = signal<Ruta>(coincidir(location.hash));
export const cargadas = signal<Partial<Record<NombreVista, ComponentType<PropsVista>>>>({});
export const fallida = signal<NombreVista | null>(null);

const pendientes = new Map<NombreVista, Promise<void>>();

export function precargar(vista: NombreVista = ruta.value.vista): Promise<void> {
  let promesa = pendientes.get(vista);
  if (!promesa) {
    promesa = cargadores[vista]().then(
      (modulo) => {
        fallida.value = null;
        cargadas.value = { ...cargadas.value, [vista]: modulo.default };
      },
      () => {
        pendientes.delete(vista);
        fallida.value = vista;
      },
    );
    pendientes.set(vista, promesa);
  }
  return promesa;
}

export function navegar(destino: string): void {
  location.hash = destino;
}

addEventListener("hashchange", () => {
  ruta.value = coincidir(location.hash);
});
