/**
 * Motor puro de la lista «Mi trabajo»: estado de los filtros, predicados, conteos, orden, grupos y URL. Sin DOM ni
 * Preact; todo lo que depende de «hoy» lo recibe como `hoy: Date` para que las pruebas sean deterministas.
 *
 * Estado
 *   Filtros { q, proceso, estado[], fecha, desde, hasta, sel, orden, agrupar }
 *     fecha: "todo" | PresetFecha | "rango" (desde/hasta "AAAA-MM-DD", solo con "rango"; uno de los dos puede faltar).
 *     sel: { [claveFaceta]: ids elegidos }, nunca con listas vacías. Claves de facetas.ts ("juzgado", "segunda.aquo",
 *          "plazo" con ids de PLAZOS).
 *   inicial(procesoFijo?)            valores por defecto: en la página de un proceso, proceso fijo y agrupar "estado";
 *                                    en Inicio, "todos" y "ninguno". Terminados fuera.
 *   FECHAS, ORDENES, AGRUPACIONES    { id, etiqueta }[] para los controles.
 *
 * Filtrar y contar (cada conteo ignora su propio filtro)
 *   predicados(f, hoy): Predicado[]  compílelos una vez por render; claves: "proceso", "estado", "fecha", "q" y
 *                                    cada clave de sel ("plazo" incluida).
 *   pasa(caso, preds, omitir?)       omitir: una clave, varias o una función clave => boolean.
 *   contar(casos, preds, omitir?, prueba?)
 *   conteoEstados(casos, preds)      franja de estados (ignora "estado").
 *   conteoPestanas(casos, preds)     pestañas (ignora "proceso" y las claves propias, OMITIR_PESTANAS).
 *   conteoOpciones(casos, preds, faceta)  Map id → n para un desplegable (ignora la clave de la faceta).
 *   conteoFechas(casos, preds, hoy)  n por preset de FECHAS (ignora "fecha").
 *   conteoPlazos(casos, preds)       n por cubeta de PLAZOS, para las baldosas (ignora "plazo").
 *   actividad(casos, hoy, dias = 30) histograma por día local de `actualizado`; pásele los casos que ya pasan
 *                                    `pasa(c, preds, "fecha")`.
 *   procesoActivo(f, casos)          el proceso cuyos filtros propios se muestran: el elegido o, si todos los casos
 *                                    son de un mismo proceso, ese (Inicio con un solo proceso).
 *
 * Cambiar el estado (devuelven un Filtros nuevo)
 *   elegirEstado(f, id)              desde el defecto, el primer toque deja solo ese estado; luego alterna;
 *                                    «terminado» se suma o se quita encima; vacío vuelve al defecto.
 *   alternar(f, clave, id), fijar(f, clave, ids)   selección de facetas (fijar con [] quita la pastilla).
 *   elegirPreset(f, id), fijarRango(f, desde, hasta), elegirDia(f, iso, pendiente) → { filtros, pendiente }
 *                                    (histograma: un toque elige un día; el segundo cierra el rango).
 *   limpiar(f, defaults) → { filtros, deshacer }   deshacer(actual, guardado) devuelve lo limpiado; orden,
 *                                    agrupar y proceso no se tocan.
 *   activos(f, defaults, facetas): { clave, texto }[]   filtros aplicados (sin proceso), para Limpiar y el conteo.
 *   quitarFiltro(f, clave, defaults) quita uno (estado vuelve al defecto).
 *   sugerencia(casos, f, defaults, facetas, hoy) → { clave, texto, n } | null   el filtro cuya retirada muestra
 *                                    más casos (para el estado vacío).
 *   rangoPreset(id, hoy), rangoDe(f, hoy), textoFecha(f), enRango(caso, rango)
 *
 * Mostrar
 *   ordenarPor(casos, orden)         prioridad (vencidos y los que vencen hoy, luego PRIORIDAD, el vencimiento más
 *                                    cercano y lo más reciente), vence (vencimiento más cercano; sin término al
 *                                    final), reciente, antiguo, radicado.
 *   agruparPor(ordenados, agrupacion, limite?) → { id, titulo, casos, total }[]   por estado o por plazo (orden de
 *                                    ESTADOS o de PLAZOS); `casos` son los primeros
 *                                    `limite` del total, repartidos; total = todos los del grupo; sin grupos vacíos.
 *   datosFila(caso, f)               FILA del proceso del caso con `eco` si su filtro está elegido.
 *
 * URL
 *   serializar(f, defaults): string  solo lo que difiere del defecto: q, p, e, f (preset), d/h (rango), pl (plazo),
 *                                    s.<clave>, o, g. Listas separadas por comas, cada valor codificado.
 *   deserializar(consulta, { defaults, casos? }): Filtros   lee y pasa por validar.
 *   validar(f, { defaults, casos? }) descarta valores desconocidos y fechas mal formadas; sin `casos` acepta
 *                                    cualquier valor en las facetas dinámicas (juzgado, entidad). Descarta las
 *                                    claves propias de otro proceso que el activo y, en un interruptor, toda
 *                                    opción que no sea la que enciende.
 */
import type { CasoResumen } from "../../api/contrato";
import { diaIso, fechaCorta } from "../../estado/formato";
import { coincideBusqueda } from "./agrupar";
import {
  clavePropia,
  ESTADOS,
  ESTADOS_DEFECTO,
  esEstado,
  esProceso,
  esPropia,
  estadoDe,
  facetaPorClave,
  FILA,
  PLAZO,
  PLAZOS,
  plazoDe,
  PRIORIDAD,
  PROCESOS,
  procesoDe,
  urgente,
  type DatoFila,
  type EstadoUi,
  type Faceta,
  type PlazoId,
  type ProcesoFiltro,
  type TipoProceso,
  type ValorFaceta,
} from "./facetas";

export type PresetFecha = "hoy" | "ayer" | "semana" | "mes" | "mespasado";
export type ModoFecha = "todo" | PresetFecha | "rango";
export type Orden = "prioridad" | "vence" | "reciente" | "antiguo" | "radicado";
export type Agrupacion = "ninguno" | "estado" | "plazo";

export interface Filtros {
  q: string;
  proceso: ProcesoFiltro;
  estado: readonly EstadoUi[];
  fecha: ModoFecha;
  desde: string;
  hasta: string;
  sel: Readonly<Record<string, readonly string[]>>;
  orden: Orden;
  agrupar: Agrupacion;
}

export const FECHAS: readonly { id: "todo" | PresetFecha; etiqueta: string }[] = [
  { id: "hoy", etiqueta: "Hoy" },
  { id: "ayer", etiqueta: "Ayer" },
  { id: "semana", etiqueta: "Últimos 7 días" },
  { id: "mes", etiqueta: "Este mes" },
  { id: "mespasado", etiqueta: "Mes pasado" },
  { id: "todo", etiqueta: "Cualquier fecha" },
];

export const ORDENES: readonly { id: Orden; etiqueta: string }[] = [
  { id: "prioridad", etiqueta: "Lo que me toca primero" },
  { id: "vence", etiqueta: "Vence primero" },
  { id: "reciente", etiqueta: "Trabajado más reciente" },
  { id: "antiguo", etiqueta: "Más tiempo sin movimiento" },
  { id: "radicado", etiqueta: "Radicado" },
];

export const AGRUPACIONES: readonly { id: Agrupacion; etiqueta: string }[] = [
  { id: "ninguno", etiqueta: "Sin agrupar" },
  { id: "estado", etiqueta: "Por estado" },
  { id: "plazo", etiqueta: "Por plazo" },
];

export function inicial(procesoFijo?: TipoProceso): Filtros {
  return {
    q: "",
    proceso: procesoFijo ?? "todos",
    estado: ESTADOS_DEFECTO,
    fecha: "todo",
    desde: "",
    hasta: "",
    sel: {},
    orden: "prioridad",
    agrupar: procesoFijo ? "estado" : "ninguno",
  };
}

const lista = (v: ValorFaceta): string[] =>
  v == null ? [] : typeof v === "string" ? [v] : v.filter((x): x is string => typeof x === "string" && x !== "");

const mismoConjunto = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x));

/* ---------- Fechas ---------- */

export interface Rango {
  desde: string;
  hasta: string;
}

const sumarDias = (hoy: Date, n: number) => new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() + n);

export function rangoPreset(id: "todo" | PresetFecha, hoy: Date): Rango {
  const dia = diaIso(hoy);
  switch (id) {
    case "hoy":
      return { desde: dia, hasta: dia };
    case "ayer": {
      const ayer = diaIso(sumarDias(hoy, -1));
      return { desde: ayer, hasta: ayer };
    }
    case "semana":
      return { desde: diaIso(sumarDias(hoy, -6)), hasta: dia };
    case "mes":
      return { desde: diaIso(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: dia };
    case "mespasado":
      return {
        desde: diaIso(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)),
        hasta: diaIso(new Date(hoy.getFullYear(), hoy.getMonth(), 0)),
      };
    case "todo":
      return { desde: "", hasta: "" };
  }
}

export const rangoDe = (f: Filtros, hoy: Date): Rango =>
  f.fecha === "rango" ? { desde: f.desde, hasta: f.hasta } : rangoPreset(f.fecha, hoy);

const diaDe = (caso: CasoResumen) => {
  const fecha = new Date(caso.actualizado);
  return Number.isNaN(fecha.getTime()) ? "" : diaIso(fecha);
};

export function enRango(caso: CasoResumen, { desde, hasta }: Rango): boolean {
  if (!desde && !hasta) return true;
  const dia = diaDe(caso);
  return dia !== "" && (!desde || dia >= desde) && (!hasta || dia <= hasta);
}

/** Texto de la pastilla Trabajado: la etiqueta del preset, "19 oct. – 3 nov.", "Desde …" o "" sin filtro. */
export function textoFecha(f: Filtros): string {
  if (f.fecha !== "rango") return f.fecha === "todo" ? "" : (FECHAS.find((p) => p.id === f.fecha)?.etiqueta ?? "");
  const { desde: d, hasta: h } = f;
  if (d && h) return d === h ? fechaCorta(d) : `${fechaCorta(d)} – ${fechaCorta(h)}`;
  if (d) return `Desde ${fechaCorta(d)}`;
  return h ? `Hasta ${fechaCorta(h)}` : "";
}

export const elegirPreset = (f: Filtros, id: "todo" | PresetFecha): Filtros => ({ ...f, fecha: id, desde: "", hasta: "" });

export function fijarRango(f: Filtros, desde: string, hasta: string): Filtros {
  if (!desde && !hasta) return elegirPreset(f, "todo");
  if (desde && hasta && desde > hasta) [desde, hasta] = [hasta, desde];
  return { ...f, fecha: "rango", desde, hasta };
}

/** Toque en un día del histograma: el primero elige ese día y queda pendiente; el segundo cierra el rango. */
export function elegirDia(f: Filtros, iso: string, pendiente: string | null): { filtros: Filtros; pendiente: string | null } {
  if (pendiente) return { filtros: fijarRango(f, pendiente, iso), pendiente: null };
  return { filtros: fijarRango(f, iso, iso), pendiente: iso };
}

export interface DiaActividad {
  /** "AAAA-MM-DD" local. */
  iso: string;
  n: number;
  /** 0 = domingo … 6 = sábado. */
  diaSemana: number;
}

/** Casos con actividad por día local, de `hoy - (dias - 1)` a `hoy`, del más antiguo al más reciente. */
export function actividad(casos: readonly CasoResumen[], hoy: Date, dias = 30): DiaActividad[] {
  const serie = Array.from({ length: dias }, (_, i) => {
    const fecha = sumarDias(hoy, i - dias + 1);
    return { iso: diaIso(fecha), n: 0, diaSemana: fecha.getDay() };
  });
  const indice = new Map(serie.map((d, i) => [d.iso, i]));
  for (const c of casos) {
    const i = indice.get(diaDe(c));
    if (i !== undefined) serie[i]!.n += 1;
  }
  return serie;
}

/* ---------- Predicados y conteos ---------- */

export interface Predicado {
  clave: string;
  pasa: (caso: CasoResumen) => boolean;
}

export type Omitir = string | readonly string[] | ((clave: string) => boolean);

/** Las pestañas de proceso cuentan sin el proceso ni los filtros propios. */
export const OMITIR_PESTANAS = (clave: string) => clave === "proceso" || esPropia(clave);

export function predicados(f: Filtros, hoy: Date): Predicado[] {
  const preds: Predicado[] = [];
  if (f.proceso !== "todos") preds.push({ clave: "proceso", pasa: (c) => procesoDe(c) === f.proceso });
  const estados = new Set(f.estado);
  preds.push({ clave: "estado", pasa: (c) => estados.has(estadoDe(c)) });
  const rango = rangoDe(f, hoy);
  if (rango.desde || rango.hasta) preds.push({ clave: "fecha", pasa: (c) => enRango(c, rango) });
  for (const [clave, ids] of Object.entries(f.sel)) {
    const faceta = facetaPorClave(clave);
    if (!faceta || ids.length === 0) continue;
    const elegidos = new Set(ids);
    preds.push({ clave, pasa: (c) => lista(faceta.valor(c)).some((v) => elegidos.has(v)) });
  }
  if (f.q.trim()) preds.push({ clave: "q", pasa: (c) => coincideBusqueda(c, f.q) });
  return preds;
}

function omite(omitir: Omitir | undefined, clave: string): boolean {
  if (omitir === undefined) return false;
  if (typeof omitir === "string") return omitir === clave;
  if (typeof omitir === "function") return omitir(clave);
  return omitir.includes(clave);
}

export const pasa = (caso: CasoResumen, preds: readonly Predicado[], omitir?: Omitir): boolean =>
  preds.every((p) => omite(omitir, p.clave) || p.pasa(caso));

export function contar(
  casos: readonly CasoResumen[],
  preds: readonly Predicado[],
  omitir?: Omitir,
  prueba: (caso: CasoResumen) => boolean = () => true,
): number {
  let n = 0;
  for (const c of casos) if (prueba(c) && pasa(c, preds, omitir)) n += 1;
  return n;
}

export function conteoEstados(casos: readonly CasoResumen[], preds: readonly Predicado[]): Record<EstadoUi, number> {
  const n = Object.fromEntries(ESTADOS.map((e) => [e.id, 0])) as Record<EstadoUi, number>;
  for (const c of casos) if (pasa(c, preds, "estado")) n[estadoDe(c)] += 1;
  return n;
}

export function conteoPestanas(casos: readonly CasoResumen[], preds: readonly Predicado[]): Record<ProcesoFiltro, number> {
  const n = Object.fromEntries(PROCESOS.map((p) => [p.id, 0])) as Record<ProcesoFiltro, number>;
  for (const c of casos) {
    if (!pasa(c, preds, OMITIR_PESTANAS)) continue;
    n.todos += 1;
    n[procesoDe(c)] += 1;
  }
  return n;
}

export function conteoOpciones(casos: readonly CasoResumen[], preds: readonly Predicado[], faceta: Faceta): Map<string, number> {
  const n = new Map<string, number>();
  for (const c of casos) {
    if (!pasa(c, preds, faceta.clave)) continue;
    for (const id of new Set(lista(faceta.valor(c)))) n.set(id, (n.get(id) ?? 0) + 1);
  }
  return n;
}

export function conteoFechas(casos: readonly CasoResumen[], preds: readonly Predicado[], hoy: Date): Record<"todo" | PresetFecha, number> {
  const rangos = FECHAS.map((p) => [p.id, rangoPreset(p.id, hoy)] as const);
  const n = Object.fromEntries(FECHAS.map((p) => [p.id, 0])) as Record<"todo" | PresetFecha, number>;
  for (const c of casos) {
    if (!pasa(c, preds, "fecha")) continue;
    for (const [id, rango] of rangos) if (enRango(c, rango)) n[id] += 1;
  }
  return n;
}

export function conteoPlazos(casos: readonly CasoResumen[], preds: readonly Predicado[]): Record<PlazoId, number> {
  const n = Object.fromEntries(PLAZOS.map((p) => [p.id, 0])) as Record<PlazoId, number>;
  for (const c of casos) if (pasa(c, preds, PLAZO.clave)) n[plazoDe(c)] += 1;
  return n;
}

export function procesoActivo(f: Filtros, casos: readonly CasoResumen[]): TipoProceso | null {
  if (f.proceso !== "todos") return f.proceso;
  const presentes = new Set(casos.map(procesoDe));
  return presentes.size === 1 ? [...presentes][0]! : null;
}

/* ---------- Cambios ---------- */

export function elegirEstado(f: Filtros, id: EstadoUi): Filtros {
  const esDefecto = mismoConjunto(f.estado, ESTADOS_DEFECTO);
  let nuevo: EstadoUi[];
  if (esDefecto && id !== "terminado") nuevo = [id];
  else nuevo = f.estado.includes(id) ? f.estado.filter((e) => e !== id) : [...f.estado, id];
  if (nuevo.length === 0) return { ...f, estado: ESTADOS_DEFECTO };
  return { ...f, estado: ESTADOS.map((e) => e.id).filter((e) => nuevo.includes(e)) };
}

export function fijar(f: Filtros, clave: string, ids: readonly string[]): Filtros {
  const { [clave]: _, ...resto } = f.sel;
  return { ...f, sel: ids.length > 0 ? { ...resto, [clave]: ids } : resto };
}

export function alternar(f: Filtros, clave: string, id: string): Filtros {
  const actual = f.sel[clave] ?? [];
  return fijar(f, clave, actual.includes(id) ? actual.filter((x) => x !== id) : [...actual, id]);
}

export function limpiar(f: Filtros, defaults: Filtros): { filtros: Filtros; deshacer: Filtros } {
  return { filtros: { ...f, q: "", estado: defaults.estado, fecha: "todo", desde: "", hasta: "", sel: {} }, deshacer: f };
}

/** Restaura lo que limpiar() quitó, conservando el orden, la agrupación y el proceso actuales. */
export const deshacer = (actual: Filtros, guardado: Filtros): Filtros => ({
  ...actual,
  q: guardado.q,
  estado: guardado.estado,
  fecha: guardado.fecha,
  desde: guardado.desde,
  hasta: guardado.hasta,
  sel: guardado.sel,
});

export interface Activo {
  clave: string;
  texto: string;
}

/** Filtros aplicados en orden: estado, fecha, facetas (en el orden de `facetas`), búsqueda. El proceso no cuenta. */
export function activos(f: Filtros, defaults: Filtros, facetas: readonly Faceta[]): Activo[] {
  const r: Activo[] = [];
  if (!mismoConjunto(f.estado, defaults.estado)) r.push({ clave: "estado", texto: "Estado" });
  const fecha = textoFecha(f);
  if (fecha) r.push({ clave: "fecha", texto: `Trabajado: ${fecha}` });
  const claves = [...facetas.map((x) => x.clave), ...Object.keys(f.sel).filter((k) => !facetas.some((x) => x.clave === k))];
  for (const clave of claves) {
    const ids = f.sel[clave];
    if (!ids?.length) continue;
    const faceta = facetas.find((x) => x.clave === clave) ?? facetaPorClave(clave);
    const nombres = ids.map((id) => faceta?.opciones.find((o) => o.id === id)?.etiqueta ?? id);
    r.push({ clave, texto: `${faceta?.etiqueta ?? clave}: ${nombres.join(", ")}` });
  }
  if (f.q.trim()) r.push({ clave: "q", texto: `Búsqueda «${f.q.trim()}»` });
  return r;
}

export function quitarFiltro(f: Filtros, clave: string, defaults: Filtros): Filtros {
  if (clave === "estado") return { ...f, estado: defaults.estado };
  if (clave === "fecha") return elegirPreset(f, "todo");
  if (clave === "q") return { ...f, q: "" };
  return fijar(f, clave, []);
}

/** El filtro aplicado cuya retirada muestra más casos (solo si muestra alguno); empate: el primero de activos(). */
export function sugerencia(
  casos: readonly CasoResumen[],
  f: Filtros,
  defaults: Filtros,
  facetas: readonly Faceta[],
  hoy: Date,
): (Activo & { n: number }) | null {
  let mejor: (Activo & { n: number }) | null = null;
  for (const a of activos(f, defaults, facetas)) {
    const n = contar(casos, predicados(quitarFiltro(f, a.clave, defaults), hoy));
    if (n > 0 && (!mejor || n > mejor.n)) mejor = { ...a, n };
  }
  return mejor;
}

/* ---------- Orden, grupos y fila ---------- */

const tiempo = (c: CasoResumen) => {
  const t = Date.parse(c.actualizado);
  return Number.isNaN(t) ? 0 : t;
};
const masReciente = (a: CasoResumen, b: CasoResumen) => tiempo(b) - tiempo(a);
/** Vencimiento más cercano primero; sin vencimiento, al final. Las fechas "AAAA-MM-DD" se comparan como texto. */
const venceAntes = (a: CasoResumen, b: CasoResumen) => {
  const [x, y] = [plazoDe(a) === "sin" ? null : a.vence, plazoDe(b) === "sin" ? null : b.vence];
  if (!x || !y) return (x ? 0 : 1) - (y ? 0 : 1);
  return x < y ? -1 : x > y ? 1 : 0;
};
const urgencia = (c: CasoResumen) => (urgente(c) ? 0 : 1);

const COMPARAR: Record<Orden, (a: CasoResumen, b: CasoResumen) => number> = {
  prioridad: (a, b) => urgencia(a) - urgencia(b) || PRIORIDAD[estadoDe(a)] - PRIORIDAD[estadoDe(b)] || venceAntes(a, b) || masReciente(a, b),
  // Sin término, los abiertos antes que los terminados.
  vence: (a, b) => venceAntes(a, b) || Number(estadoDe(a) === "terminado") - Number(estadoDe(b) === "terminado") || masReciente(a, b),
  reciente: masReciente,
  antiguo: (a, b) => -masReciente(a, b),
  radicado: (a, b) => {
    if (!a.radicado || !b.radicado) return (a.radicado ? 0 : 1) - (b.radicado ? 0 : 1) || masReciente(a, b);
    return a.radicado.localeCompare(b.radicado, "es", { numeric: true }) || masReciente(a, b);
  },
};

export const ordenarPor = (casos: readonly CasoResumen[], orden: Orden): CasoResumen[] => [...casos].sort(COMPARAR[orden]);

export interface Grupo {
  id: string;
  /** "" sin agrupar. */
  titulo: string;
  /** Los casos del grupo dentro de los primeros `limite`. */
  casos: CasoResumen[];
  /** Todos los casos del grupo. */
  total: number;
}

export function agruparPor(ordenados: readonly CasoResumen[], agrupacion: Agrupacion, limite = Infinity): Grupo[] {
  const mostrados = ordenados.slice(0, limite);
  if (agrupacion === "ninguno") return mostrados.length ? [{ id: "todos", titulo: "", casos: mostrados, total: ordenados.length }] : [];
  const grupos: readonly { id: string; etiqueta: string }[] = agrupacion === "plazo" ? PLAZOS : ESTADOS;
  const de: (c: CasoResumen) => string = agrupacion === "plazo" ? plazoDe : estadoDe;
  return grupos
    .map((g) => ({
      id: g.id,
      titulo: g.etiqueta,
      casos: mostrados.filter((c) => de(c) === g.id),
      total: ordenados.filter((c) => de(c) === g.id).length,
    }))
    .filter((g) => g.casos.length > 0);
}

/** Los datos propios de la fila; `eco` si el filtro que reflejan tiene elegido su valor. */
export function datosFila(caso: CasoResumen, f: Filtros): (DatoFila & { eco: boolean })[] {
  const proceso = procesoDe(caso);
  return FILA[proceso](caso)
    .filter((d): d is DatoFila => d !== null)
    .map((d) => {
      const elegidos = d.clave ? (f.sel[clavePropia(proceso, d.clave)] ?? []) : [];
      return { ...d, eco: lista(d.valor).some((v) => elegidos.includes(v)) };
    });
}

/* ---------- URL ---------- */

export interface Contexto {
  defaults: Filtros;
  /** Los casos en alcance, para validar las opciones de juzgado y entidad. */
  casos?: readonly CasoResumen[];
}

const valores = (ids: readonly string[]) => ids.map(encodeURIComponent).join(",");

export function serializar(f: Filtros, defaults: Filtros): string {
  const partes: string[] = [];
  if (f.q.trim()) partes.push(`q=${encodeURIComponent(f.q)}`);
  if (f.proceso !== defaults.proceso) partes.push(`p=${f.proceso}`);
  if (!mismoConjunto(f.estado, defaults.estado)) partes.push(`e=${ESTADOS.filter((e) => f.estado.includes(e.id)).map((e) => e.id).join(",")}`);
  if (f.fecha === "rango") {
    if (f.desde) partes.push(`d=${f.desde}`);
    if (f.hasta) partes.push(`h=${f.hasta}`);
  } else if (f.fecha !== "todo") partes.push(`f=${f.fecha}`);
  const plazos = f.sel[PLAZO.clave] ?? [];
  if (plazos.length) partes.push(`pl=${PLAZOS.filter((p) => plazos.includes(p.id)).map((p) => p.id).join(",")}`);
  for (const clave of Object.keys(f.sel).sort()) {
    const ids = f.sel[clave] ?? [];
    if (ids.length && clave !== PLAZO.clave) partes.push(`s.${encodeURIComponent(clave)}=${valores([...ids].sort())}`);
  }
  if (f.orden !== defaults.orden) partes.push(`o=${f.orden}`);
  if (f.agrupar !== defaults.agrupar) partes.push(`g=${f.agrupar}`);
  return partes.join("&");
}

const decodificar = (texto: string) => {
  try {
    return decodeURIComponent(texto.replace(/\+/g, " "));
  } catch {
    return "";
  }
};

export function deserializar(consulta: string, contexto: Contexto): Filtros {
  const f = { ...contexto.defaults, sel: {} as Record<string, string[]> };
  let preset: string | null = null;
  let desde = "";
  let hasta = "";
  for (const parte of consulta.replace(/^\?/, "").split("&")) {
    if (!parte) continue;
    const i = parte.indexOf("=");
    const clave = decodificar(i < 0 ? parte : parte.slice(0, i));
    const crudo = i < 0 ? "" : parte.slice(i + 1);
    const ids = crudo.split(",").map(decodificar).filter(Boolean);
    if (clave === "q") f.q = decodificar(crudo);
    else if (clave === "p") f.proceso = decodificar(crudo) as ProcesoFiltro;
    else if (clave === "e") f.estado = ids as EstadoUi[];
    else if (clave === "f") preset = decodificar(crudo);
    else if (clave === "d") desde = decodificar(crudo);
    else if (clave === "h") hasta = decodificar(crudo);
    else if (clave === "pl") f.sel[PLAZO.clave] = ids;
    else if (clave === "o") f.orden = decodificar(crudo) as Orden;
    else if (clave === "g") f.agrupar = decodificar(crudo) as Agrupacion;
    else if (clave.startsWith("s.") && clave.length > 2) f.sel[clave.slice(2)] = ids;
  }
  if (preset !== null) Object.assign(f, { fecha: preset, desde: "", hasta: "" });
  else if (desde || hasta) Object.assign(f, { fecha: "rango", desde, hasta });
  return validar(f, contexto);
}

const diaValido = (texto: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto);
  return !!m && diaIso(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))) === texto;
};

const texto = (x: unknown) => (typeof x === "string" ? x : "");

export function validar(f: Filtros, { defaults, casos }: Contexto): Filtros {
  // En Inicio, un proceso sin casos dejaría la lista vacía y sin pestañas para salir de él.
  const conCasos = (p: ProcesoFiltro) => p === "todos" || !casos || casos.some((c) => procesoDe(c) === p);
  const proceso = defaults.proceso !== "todos" ? defaults.proceso : esProceso(texto(f.proceso)) && conCasos(f.proceso) ? f.proceso : defaults.proceso;
  const pedidos = Array.isArray(f.estado) ? f.estado.filter((e) => esEstado(texto(e))) : [];
  const estado = pedidos.length ? ESTADOS.map((e) => e.id).filter((e) => pedidos.includes(e)) : defaults.estado;
  let fecha: ModoFecha = f.fecha === "rango" || FECHAS.some((p) => p.id === f.fecha) ? f.fecha : "todo";
  let desde = fecha === "rango" && diaValido(texto(f.desde)) ? f.desde : "";
  let hasta = fecha === "rango" && diaValido(texto(f.hasta)) ? f.hasta : "";
  if (fecha === "rango" && !desde && !hasta) fecha = "todo";
  if (desde && hasta && desde > hasta) [desde, hasta] = [hasta, desde];
  // Las claves propias solo valen para el proceso cuyo carril se ve (la misma regla que al cambiar de pestaña).
  // Sin `casos` y en «Todos» no se sabe cuál es (undefined): se conservan.
  const activo = casos ? procesoActivo({ ...f, proceso }, casos) : proceso === "todos" ? undefined : proceso;
  const sel: Record<string, string[]> = {};
  for (const [clave, ids] of Object.entries(f.sel ?? {})) {
    const faceta = facetaPorClave(clave, casos);
    if (!faceta || !Array.isArray(ids)) continue;
    if (esPropia(clave) && activo !== undefined && clave.split(".")[0] !== activo) continue;
    // Un interruptor solo enciende su opción; otra (s.alertas=sin) filtraría sin que el botón lo muestre.
    const validos = faceta.tipo === "interruptor" ? new Set([faceta.activo]) : faceta.dinamica && !casos ? null : new Set(faceta.opciones.map((o) => o.id));
    const limpios = [...new Set(ids.map(texto))].filter((id) => id !== "" && (!validos || validos.has(id)));
    if (limpios.length) sel[clave] = limpios;
  }
  return {
    q: texto(f.q),
    proceso,
    estado,
    fecha,
    desde,
    hasta,
    sel,
    orden: ORDENES.some((o) => o.id === f.orden) ? f.orden : defaults.orden,
    agrupar: AGRUPACIONES.some((a) => a.id === f.agrupar) ? f.agrupar : defaults.agrupar,
  };
}
