import type { ApoderadoVista, Bloque, CitaVista, EstadoCasoApi, EvidenciaVista, ProveedorCaso } from "../../api/contrato";
import type { TonoChip } from "../../ui";

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
  /** La última decisión del caso (`accion`, `instruccion` y `fecha`); tras una corrección, `rehacer_*`. */
  decision?: { accion?: string; instruccion?: string; fecha?: string } | null;
}

export interface EstadoCaso {
  ok?: boolean;
  estado: EstadoCasoApi;
  resumen?: ResumenEstado | null;
  error?: string | null;
  job_activo?: string | null;
  proveedor_llm?: ProveedorCaso | null;
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
  | { tipo: "comparar"; lecturas: { etiqueta: string; valores: string[] }[] }
  | { tipo: "apoderado"; apoderado: ApoderadoVista };

export interface AlertaLegible {
  nivel: NivelRevision;
  origen: string;
  titulo: string;
  linea: string | null;
  lineaCompleta: boolean;
  detalle: DetalleRevision | null;
}

export type GrupoRevision = "citas" | "apoderados";

export type Pestana = GrupoRevision;

/** Lo que está marcado en el texto del borrador: una cita o el nombre de un abogado. */
export interface Seleccion {
  tipo: "cita" | "apoderado";
  id: string;
}

export interface ItemRevision extends AlertaLegible {
  clave: string;
  /** La marca del texto que corresponde a la fila, si la hay. */
  marca: Seleccion | null;
  grupo: GrupoRevision;
  /**
   * Un aviso corto que la fila cerrada muestra antes de su línea, como «Necesita su ayuda». Con `giro` es algo en
   * curso («Consultando vigencia en la Rama Judicial…»): va en su propio renglón, con el indicador de actividad.
   */
  etiqueta?: { texto: string; tono: TonoChip; giro?: boolean };
}

/** Una corrección a mano de un apoderado que pide un diálogo (M5): descartar el poder, señalarlo o escribir la cédula. */
export interface PedidoAjuste {
  tipo: "descartar" | "poder" | "cedula";
  apoderado: string;
}

/** Qué abrir en el visor de evidencia: la página citada de un documento del expediente. */
export interface PedidoVisor {
  apoderado: string;
  evidencia: EvidenciaVista;
  titulo: string;
  subtitulo: string;
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
  /** Cuántos de los `n` son nombres de abogados (el resto, citas); sin abogados no viene. */
  apoderados?: number;
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
