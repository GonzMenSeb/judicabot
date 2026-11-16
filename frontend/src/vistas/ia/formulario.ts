import { ErrorApi } from "../../api/cliente";
import type { Effort, ModoJev, PreferenciasIa, PreferenciasIaCuerpo, Proveedor, RazonamientoGemini } from "../../api/contrato";

export const MAX_TOKENS = 64000;
export const MAX_REINTENTOS = 5;

export interface Formulario {
  proveedor: Proveedor;
  modelo: string;
  effort: Effort;
  modeloGemini: string;
  razonamiento: RazonamientoGemini;
  modo: ModoJev;
  umbral: number;
  maxTokens: string;
  maxRetries: string;
}

export type CampoForm = "proveedor" | "modelo" | "effort" | "gemini_modelo" | "razonamiento" | "modo" | "umbral" | "max_tokens" | "max_retries";
export type ErroresForm = Partial<Record<CampoForm, string>>;

export const CAMPOS_AVANZADOS: readonly CampoForm[] = ["max_tokens", "max_retries"];

export const ESFUERZOS: { valor: Effort; texto: string }[] = [
  { valor: "low", texto: "Bajo (low)" },
  { valor: "medium", texto: "Medio (medium)" },
  { valor: "high", texto: "Alto (high)" },
  { valor: "xhigh", texto: "Muy alto (xhigh)" },
  { valor: "max", texto: "Máximo (max)" },
];

export const NIVELES_GEMINI: { valor: RazonamientoGemini; texto: string }[] = [
  { valor: "low", texto: "Bajo (low)" },
  { valor: "medium", texto: "Medio (medium)" },
  { valor: "high", texto: "Alto (high)" },
  { valor: "xhigh", texto: "Muy alto (xhigh)" },
];

const CAMPO_SERVIDOR: Record<string, CampoForm> = {
  proveedor: "proveedor",
  modelo: "modelo",
  effort: "effort",
  "gemini.modelo": "gemini_modelo",
  "gemini.razonamiento": "razonamiento",
  "jev.modo": "modo",
  "jev.umbral": "umbral",
  max_tokens: "max_tokens",
  max_retries: "max_retries",
};

export function aFormulario(p: PreferenciasIa): Formulario {
  return {
    proveedor: p.proveedor,
    modelo: p.modelo,
    effort: p.effort,
    modeloGemini: p.gemini.modelo,
    razonamiento: p.gemini.razonamiento,
    modo: p.jev.modo,
    umbral: Math.round(p.jev.umbral * 100),
    maxTokens: String(p.max_tokens),
    maxRetries: String(p.max_retries),
  };
}

const entero = (texto: string): number | null => (/^\d+$/.test(texto.trim()) ? Number(texto.trim()) : null);

export const nivelesDe = (p: PreferenciasIa, modelo: string): RazonamientoGemini[] => p.razonamientos_gemini[modelo] ?? [];

export function nivelAjustado(p: PreferenciasIa, modelo: string, nivel: RazonamientoGemini): RazonamientoGemini {
  const niveles = nivelesDe(p, modelo);
  return niveles.includes(nivel) || !niveles.length ? nivel : niveles.includes("high") ? "high" : (niveles[niveles.length - 1] ?? nivel);
}

export const editaAnthropic = (p: PreferenciasIa): boolean => p.api_key && p.modelos.length > 0;
export const editaGemini = (p: PreferenciasIa): boolean => p.gemini_key && p.modelos_gemini.length > 0;

export function aCuerpo(f: Formulario, p: PreferenciasIa): PreferenciasIaCuerpo {
  return {
    proveedor: f.proveedor,
    ...(editaAnthropic(p) ? { modelo: f.modelo, effort: f.effort } : {}),
    ...(editaGemini(p) ? { gemini: { modelo: f.modeloGemini, razonamiento: f.razonamiento } } : {}),
    jev: { modo: f.modo, umbral: Math.round(f.umbral) / 100 },
    max_tokens: entero(f.maxTokens) ?? 0,
    max_retries: entero(f.maxRetries) ?? 0,
  };
}

export function validar(f: Formulario, p: PreferenciasIa): ErroresForm {
  const errores: ErroresForm = {};
  if (editaAnthropic(p) && !p.modelos.includes(f.modelo)) errores.modelo = "Elija uno de los modelos disponibles.";
  if (editaGemini(p)) {
    if (!p.modelos_gemini.includes(f.modeloGemini)) errores.gemini_modelo = "Elija uno de los modelos disponibles.";
    else if (!nivelesDe(p, f.modeloGemini).includes(f.razonamiento)) errores.razonamiento = "Elija un nivel que admita el modelo.";
  }
  if (!Number.isFinite(f.umbral) || f.umbral < 0 || f.umbral > 100) errores.umbral = "Debe estar entre 0 % y 100 %.";
  const tokens = entero(f.maxTokens);
  if (tokens === null || tokens < 1 || tokens > MAX_TOKENS) errores.max_tokens = "Escriba un número entero entre 1 y 64.000.";
  const reintentos = entero(f.maxRetries);
  if (reintentos === null || reintentos > MAX_REINTENTOS) errores.max_retries = `Escriba un número entero entre 0 y ${MAX_REINTENTOS}.`;
  return errores;
}

export function igual(a: Formulario, b: Formulario): boolean {
  return (
    a.proveedor === b.proveedor &&
    a.modelo === b.modelo &&
    a.effort === b.effort &&
    a.modeloGemini === b.modeloGemini &&
    a.razonamiento === b.razonamiento &&
    a.modo === b.modo &&
    a.umbral === b.umbral &&
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
