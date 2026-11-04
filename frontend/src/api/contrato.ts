export type EstadoCasoApi =
  | "sin_iniciar"
  | "revision"
  | "incompleto"
  | "esperando_decision"
  | "terminado"
  | "error"
  | "corriendo";

export interface CasoResumen {
  id: string;
  nombre: string;
  radicado: string | null;
  accionante: string | null;
  accionadas: string[];
  juzgado_a_quo: string | null;
  estado: EstadoCasoApi;
  etapa: 0 | 1 | 2 | 3 | 4;
  siguiente_paso: string;
  n_insumos: number;
  n_alertas: number;
  job_activo: string | null;
  actualizado: string;
}

export interface CrearCasoRespuesta {
  id: string;
  n_insumos: number;
}

export type TipoCampo = "texto" | "texto_largo" | "lista";

export interface CampoFormato {
  clave: string;
  etiqueta: string;
  ayuda: string;
  tipo: TipoCampo;
  grupo: string;
  documentos: string[];
}

export interface Despacho {
  nombre: string;
  nombre_corto: string;
  nombre_cuerpo: string;
  ciudad: string;
  juez: string;
  cargo_juez: string;
  escribiente: string;
  cargo_escribiente: string;
  firmante_oficio: string;
  cargo_firmante_oficio: string;
  cargo_evaluador: string;
  pie: string;
  correo: string;
  telefono_correo: string;
  cierre_fallo: string;
  cierre_auto: string;
  pie_fallo: string[];
  pie_auto: string[];
  firma_correo: string[];
}

export interface FormatoRespuesta {
  campos: CampoFormato[];
  valores: Despacho;
  plantilla_gen: "A" | "B";
  documentos: { id: string; nombre: string }[];
}

export interface FormatoCuerpo {
  valores: Despacho;
  plantilla_gen: "A" | "B";
}

export type EtapaEvento =
  | "ingesta"
  | "apertura"
  | "consideraciones"
  | "verificacion"
  | "caso_concreto"
  | "documentos"
  | "sistema";
export type TipoEvento = "lee" | "razona" | "escribe" | "verifica" | "sistema" | "error";

export interface Evento {
  n: number;
  t: string;
  etapa: EtapaEvento;
  tipo: TipoEvento;
  texto: string;
  datos: Record<string, unknown> | null;
}

export interface FinJob {
  estado: "terminado" | "error";
  error: string | null;
}

export interface EventosJson {
  eventos: Evento[];
  estado: "corriendo" | "terminado" | "error";
  error: string | null;
}

export interface Segmento {
  texto: string;
  negrita?: boolean;
  cursiva?: boolean;
  cita_id?: string;
}

export type TipoBloque =
  | "titulo"
  | "encabezado"
  | "parrafo"
  | "cita_bloque"
  | "lista"
  | "tabla"
  | "firma"
  | "pie"
  | "resuelve_numeral";

export interface Bloque {
  id: string;
  tipo: TipoBloque;
  origen: "plantilla" | "modelo";
  seccion: string | null;
  segmentos: Segmento[];
}

export interface PaginaVista {
  bloques: Bloque[];
}

export interface CitaVista {
  id: string;
  texto: string;
  fuente: string;
  cobertura: number | null;
  estado: "verificada" | "revisar" | "rechazada";
  detalle: string | null;
}

export interface Vista {
  tipo: "borrador" | "fallo";
  sha256: string;
  paginas: PaginaVista[];
  citas: CitaVista[];
  indice: { id: string; titulo: string }[];
}

export interface NumeralVista {
  clave: string;
  texto: string;
  negritas: string[];
}

export interface DecisionVistaRespuesta {
  numerales: NumeralVista[];
  faltantes: { campo: string; mensaje: string }[];
  errores: string[];
}

export type ModoJev = "apagado" | "sombra" | "relleno";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";

export interface PreferenciasIa {
  modelo: string;
  modelos: string[];
  api_key: boolean;
  jev_key: boolean;
  jev: { modo: ModoJev; umbral: number };
  effort: Effort;
  max_tokens: number;
  max_retries: number;
}

export interface PreferenciasIaCuerpo {
  modelo: string;
  jev: { modo: ModoJev; umbral: number };
  effort: Effort;
  max_tokens: number;
  max_retries: number;
}

export interface EstadoServidor {
  api_key: boolean;
  jev_key: boolean;
  modelo: string;
  modelos: string[];
}

export interface RunCuerpo {
  cmd: "nuevo" | "iniciar" | "decidir" | "continuar";
  decision?: Record<string, unknown>;
  forzar?: boolean;
}

export interface JobInicio {
  job_id: string;
}

export interface ErroresCampo {
  errores: { campo: string; mensaje: string }[];
}
