import type { EvidenciaVista } from "../../api/contrato";

export interface Segmento {
  texto: string;
  marcado: boolean;
}

export type Tramo = readonly [inicio: number, fin: number];

export type PasajeCitado = Pick<EvidenciaVista, "cita" | "inicio" | "fin">;

interface Ficha {
  clave: string;
  a: number;
  b: number;
}

const PALABRA = /[\p{L}\p{N}\p{M}]+/gu;
const MARCAS = /\p{M}/gu;
// Entre dos palabras: el guion de fin de renglón (con su salto) o el guion blando.
const GUION_DE_RENGLON = /^(?:­|[-‐‑]\s*[\r\n]\s*)$/;
// La cita llega con los saltos de renglón colapsados: "pro- cesal" por "pro-\ncesal".
const GUION_COLAPSADO = /^(?:­|[-‐‑]\s+)$/;
const ANCLA = 4;
const MARGEN_ANCLAS = 20;

const plegar = (texto: string): string => texto.normalize("NFD").replace(MARCAS, "").toLowerCase();

function fichas(texto: string): Ficha[] {
  const salida: Ficha[] = [];
  for (const m of texto.matchAll(PALABRA)) {
    const clave = plegar(m[0]);
    if (clave) salida.push({ clave, a: m.index, b: m.index + m[0].length });
  }
  return salida;
}

function unirGuiones(texto: string, lista: Ficha[], union: RegExp): Ficha[] {
  const salida: Ficha[] = [];
  for (const ficha of lista) {
    const previa = salida[salida.length - 1];
    if (previa && union.test(texto.slice(previa.b, ficha.a))) {
      salida[salida.length - 1] = { clave: previa.clave + ficha.clave, a: previa.a, b: ficha.b };
    } else {
      salida.push(ficha);
    }
  }
  return salida;
}

function indiceDe(pajar: Ficha[], aguja: Ficha[], desde = 0): number {
  const n = aguja.length;
  for (let i = desde; i + n <= pajar.length; i++) {
    let j = 0;
    while (j < n && pajar[i + j]!.clave === aguja[j]!.clave) j++;
    if (j === n) return i;
  }
  return -1;
}

function recortar(texto: string, inicio: number, fin: number): Tramo | null {
  const trozo = texto.slice(inicio, fin);
  const izquierda = trozo.length - trozo.replace(/^\s+/, "").length;
  const derecha = trozo.length - trozo.replace(/\s+$/, "").length;
  const a = inicio + izquierda;
  const b = fin - derecha;
  return a < b ? [a, b] : null;
}

function porOffsets(texto: string, { cita, inicio, fin }: PasajeCitado): Tramo | null {
  if (inicio == null || fin == null || !Number.isInteger(inicio) || !Number.isInteger(fin)) return null;
  if (inicio < 0 || fin > texto.length || inicio >= fin) return null;
  const buscada = fichas(cita);
  if (buscada.length > 0) {
    const leida = fichas(texto.slice(inicio, fin));
    const k = Math.min(3, leida.length, buscada.length);
    if (k === 0) return null;
    const mismos = (a: Ficha[], b: Ficha[]) => a.every((f, i) => f.clave === b[i]!.clave);
    const empieza = mismos(leida.slice(0, k), buscada.slice(0, k));
    const termina = mismos(leida.slice(leida.length - k), buscada.slice(buscada.length - k));
    if (!empieza || !termina) return null;
  }
  return recortar(texto, inicio, fin);
}

function porTexto(texto: string, cita: string): Tramo | null {
  const buscada = fichas(cita);
  if (buscada.length === 0) return null;
  const sueltas = fichas(texto);
  const variantes: [Ficha[], Ficha[]][] = [
    [sueltas, buscada],
    [unirGuiones(texto, sueltas, GUION_DE_RENGLON), unirGuiones(cita, buscada, GUION_COLAPSADO)],
  ];
  for (const [pajar, aguja] of variantes) {
    const i = indiceDe(pajar, aguja);
    if (i >= 0) return [pajar[i]!.a, pajar[i + aguja.length - 1]!.b];
  }
  // La cita no es literal (puntos suspensivos, una palabra mal leída): se marca desde su comienzo hasta su final.
  for (const [pajar, aguja] of variantes) {
    const k = Math.min(ANCLA, aguja.length);
    if (aguja.length <= k) continue;
    const i = indiceDe(pajar, aguja.slice(0, k));
    if (i < 0) continue;
    const j = indiceDe(pajar, aguja.slice(aguja.length - k), i + k);
    if (j >= 0 && j + k - i <= 3 * aguja.length + MARGEN_ANCLAS) return [pajar[i]!.a, pajar[j + k - 1]!.b];
  }
  return null;
}

/** Dónde está el pasaje en el texto de la página: los offsets del servidor si son verosímiles, y si no, la cita
 * buscada sin distinguir mayúsculas, tildes, espacios ni guiones de fin de renglón. */
export function localizar(texto: string, pasaje: PasajeCitado): Tramo | null {
  return porOffsets(texto, pasaje) ?? porTexto(texto, pasaje.cita);
}

export function resaltar(texto: string, pasaje: PasajeCitado): Segmento[] {
  if (!texto) return [];
  const tramo = localizar(texto, pasaje);
  if (!tramo) return [{ texto, marcado: false }];
  const [a, b] = tramo;
  const segmentos: Segmento[] = [];
  if (a > 0) segmentos.push({ texto: texto.slice(0, a), marcado: false });
  segmentos.push({ texto: texto.slice(a, b), marcado: true });
  if (b < texto.length) segmentos.push({ texto: texto.slice(b), marcado: false });
  return segmentos;
}
