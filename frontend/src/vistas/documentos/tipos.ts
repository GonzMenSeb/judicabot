export const ROLES = [
  { id: "acta_reparto_1a", etiqueta: "Acta de reparto de primera instancia" },
  { id: "acta_reparto_2a", etiqueta: "Acta de reparto de la impugnación" },
  { id: "escrito_tutela", etiqueta: "Escrito de tutela" },
  { id: "auto_admisorio", etiqueta: "Auto admisorio" },
  { id: "auto_vinculacion", etiqueta: "Auto de vinculación" },
  { id: "contestacion", etiqueta: "Contestación" },
  { id: "fallo_a_quo", etiqueta: "Fallo de primera instancia" },
  { id: "impugnacion", etiqueta: "Impugnación" },
  { id: "auto_concede_impugnacion", etiqueta: "Auto que concede la impugnación" },
  { id: "notificacion", etiqueta: "Notificación" },
  { id: "correo", etiqueta: "Correo" },
  { id: "memorial", etiqueta: "Memorial" },
  { id: "indice", etiqueta: "Índice" },
  { id: "anexo", etiqueta: "Anexo" },
  { id: "producto_despacho", etiqueta: "Producto del despacho" },
  { id: "otro", etiqueta: "Otro" },
] as const;

export type RolDoc = (typeof ROLES)[number]["id"];

export const OBLIGATORIOS: readonly RolDoc[] = ["escrito_tutela", "fallo_a_quo", "impugnacion"];

export const etiquetaRol = (rol: string): string => ROLES.find((r) => r.id === rol)?.etiqueta ?? rol;

export interface DocResumen {
  doc_id: string;
  ruta: string;
  nombre: string;
  rol: RolDoc;
  rol_origen: "contenido" | "usuario" | "jev";
  evidencia: string;
  paginas: number;
  paginas_sin_texto: number;
  ruido: boolean;
  ajeno: boolean;
  revisar: boolean;
  jev_rol: string | null;
  jev_confianza: number | null;
  jev_umbral: number | null;
}

export interface DatosAuto {
  fecha: string | null;
  fecha_reparto: string | null;
  accionante: string | null;
  accionada: string | null;
  firmante: string | null;
  cargo_firmante: string | null;
}

export type ClaveAuto = keyof DatosAuto;

export interface ResumenIngesta {
  n_documentos: number;
  documentos: DocResumen[];
  faltantes: string[];
  esperados_faltantes: string[];
  alertas: string[];
  docs_ajenos: string[];
  docs_revisar: string[];
  auto: DatosAuto;
}

export type EstadoApi = "sin_iniciar" | "revision" | "incompleto" | "esperando_decision" | "terminado" | "error";

export interface EstadoCaso {
  ok: boolean;
  estado: EstadoApi;
  salidas: string[];
  resumen: Partial<ResumenIngesta> | null;
  error: string | null;
  job_activo?: string | null;
  ingesta?: ResumenIngesta;
}

export interface RevisionCuerpo {
  roles?: Record<string, string>;
  auto?: Partial<DatosAuto>;
}

export interface JobEstado {
  id: string;
  caso: string;
  cmd: "nuevo" | "iniciar" | "decidir" | "continuar";
  estado: "corriendo" | "terminado" | "error";
  error: string | null;
}

export interface ConfigCaso {
  llm?: { proveedor?: "anthropic" | "fake" };
}

export interface SalidaPrevia {
  ruta: string;
  titulo: string;
  archivo: string;
}

export const CLAVES_AUTO: readonly ClaveAuto[] = ["fecha_reparto", "fecha", "accionante", "accionada", "firmante", "cargo_firmante"];

export function ingestaDe(estado: EstadoCaso): ResumenIngesta | null {
  const fuente = estado.ingesta ?? estado.resumen;
  return fuente && Array.isArray(fuente.documentos) ? (fuente as ResumenIngesta) : null;
}

const PREVIAS: readonly [RegExp, string][] = [
  [/ActaRepartoSegunda/, "Acta de reparto de la impugnación"],
  [/AutoAsumeSegunda/, "Auto que asume el conocimiento"],
  [/requerimiento/, "Requerimiento de documentos faltantes"],
];

export function salidasPrevias(salidas: string[]): SalidaPrevia[] {
  const resultado: SalidaPrevia[] = [];
  for (const [patron, titulo] of PREVIAS) {
    const ruta = salidas.find((s) => patron.test(s));
    if (ruta) resultado.push({ ruta, titulo, archivo: ruta.split("/").pop() ?? ruta });
  }
  return resultado;
}

export const urlSalida = (caso: string, ruta: string): string =>
  `/api/casos/${encodeURIComponent(caso)}/salidas/${ruta.split("/").map(encodeURIComponent).join("/")}`;
