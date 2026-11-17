/**
 * Registro de la lista compartida «Mi trabajo»: qué procesos, estados y facetas existen. Sin DOM ni Preact.
 * Lo único que cambia entre procesos son PROPIAS y FILA; el motor (filtros.ts) solo lee este registro.
 *
 * Procesos
 *   PROCESOS: { id, corto, largo, proximamente? }[]  pestañas en orden: todos, primera, segunda, desacato, penal.
 *   infoProceso(id) / esProceso(x)            búsqueda y guarda de tipo.
 *   procesoDe(caso): TipoProceso              caso.proceso.
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
 *   PROPIAS[proceso](casos)                   facetas propias con clave local ("aquo"); `casos` da las opciones
 *   propias(proceso, casos?)                  dinámicas (Derecho, «Sin dato»). propias() antepone el proceso a la
 *                                             clave ("segunda.aquo", en la URL s.segunda.aquo); propiasVisibles()
 *                                             omite además las dinámicas sin opciones. Hoy solo «segunda» tiene facetas: Decisión
 *                                             1ª inst., Impugnó, Sentido 2ª inst., Derecho, Por revisar y el
 *                                             interruptor Con pruebas nuevas, todas sobre caso.segunda (null = sin
 *                                             datos: ningún valor, o «Sin dato»/«Sin decidir»).
 *   FILA[proceso](caso): DatoFila[]           datos propios que la fila muestra; clave/valor dicen qué filtro
 *                                             reflejan (filtros.datosFila calcula el resaltado).
 *   facetaPorClave(clave, casos?)             la faceta de una clave de filtro, o undefined si no existe.
 *
 * Plazos (término para fallar: caso.vence y caso.dias_restantes, calculados por el servidor)
 *   PLAZOS: { id, etiqueta, tono }[]          cubetas en orden de urgencia: vencido (< 0), pronto (hoy o en 1 día: 0 y 1),
 *                                             semana (2 a 5), despues (6 o más) y sin (sin término, o terminado). Los
 *                                             días se cuentan en la unidad del término (hábiles o calendario).
 *   plazoDe(caso): PlazoId                    la cubeta del caso. PLAZO es su faceta (clave "plazo", en la URL pl=);
 *                                             no tiene pastilla: la filtran las baldosas del Tablero.
 *   textoPlazo(caso, hoy), tituloPlazo(caso)  el chip de la fila («Venció hace 2 días hábiles», «Vence hoy»,
 *                                             «Faltan 3 días hábiles») y su título («Recibido el …; vence el …»).
 *   tonoPlazo(caso)                           el tono del chip: "mal" si venció o vence hoy, "alerta" si faltan de
 *                                             1 a 5 días, "neutro" después (el de las baldosas, como el prototipo).
 *   urgente(caso)                             vencido o vence hoy.
 *   esPropia(clave), opciones(...etiquetas)   ayudas.
 */
import type { CasoResumen, DatosSegunda, EstadoCasoApi, ImpugnanteCaso, ResultadoCaso, SentidoAQuo, SustitutivaCaso } from "../../api/contrato";
import { diaIso, plural, textoDiasRestantes } from "../../estado/formato";
import { plano, type TonoFicha } from "./agrupar";
import type { TipoProceso } from "./iconos";

export type { TipoProceso };
export type ProcesoFiltro = "todos" | TipoProceso;

export interface InfoProceso {
  id: ProcesoFiltro;
  corto: string;
  largo: string;
  /** Aún no se puede trabajar en él (Inicio lo marca «Próximamente»); quítelo al implementarlo. */
  proximamente?: true;
}

export const PROCESOS: readonly InfoProceso[] = [
  { id: "todos", corto: "Todos", largo: "Todos los procesos" },
  { id: "primera", corto: "1ª instancia", largo: "Fallos de tutela de primera instancia", proximamente: true },
  { id: "segunda", corto: "2ª instancia", largo: "Fallos de tutela de segunda instancia" },
  { id: "desacato", corto: "Desacato", largo: "Incidentes de desacato", proximamente: true },
  { id: "penal", corto: "Penal", largo: "Penal", proximamente: true },
];

export const infoProceso = (id: ProcesoFiltro): InfoProceso => PROCESOS.find((p) => p.id === id) ?? PROCESOS[0]!;

export const esProceso = (x: string): x is ProcesoFiltro => PROCESOS.some((p) => p.id === x);

/** El proceso del caso. */
export const procesoDe = (caso: CasoResumen): TipoProceso => caso.proceso;

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

export interface DatoFila {
  texto: string;
  tono?: "ok" | "alerta" | "mal";
  /** Clave local de la faceta que este dato refleja (sin prefijo de proceso). */
  clave?: string;
  /** Id o ids de opción de esa faceta; si alguno está elegido, el dato se resalta. */
  valor?: string | readonly string[];
}

/* ---------- Segunda instancia (caso.segunda) ---------- */

const SIN_DATO = "sin_dato";
const SIN_DECIDIR = "sin_decidir";

const AQUO: Readonly<Record<SentidoAQuo, string>> = {
  ampara: "Amparó",
  niega: "Negó el amparo",
  improcedente: "Declaró improcedente",
  carencia_actual_de_objeto: "Carencia actual de objeto",
  otro: "Otra",
};

const IMPUGNA: Readonly<Record<ImpugnanteCaso, string>> = {
  accionante: "Accionante",
  accionada: "Accionada",
  vinculada: "Vinculada",
  otro: "Otro",
  varios: "Varios",
};

/** Ids en minúscula para la URL (s.segunda.sentido=revoca); etiquetas en el tiempo del fallo ya dictado. */
const SENTIDO: Readonly<Record<ResultadoCaso, Opcion>> = {
  CONFIRMAR: { id: "confirma", etiqueta: "Confirma" },
  REVOCAR: { id: "revoca", etiqueta: "Revoca" },
  MODIFICAR: { id: "modifica", etiqueta: "Modifica" },
};

/** Lo que sigue al verbo en el dato de la fila: «Fallo: revoca y ampara». */
const SUSTITUTIVA: Readonly<Record<SustitutivaCaso, string>> = {
  AMPARAR: "y ampara",
  NEGAR: "y niega",
  IMPROCEDENTE: "y declara improcedente",
  CARENCIA_HECHO_SUPERADO: "y declara hecho superado",
  CARENCIA_DANO_CONSUMADO: "y declara daño consumado",
  CARENCIA_SOBREVINIENTE: "y declara situación sobreviniente",
};

const deRegistro = (r: Readonly<Record<string, string>>): Opcion[] => Object.entries(r).map(([id, etiqueta]) => ({ id, etiqueta }));

/** Las opciones fijas más la de «sin valor» si algún caso cae en ella (sin `casos`, siempre, para validar la URL). */
const conVacia = (fijas: Opcion[], casos: readonly CasoResumen[], valor: (c: CasoResumen) => string, vacia: Opcion): Opcion[] =>
  casos.length === 0 || casos.some((c) => valor(c) === vacia.id) ? [...fijas, vacia] : fijas;

const seg = (c: CasoResumen): DatosSegunda | null => c.segunda ?? null;

const aquoDe = (c: CasoResumen) => seg(c)?.decision_a_quo ?? SIN_DATO;
const sentidoDe = (c: CasoResumen) => {
  const r = seg(c)?.resultado;
  return r ? SENTIDO[r].id : SIN_DECIDIR;
};
const derechosDe = (c: CasoResumen) => seg(c)?.derechos ?? [];

function segunda(casos: readonly CasoResumen[]): Faceta[] {
  return [
    {
      clave: "aquo",
      etiqueta: "Decisión de primera instancia",
      corto: "Decisión 1ª inst.",
      tipo: "varias",
      opciones: conVacia(deRegistro(AQUO), casos, aquoDe, { id: SIN_DATO, etiqueta: "Sin dato" }),
      valor: aquoDe,
    },
    {
      clave: "impugna",
      etiqueta: "Quién impugnó",
      corto: "Impugnó",
      tipo: "varias",
      opciones: deRegistro(IMPUGNA),
      valor: (c) => seg(c)?.impugnante,
    },
    {
      clave: "sentido",
      etiqueta: "Sentido del fallo de segunda instancia",
      corto: "Sentido 2ª inst.",
      tipo: "varias",
      opciones: conVacia(Object.values(SENTIDO), casos, sentidoDe, { id: SIN_DECIDIR, etiqueta: "Sin decidir" }),
      valor: sentidoDe,
    },
    {
      clave: "derecho",
      etiqueta: "Derecho invocado",
      corto: "Derecho",
      tipo: "buscable",
      dinamica: true,
      opciones: dinamicas(casos, derechosDe),
      valor: (c) => derechosDe(c).map(normalizar),
    },
    {
      clave: "revisar",
      etiqueta: "Por revisar antes de decidir",
      corto: "Por revisar",
      tipo: "varias",
      opciones: [
        { id: "citas", etiqueta: "Citas por revisar" },
        { id: "jev", etiqueta: "Jev discrepa" },
      ],
      valor: (c) => [(seg(c)?.n_citas_revisar ?? 0) > 0 ? "citas" : null, seg(c)?.jev_discrepa ? "jev" : null],
    },
    {
      clave: "pruebas",
      etiqueta: "Pruebas nuevas en segunda instancia",
      corto: "Con pruebas nuevas",
      tipo: "interruptor",
      activo: "con",
      opciones: [
        { id: "con", etiqueta: "Con pruebas nuevas" },
        { id: "sin", etiqueta: "Sin pruebas nuevas" },
      ],
      valor: (c) => {
        const p = seg(c)?.pruebas_nuevas;
        return p === true ? "con" : p === false ? "sin" : null;
      },
    },
  ];
}

function filaSegunda(c: CasoResumen): (DatoFila | null)[] {
  const s = seg(c);
  if (!s) return [];
  const sentido = s.resultado ? SENTIDO[s.resultado] : null;
  const sustitutiva = s.resultado !== "CONFIRMAR" && s.sustitutiva ? ` ${SUSTITUTIVA[s.sustitutiva]}` : "";
  const citas = s.n_citas_revisar ?? 0;
  return [
    s.decision_a_quo ? { texto: `1ª inst.: ${AQUO[s.decision_a_quo]}`, clave: "aquo", valor: s.decision_a_quo } : null,
    s.impugnante ? { texto: `Impugna: ${IMPUGNA[s.impugnante].toLowerCase()}`, clave: "impugna", valor: s.impugnante } : null,
    sentido ? { texto: `Fallo: ${sentido.etiqueta.toLowerCase()}${sustitutiva}`, tono: "ok", clave: "sentido", valor: sentido.id } : null,
    s.pruebas_nuevas ? { texto: "Pruebas nuevas en 2ª", clave: "pruebas", valor: "con" } : null,
    citas > 0 ? { texto: `${plural(citas, "cita")} por revisar`, tono: "alerta", clave: "revisar", valor: "citas" } : null,
    s.jev_discrepa ? { texto: "Jev discrepa", tono: "alerta", clave: "revisar", valor: "jev" } : null,
  ];
}

const ninguna = (): Faceta[] => [];

/** Facetas propias de cada proceso, con clave local ("aquo"). `casos`: los casos en alcance, para las opciones dinámicas. */
export const PROPIAS: Readonly<Record<TipoProceso, (casos: readonly CasoResumen[]) => readonly Faceta[]>> = {
  primera: ninguna,
  segunda,
  desacato: ninguna,
  penal: ninguna,
};

/** Clave de filtro de una faceta propia: "<proceso>.<clave>". */
export const clavePropia = (proceso: TipoProceso, clave: string) => `${proceso}.${clave}`;

/** ¿La clave de filtro es de un proceso concreto? Las pestañas de proceso las ignoran al contar. */
export const esPropia = (clave: string) => clave.includes(".");

/** Las facetas propias del proceso, con la clave ya prefijada para usarla en Filtros.sel. Sin `casos`, las dinámicas vienen sin opciones. */
export const propias = (proceso: TipoProceso | null, casos: readonly CasoResumen[] = []): Faceta[] =>
  proceso ? PROPIAS[proceso](casos).map((f) => ({ ...f, clave: clavePropia(proceso, f.clave) })) : [];

/** Las propias que se muestran: sin las dinámicas que se quedaron sin opciones (p. ej. Derecho sin derechos). */
export const propiasVisibles = (proceso: TipoProceso | null, casos: readonly CasoResumen[]): Faceta[] =>
  propias(proceso, casos).filter((f) => !f.dinamica || f.opciones.length > 0);

const sinDatos = (): (DatoFila | null)[] => [];

/** Datos propios que cada fila muestra según su proceso. */
export const FILA: Readonly<Record<TipoProceso, (caso: CasoResumen) => readonly (DatoFila | null)[]>> = {
  primera: sinDatos,
  segunda: filaSegunda,
  desacato: sinDatos,
  penal: sinDatos,
};

/* ---------- Plazos ---------- */

export type PlazoId = "vencido" | "pronto" | "semana" | "despues" | "sin";

export interface InfoPlazo {
  id: PlazoId;
  etiqueta: string;
  tono: "mal" | "alerta" | "";
}

/** Cubetas del término en orden de urgencia; las tres primeras son las baldosas del Tablero. */
export const PLAZOS: readonly InfoPlazo[] = [
  { id: "vencido", etiqueta: "Vencidos", tono: "mal" },
  { id: "pronto", etiqueta: "Vencen hoy o en 1 día", tono: "alerta" },
  { id: "semana", etiqueta: "Vencen en 2 a 5 días", tono: "" },
  { id: "despues", etiqueta: "Vencen en 6 días o más", tono: "" },
  { id: "sin", etiqueta: "Sin término calculado", tono: "" },
];

/** Días que faltan (0 = vence hoy, negativo = vencido), o null si el caso terminó o no tiene término. */
const restantes = (c: CasoResumen): number | null => (c.estado === "terminado" || c.vence == null ? null : c.dias_restantes);

export function plazoDe(c: CasoResumen): PlazoId {
  const r = restantes(c);
  if (r == null) return "sin";
  if (r < 0) return "vencido";
  if (r <= 1) return "pronto";
  return r <= 5 ? "semana" : "despues";
}

/** Vencido o vence hoy: va primero en «Lo que me toca primero» y su chip va en rojo. */
export const urgente = (c: CasoResumen): boolean => (restantes(c) ?? 1) <= 0;

/** Tono del chip de plazo de la fila: rojo si venció o vence hoy, ámbar si faltan de 1 a 5 días, neutro después. */
export function tonoPlazo(c: CasoResumen): "mal" | "alerta" | "neutro" {
  if (urgente(c)) return "mal";
  const p = plazoDe(c);
  return p === "pronto" || p === "semana" ? "alerta" : "neutro";
}

/** Texto del chip de plazo de la fila, o null sin plazo. `hoy` decide si el día que falta es «mañana». */
export function textoPlazo(c: CasoResumen, hoy: Date): string | null {
  const r = restantes(c);
  if (r == null) return null;
  const manana = diaIso(new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() + 1));
  if (r === 1 && c.vence === manana) return "Vence mañana";
  return textoDiasRestantes(r, c.termino?.unidad ?? "habiles");
}

const fechaLarga = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "long", year: "numeric" });
const dia = (iso: string) => {
  const [a, m, d] = iso.split("-").map(Number);
  return fechaLarga.format(new Date(a!, m! - 1, d));
};

/** Título del chip de plazo: «Recibido el 21 de octubre de 2026; vence el 20 de noviembre de 2026 (20 días hábiles)». */
export function tituloPlazo(c: CasoResumen): string {
  if (!c.vence) return "";
  if (!c.termino) return `Vence el ${dia(c.vence)}`;
  const { inicio, dias, unidad } = c.termino;
  const plazo = unidad === "calendario" ? `${plural(dias, "día")} calendario` : plural(dias, "día hábil", "días hábiles");
  return `Recibido el ${dia(inicio)}; vence el ${dia(c.vence)} (${plazo})`;
}

/** El plazo como faceta: lo filtran las baldosas del Tablero (sin pastilla); en la URL va como pl=. */
export const PLAZO: Faceta = {
  clave: "plazo",
  etiqueta: "Plazo",
  corto: "Plazo",
  tipo: "varias",
  opciones: PLAZOS.map((p) => ({ id: p.id, etiqueta: p.etiqueta })),
  valor: plazoDe,
};

/** La faceta que corresponde a una clave de filtro (general o propia). Sin `casos`, las dinámicas vienen sin opciones. */
export function facetaPorClave(clave: string, casos: readonly CasoResumen[] = []): Faceta | undefined {
  if (clave === "plazo") return PLAZO;
  if (clave === "juzgado") return juzgado(null, casos);
  if (clave === "entidad") return entidad(null, casos);
  if (clave === "alertas") return ALERTAS;
  const [proceso = "", local] = clave.split(".", 2);
  if (!esProceso(proceso) || proceso === "todos" || !local) return undefined;
  return propias(proceso, casos).find((f) => f.clave === clave);
}
