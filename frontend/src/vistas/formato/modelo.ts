import type { CampoFormato, Despacho, FormatoCuerpo } from "../../api/contrato";

export type Plantilla = "A" | "B";

export interface Seccion {
  grupo: string;
  campos: CampoFormato[];
}

export interface EstadoFormato {
  valores: Despacho;
  plantilla: Plantilla;
}

export interface ErroresFormato {
  porCampo: Record<string, string>;
  generales: string[];
}

export const SIN_ERRORES: ErroresFormato = { porCampo: {}, generales: [] };

const registro = (valores: Despacho) => valores as unknown as Record<string, unknown>;

export function texto(valores: Despacho, clave: string): string {
  const valor = registro(valores)[clave];
  if (Array.isArray(valor)) return valor.join("\n");
  return typeof valor === "string" ? valor : "";
}

export function lineas(valores: Despacho, clave: string): string[] {
  const valor = registro(valores)[clave];
  if (Array.isArray(valor)) return valor.map(String);
  return typeof valor === "string" && valor ? [valor] : [];
}

export function con(valores: Despacho, clave: string, valor: string | string[]): Despacho {
  return { ...valores, [clave]: valor };
}

export function agrupar(campos: readonly CampoFormato[]): Seccion[] {
  const secciones: Seccion[] = [];
  for (const campo of campos) {
    const existente = secciones.find((s) => s.grupo === campo.grupo);
    if (existente) existente.campos.push(campo);
    else secciones.push({ grupo: campo.grupo, campos: [campo] });
  }
  return secciones;
}

export const esSucio = (actual: EstadoFormato, guardado: EstadoFormato): boolean =>
  actual.plantilla !== guardado.plantilla || JSON.stringify(actual.valores) !== JSON.stringify(guardado.valores);

export function cuerpoParaGuardar(actual: EstadoFormato, campos: readonly CampoFormato[]): FormatoCuerpo {
  let valores = actual.valores;
  for (const campo of campos) {
    if (campo.tipo === "lista") valores = con(valores, campo.clave, lineas(valores, campo.clave).filter((l) => l.trim() !== ""));
  }
  return { valores, plantilla_gen: actual.plantilla };
}

const mayuscula = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export function leerErrores(detalle: unknown, campos: readonly CampoFormato[]): ErroresFormato | null {
  if (typeof detalle !== "object" || detalle === null || !("errores" in detalle) || !Array.isArray(detalle.errores)) return null;
  const claves = new Set(campos.map((c) => c.clave));
  const porCampo: Record<string, string> = {};
  const generales: string[] = [];
  for (const e of detalle.errores as unknown[]) {
    if (typeof e !== "object" || e === null) continue;
    const campo = "campo" in e && typeof e.campo === "string" ? e.campo : "";
    const mensaje = mayuscula("mensaje" in e && typeof e.mensaje === "string" ? e.mensaje : "Valor no válido.");
    const clave = campo.split(".")[0] ?? "";
    if (claves.has(clave)) porCampo[clave] = porCampo[clave] ? `${porCampo[clave]} ${mensaje}` : mensaje;
    else generales.push(campo ? `${campo}: ${mensaje}` : mensaje);
  }
  return { porCampo, generales };
}

let contador = 0;
export const nuevaClave = (): number => ++contador;

const CORTOS: Record<string, string> = {
  fallo: "Fallo",
  auto: "Auto",
  oficio: "Oficio",
  correos: "Correos",
  formato: "Formato de calidad",
};

export const nombreCorto = (id: string, documentos: readonly { id: string; nombre: string }[]): string =>
  CORTOS[id] ?? documentos.find((d) => d.id === id)?.nombre ?? id;
