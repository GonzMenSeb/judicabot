import type { Bloque, CitaVista, EstadoCasoApi } from "../../api/contrato";

export type PreguntaJev = "sentido_fallo" | "sentido_clausula" | "rol_impugnante";

export interface LecturaJev {
  choice: string;
  confidence: number;
}

export interface JevMetadatos {
  modelo?: string;
  umbral?: number;
  preguntas?: Partial<Record<PreguntaJev, LecturaJev>>;
  coincide?: { sentido?: boolean | null; rol_impugnante?: boolean | null };
}

export interface MetadatosCaso {
  cui_1a?: string | null;
  cui_2a?: string | null;
  juzgado_a_quo?: string | null;
  accionante?: string | null;
  accionadas?: string[];
  impugnante?: string | null;
  impugnante_rol?: string | null;
  decision_a_quo?: string | null;
}

export type AlertasApi = Record<string, string[]> | string[];

export interface LlamadaBitacora {
  nodo: string;
  intento?: number;
  proveedor?: string;
  modelo_pedido?: string;
  modelo_efectivo?: string | null;
}

export interface Redaccion {
  nodo: string;
  secciones: string;
  modelo: string;
  pedido: string | null;
}

export interface ResumenEstado {
  metadatos?: MetadatosCaso | null;
  jev_metadatos?: JevMetadatos | null;
  alertas?: AlertasApi | null;
  bitacora?: LlamadaBitacora[] | null;
}

export interface EstadoCaso {
  ok?: boolean;
  estado: EstadoCasoApi;
  resumen?: ResumenEstado | null;
  error?: string | null;
  job_activo?: string | null;
}

export type EstadoComparacion = "coincide" | "difiere" | "sin_comparar";

export interface FilaJev {
  id: string;
  etiqueta: string;
  borrador: { principal: string | null; secundario: string | null };
  jev: { principal: string | null; confianza: number | null; nota: string | null };
  estado: EstadoComparacion;
  motivo: string | null;
}

export type NivelRevision = "mal" | "alerta" | "info" | "ok";

export type DetalleRevision =
  | { tipo: "cita"; cita: CitaVista; motivos: string[] }
  | { tipo: "jev"; fila: FilaJev }
  | { tipo: "archivo"; archivo: string; nota: string }
  | { tipo: "comparar"; lecturas: { etiqueta: string; valores: string[] }[] };

export interface AlertaLegible {
  nivel: NivelRevision;
  origen: string;
  titulo: string;
  linea: string | null;
  lineaCompleta: boolean;
  detalle: DetalleRevision | null;
}

export interface ItemRevision extends AlertaLegible {
  clave: string;
  cita: string | null;
}

export interface EntradaIndice {
  id: string;
  titulo: string;
  sub: boolean;
  anexo: boolean;
}

export interface MarcaIndice {
  n: number;
  mal: boolean;
}

export type GrupoBloque =
  | { tipo: "bloque"; bloque: Bloque }
  | { tipo: "tabla" | "lista"; bloques: Bloque[] };

export interface UnidadEdicion {
  clave: string;
  pieza: string;
  parrafo: number;
  ids: string[];
}

export interface CorreccionCuerpo {
  cmd: "decidir";
  decision: { accion: "rehacer_apertura" | "rehacer_consideraciones"; instruccion: string };
}
