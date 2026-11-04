import type { CasoResumen, EstadoCasoApi } from "../../api/contrato";

export type Alertas = Record<string, string[]> | string[] | null | undefined;

export interface CitaEstado {
  id: string;
  sentencia_original: string;
  sentencia_norm?: string | null;
  estado: "ok" | "alerta" | "rechazada";
  motivos?: string[];
  cobertura?: number | null;
}

export interface MetadatosEstado {
  cui_1a?: string | null;
  cui_2a?: string | null;
  juzgado_a_quo?: string | null;
  accionante?: string | null;
}

export interface EstadoCaso {
  ok?: boolean;
  estado: Exclude<EstadoCasoApi, "corriendo">;
  salidas?: string[];
  resumen?: {
    citas?: CitaEstado[];
    alertas?: Alertas;
    metadatos?: MetadatosEstado | null;
  };
  error?: string | null;
  job_activo?: string | null;
}

export interface SalidasRespuesta {
  archivos: string[];
}

export interface CitaResumen {
  fuente: string;
  estado: "verificada" | "revisar" | "rechazada";
}

export interface Salida {
  ruta: string;
  archivo: string;
  nombre: string;
}

export interface GrupoSalidas {
  clave: string;
  titulo: string;
  salidas: Salida[];
}

export interface AvisoFallo {
  clave: string;
  texto: string;
  detalle?: string[];
}

export interface AvisosFallo {
  revise: AvisoFallo[];
  recuerde: AvisoFallo[];
  citasVerificadas: number;
}

export interface Destino {
  texto: string;
  enlace: string;
  href: string;
}

export type InfoCaso = Pick<CasoResumen, "nombre" | "radicado" | "juzgado_a_quo">;
