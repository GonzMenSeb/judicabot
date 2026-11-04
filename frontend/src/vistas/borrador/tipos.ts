import type { Bloque, EstadoCasoApi } from "../../api/contrato";

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

export interface ResumenEstado {
  metadatos?: MetadatosCaso | null;
  jev_metadatos?: JevMetadatos | null;
  alertas?: AlertasApi | null;
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

export interface ItemRevision {
  clave: string;
  tono: "alerta" | "mal";
  etiqueta: string;
  texto: string;
  detalle: string | null;
  cita: string | null;
}

export interface EntradaIndice {
  id: string;
  titulo: string;
  sub: boolean;
}

export type GrupoBloque =
  | { tipo: "bloque"; bloque: Bloque }
  | { tipo: "tabla" | "lista"; bloques: Bloque[] };

export interface CorreccionCuerpo {
  cmd: "decidir";
  decision: { accion: "rehacer_apertura" | "rehacer_consideraciones"; instruccion: string };
}
