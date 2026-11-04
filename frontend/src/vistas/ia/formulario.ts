import { ErrorApi } from "../../api/cliente";
import type { Effort, ModoJev, PreferenciasIa, PreferenciasIaCuerpo } from "../../api/contrato";

export const MAX_TOKENS = 64000;
export const MAX_REINTENTOS = 5;

export interface Formulario {
  modelo: string;
  modo: ModoJev;
  umbral: number;
  effort: Effort;
  maxTokens: string;
  maxRetries: string;
}

export type CampoForm = "modelo" | "modo" | "umbral" | "effort" | "max_tokens" | "max_retries";
export type ErroresForm = Partial<Record<CampoForm, string>>;

export const CAMPOS_AVANZADOS: readonly CampoForm[] = ["effort", "max_tokens", "max_retries"];

export const ESFUERZOS: { valor: Effort; texto: string }[] = [
  { valor: "low", texto: "Bajo (low)" },
  { valor: "medium", texto: "Medio (medium)" },
  { valor: "high", texto: "Alto (high)" },
  { valor: "xhigh", texto: "Muy alto (xhigh)" },
  { valor: "max", texto: "Máximo (max)" },
];

const CAMPO_SERVIDOR: Record<string, CampoForm> = {
  modelo: "modelo",
  "jev.modo": "modo",
  "jev.umbral": "umbral",
  effort: "effort",
  max_tokens: "max_tokens",
  max_retries: "max_retries",
};

export function aFormulario(p: PreferenciasIa): Formulario {
  return {
    modelo: p.modelo,
    modo: p.jev.modo,
    umbral: Math.round(p.jev.umbral * 100),
    effort: p.effort,
    maxTokens: String(p.max_tokens),
    maxRetries: String(p.max_retries),
  };
}

const entero = (texto: string): number | null => (/^\d+$/.test(texto.trim()) ? Number(texto.trim()) : null);

export function aCuerpo(f: Formulario): PreferenciasIaCuerpo {
  return {
    modelo: f.modelo,
    jev: { modo: f.modo, umbral: Math.round(f.umbral) / 100 },
    effort: f.effort,
    max_tokens: entero(f.maxTokens) ?? 0,
    max_retries: entero(f.maxRetries) ?? 0,
  };
}

export function validar(f: Formulario, modelos: readonly string[]): ErroresForm {
  const errores: ErroresForm = {};
  if (!modelos.includes(f.modelo)) errores.modelo = "Elija uno de los modelos disponibles.";
  if (!Number.isFinite(f.umbral) || f.umbral < 0 || f.umbral > 100) errores.umbral = "Debe estar entre 0 % y 100 %.";
  const tokens = entero(f.maxTokens);
  if (tokens === null || tokens < 1 || tokens > MAX_TOKENS) errores.max_tokens = "Escriba un número entero entre 1 y 64.000.";
  const reintentos = entero(f.maxRetries);
  if (reintentos === null || reintentos > MAX_REINTENTOS) errores.max_retries = `Escriba un número entero entre 0 y ${MAX_REINTENTOS}.`;
  return errores;
}

export function igual(a: Formulario, b: Formulario): boolean {
  return (
    a.modelo === b.modelo &&
    a.modo === b.modo &&
    a.umbral === b.umbral &&
    a.effort === b.effort &&
    a.maxTokens.trim() === b.maxTokens.trim() &&
    a.maxRetries.trim() === b.maxRetries.trim()
  );
}

const mayuscula = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

export interface ErroresServidor {
  campos: ErroresForm;
  generales: string[];
}

export function leerErrorServidor(error: unknown, porDefecto: string): ErroresServidor {
  const vacio: ErroresServidor = { campos: {}, generales: [] };
  if (!(error instanceof ErrorApi)) return { ...vacio, generales: [porDefecto] };
  if (error.estado === 0) return { ...vacio, generales: [error.message] };
  const detalle = error.detalle;
  if (typeof detalle === "string" && detalle) return { ...vacio, generales: [detalle] };
  if (typeof detalle === "object" && detalle !== null && "errores" in detalle && Array.isArray(detalle.errores)) {
    const salida: ErroresServidor = { campos: {}, generales: [] };
    for (const item of detalle.errores as unknown[]) {
      if (typeof item !== "object" || item === null) continue;
      const { campo, mensaje } = item as { campo?: unknown; mensaje?: unknown };
      const texto = typeof mensaje === "string" ? mayuscula(mensaje) : porDefecto;
      const clave = typeof campo === "string" ? CAMPO_SERVIDOR[campo] : undefined;
      if (clave) salida.campos[clave] = texto;
      else salida.generales.push(typeof campo === "string" && campo ? `${campo}: ${texto}` : texto);
    }
    if (salida.generales.length || Object.keys(salida.campos).length) return salida;
  }
  return { ...vacio, generales: [error.estado >= 500 ? "El servidor no pudo completar la operación. Intente de nuevo." : porDefecto] };
}
