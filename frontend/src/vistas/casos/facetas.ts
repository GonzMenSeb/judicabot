/**
 * Registro de la lista compartida «Mi trabajo»: qué procesos, estados y facetas existen. Sin DOM ni Preact.
 * Lo único que cambia entre procesos son PROPIAS y FILA; el motor (filtros.ts) solo lee este registro.
 *
 * Procesos
 *   PROCESOS: { id, corto, largo }[]          pestañas en orden: todos, primera, segunda, desacato, penal.
 *   infoProceso(id) / esProceso(x)            búsqueda y guarda de tipo.
 *   procesoDe(caso): TipoProceso              hoy siempre "segunda" (PR2 lo lee de caso.proceso).
 *
 * Estados (los 7 de la API en 6 grupos de la interfaz)
 *   ESTADOS: { id, etiqueta, tono, api[] }[]  orden de la franja y de los grupos.
 *   estadoDe(caso | estadoApi): EstadoUi      sin_iniciar y revision son «Por preparar».
 *   infoEstado(id), ESTADOS_DEFECTO (todos menos «terminado»), PRIORIDAD (menor = primero).
 *
 * Facetas: { clave, etiqueta, corto, tipo, activo?, dinamica?, opciones, valor(caso) }
 *   tipo "varias" | "buscable" (lista larga con buscador) | "pasos" (orden procesal) | "interruptor" (un toque:
 *   `activo` es el id de la opción que enciende). valor(caso) devuelve el id o los ids de opción del caso.
 *   TRABAJADO                                 la pastilla de fecha (control propio, no es una Faceta); va primera.
 *   generales(proceso, casos): Faceta[]       Juzgado, Entidad accionada (opciones sacadas de `casos`, agrupando
 *                                             variantes sin tildes ni mayúsculas; se omiten si no hay ninguna) y
 *                                             Con alertas. `casos` = los casos en alcance (pestaña o página).
 *   PROPIAS[proceso] / propias(proceso)       facetas propias; propias() les antepone el proceso a la clave
 *                                             ("segunda.aquo"). Vacías en PR1; PR2 llena «segunda».
 *   FILA[proceso](caso): DatoFila[]           datos propios que la fila muestra; clave/valor dicen qué filtro
 *                                             reflejan (filtros.datosFila calcula el resaltado). Vacía en PR1.
 *   facetaPorClave(clave, casos?)             la faceta de una clave de filtro, o undefined si no existe.
 *   esPropia(clave), opciones(...etiquetas)   ayudas.
 */
import type { CasoResumen, EstadoCasoApi } from "../../api/contrato";
import { plano, type TonoFicha } from "./agrupar";
import type { TipoProceso } from "./iconos";

export type { TipoProceso };
export type ProcesoFiltro = "todos" | TipoProceso;

export interface InfoProceso {
  id: ProcesoFiltro;
  corto: string;
  largo: string;
}

export const PROCESOS: readonly InfoProceso[] = [
  { id: "todos", corto: "Todos", largo: "Todos los procesos" },
  { id: "primera", corto: "1ª instancia", largo: "Fallos de tutela de primera instancia" },
  { id: "segunda", corto: "2ª instancia", largo: "Fallos de tutela de segunda instancia" },
  { id: "desacato", corto: "Desacato", largo: "Incidentes de desacato" },
  { id: "penal", corto: "Penal", largo: "Penal" },
];

export const infoProceso = (id: ProcesoFiltro): InfoProceso => PROCESOS.find((p) => p.id === id) ?? PROCESOS[0]!;

export const esProceso = (x: string): x is ProcesoFiltro => PROCESOS.some((p) => p.id === x);

/** El proceso del caso. CasoResumen aún no lo trae: todos los casos de hoy son de segunda instancia. */
export const procesoDe = (_caso: CasoResumen): TipoProceso => "segunda";

export type EstadoUi = "decidir" | "faltan" | "error" | "preparar" | "redaccion" | "terminado";

export interface InfoEstado {
  id: EstadoUi;
  etiqueta: string;
  tono: TonoFicha;
  api: readonly EstadoCasoApi[];
}

export const ESTADOS: readonly InfoEstado[] = [
  { id: "decidir", etiqueta: "Por decidir", tono: "sello", api: ["esperando_decision"] },
  { id: "faltan", etiqueta: "Faltan documentos", tono: "alerta", api: ["incompleto"] },
  { id: "error", etiqueta: "Con error", tono: "alerta", api: ["error"] },
  { id: "preparar", etiqueta: "Por preparar", tono: "", api: ["sin_iniciar", "revision"] },
  { id: "redaccion", etiqueta: "En redacción", tono: "trabajando", api: ["corriendo"] },
  { id: "terminado", etiqueta: "Terminados", tono: "ok", api: ["terminado"] },
];

const POR_API = Object.fromEntries(ESTADOS.flatMap((e) => e.api.map((a) => [a, e.id]))) as Record<EstadoCasoApi, EstadoUi>;

export const estadoDe = (caso: Pick<CasoResumen, "estado"> | EstadoCasoApi): EstadoUi =>
  POR_API[typeof caso === "string" ? caso : caso.estado];

export const infoEstado = (id: EstadoUi): InfoEstado => ESTADOS.find((e) => e.id === id)!;

export const esEstado = (x: string): x is EstadoUi => ESTADOS.some((e) => e.id === x);

/** Lo que se ve sin tocar la franja: todo lo abierto. */
export const ESTADOS_DEFECTO: readonly EstadoUi[] = ESTADOS.filter((e) => e.id !== "terminado").map((e) => e.id);

/** «Lo que me toca primero»: menor va antes. */
export const PRIORIDAD: Readonly<Record<EstadoUi, number>> = {
  decidir: 0,
  faltan: 1,
  error: 1,
  preparar: 2,
  redaccion: 3,
  terminado: 4,
};

export type TipoFaceta = "varias" | "buscable" | "pasos" | "interruptor";

export interface Opcion {
  id: string;
  etiqueta: string;
}

export type ValorFaceta = string | readonly (string | null | undefined)[] | null | undefined;

export interface Faceta {
  clave: string;
  /** Título largo (encabezado del desplegable, texto de «filtros aplicados»). */
  etiqueta: string;
  /** Texto de la pastilla. */
  corto: string;
  tipo: TipoFaceta;
  /** Solo en "interruptor": el id de la opción que el toque enciende. */
  activo?: string;
  /** Las opciones salen de los casos (ids normalizados): no se pueden validar sin ellos. */
  dinamica?: boolean;
  opciones: readonly Opcion[];
  valor: (caso: CasoResumen) => ValorFaceta;
}

/** Opciones cuyo id es su propia etiqueta (lo normal en las facetas propias). */
export const opciones = (...etiquetas: string[]): Opcion[] => etiquetas.map((e) => ({ id: e, etiqueta: e }));

/** La pastilla de fecha de la última actividad; su control es FiltroFecha, no una lista. */
export const TRABAJADO = { clave: "fecha", etiqueta: "Trabajado (última actividad en el caso)", corto: "Trabajado" } as const;

const normalizar = (texto: string) => plano(texto).replace(/\s+/g, " ").trim();

/** Opciones a partir de los valores de los casos: variantes de escritura juntas, más frecuentes primero. */
function dinamicas(casos: readonly CasoResumen[], valores: (c: CasoResumen) => readonly (string | null)[]): Opcion[] {
  const cuenta = new Map<string, { n: number; formas: Map<string, number> }>();
  for (const c of casos) {
    const vistos = new Set<string>();
    for (const crudo of valores(c)) {
      const texto = crudo?.replace(/\s+/g, " ").trim();
      if (!texto) continue;
      const id = normalizar(texto);
      const item = cuenta.get(id) ?? { n: 0, formas: new Map<string, number>() };
      if (!vistos.has(id)) item.n += 1;
      vistos.add(id);
      item.formas.set(texto, (item.formas.get(texto) ?? 0) + 1);
      cuenta.set(id, item);
    }
  }
  return [...cuenta]
    .map(([id, { n, formas }]) => {
      let etiqueta = "";
      let max = 0;
      for (const [forma, k] of formas) if (k > max) [etiqueta, max] = [forma, k];
      return { id, etiqueta, n };
    })
    .sort((a, b) => b.n - a.n || a.etiqueta.localeCompare(b.etiqueta, "es", { numeric: true }))
    .map(({ id, etiqueta }) => ({ id, etiqueta }));
}

const juzgadoDe = (c: CasoResumen) => [c.juzgado_a_quo];
const entidadesDe = (c: CasoResumen) => c.accionadas;

function juzgado(proceso: ProcesoFiltro | null, casos: readonly CasoResumen[]): Faceta {
  const segunda = proceso === "segunda";
  return {
    clave: "juzgado",
    etiqueta: segunda ? "Juzgado de primera instancia" : "Juzgado",
    corto: segunda ? "Juzgado de 1ª inst." : "Juzgado",
    tipo: "buscable",
    dinamica: true,
    opciones: dinamicas(casos, juzgadoDe),
    valor: (c) => (c.juzgado_a_quo ? normalizar(c.juzgado_a_quo) : null),
  };
}

function entidad(proceso: ProcesoFiltro | null, casos: readonly CasoResumen[]): Faceta {
  const texto = proceso === "desacato" ? "Entidad requerida" : "Entidad accionada";
  return {
    clave: "entidad",
    etiqueta: texto,
    corto: texto,
    tipo: "buscable",
    dinamica: true,
    opciones: dinamicas(casos, entidadesDe),
    valor: (c) => c.accionadas.map(normalizar),
  };
}

const ALERTAS: Faceta = {
  clave: "alertas",
  etiqueta: "Alertas",
  corto: "Con alertas",
  tipo: "interruptor",
  activo: "con",
  opciones: [
    { id: "con", etiqueta: "Con alertas" },
    { id: "sin", etiqueta: "Sin alertas" },
  ],
  valor: (c) => (c.n_alertas > 0 ? "con" : "sin"),
};

/** Facetas del carril «Generales» (después de TRABAJADO). `casos`: los casos en alcance. */
export function generales(proceso: ProcesoFiltro | null, casos: readonly CasoResumen[]): Faceta[] {
  return [juzgado(proceso, casos), entidad(proceso, casos), ALERTAS].filter((f) => !f.dinamica || f.opciones.length > 0);
}

/** Facetas propias de cada proceso, con clave local ("aquo"). Vacías hasta que el resumen traiga sus datos (PR2). */
export const PROPIAS: Readonly<Record<TipoProceso, readonly Faceta[]>> = {
  primera: [],
  segunda: [],
  desacato: [],
  penal: [],
};

/** Clave de filtro de una faceta propia: "<proceso>.<clave>". */
export const clavePropia = (proceso: TipoProceso, clave: string) => `${proceso}.${clave}`;

/** ¿La clave de filtro es de un proceso concreto? Las pestañas de proceso las ignoran al contar. */
export const esPropia = (clave: string) => clave.includes(".");

/** Las facetas propias del proceso, con la clave ya prefijada para usarla en Filtros.sel. */
export const propias = (proceso: TipoProceso | null): Faceta[] =>
  proceso ? PROPIAS[proceso].map((f) => ({ ...f, clave: clavePropia(proceso, f.clave) })) : [];

export interface DatoFila {
  texto: string;
  tono?: "ok" | "alerta" | "mal";
  /** Clave local de la faceta que este dato refleja (sin prefijo de proceso). */
  clave?: string;
  /** Id o ids de opción de esa faceta; si alguno está elegido, el dato se resalta. */
  valor?: string | readonly string[];
}

const sinDatos = (): (DatoFila | null)[] => [];

/** Datos propios que cada fila muestra según su proceso. Vacíos en PR1. */
export const FILA: Readonly<Record<TipoProceso, (caso: CasoResumen) => readonly (DatoFila | null)[]>> = {
  primera: sinDatos,
  segunda: sinDatos,
  desacato: sinDatos,
  penal: sinDatos,
};

/** La faceta que corresponde a una clave de filtro (general o propia). Sin `casos`, las dinámicas vienen sin opciones. */
export function facetaPorClave(clave: string, casos: readonly CasoResumen[] = []): Faceta | undefined {
  if (clave === "juzgado") return juzgado(null, casos);
  if (clave === "entidad") return entidad(null, casos);
  if (clave === "alertas") return ALERTAS;
  const [proceso = "", local] = clave.split(".", 2);
  if (!esProceso(proceso) || proceso === "todos" || !local) return undefined;
  return propias(proceso).find((f) => f.clave === clave);
}
