export type EstadoCasoApi =
  | "sin_iniciar"
  | "revision"
  | "incompleto"
  | "esperando_decision"
  | "terminado"
  | "error"
  | "corriendo";

export type ProcesoCaso = "segunda";

export type SentidoAQuo = "ampara" | "niega" | "improcedente" | "carencia_actual_de_objeto" | "otro";
export type ImpugnanteCaso = "accionante" | "accionada" | "vinculada" | "otro" | "varios";
export type ResultadoCaso = "CONFIRMAR" | "REVOCAR" | "MODIFICAR";
export type SustitutivaCaso =
  | "AMPARAR"
  | "NEGAR"
  | "IMPROCEDENTE"
  | "CARENCIA_HECHO_SUPERADO"
  | "CARENCIA_DANO_CONSUMADO"
  | "CARENCIA_SOBREVINIENTE";

/**
 * Datos propios de la segunda instancia para filtrar la lista. Todos pueden faltar (null, o [] en derechos).
 * resultado y sustitutiva solo vienen si ya hay una decisión "decidir"; n_citas_revisar y jev_discrepa, solo
 * mientras el caso espera la decisión.
 */
export interface DatosSegunda {
  decision_a_quo: SentidoAQuo | null;
  impugnante: ImpugnanteCaso | null;
  resultado: ResultadoCaso | null;
  sustitutiva: SustitutivaCaso | null;
  derechos: string[];
  pruebas_nuevas: boolean | null;
  n_citas_revisar: number | null;
  jev_discrepa: boolean | null;
}

export type UnidadTermino = "habiles" | "calendario";

/**
 * Término para fallar: el despacho recibió el expediente el día `inicio` (AAAA-MM-DD, "Recibido el") y cuenta con `dias`
 * (1 a 365) desde el día siguiente, en días hábiles (sin fines de semana ni festivos) o calendario (si vence en un día no
 * hábil, pasa al siguiente hábil).
 */
export interface Termino {
  inicio: string;
  dias: number;
  unidad: UnidadTermino;
}

/**
 * GET y PUT /api/casos/{id}/termino. termino es el guardado o, mientras no se guarde (por_defecto), el propuesto desde
 * fecha_reparto: 20 días hábiles. Sin fecha de reparto ni término guardado no hay término. vence y dias_restantes
 * (ver CasoResumen) son null si no hay término o el caso terminó.
 */
export interface TerminoRespuesta {
  termino: Termino | null;
  por_defecto: boolean;
  fecha_reparto: string | null;
  vence: string | null;
  dias_restantes: number | null;
}

export interface CasoResumen {
  id: string;
  nombre: string;
  proceso: ProcesoCaso;
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
  /** null solo si el estado del caso no se pudo leer. */
  segunda: DatosSegunda | null;
  /** Instante de creación del caso (ISO 8601 con desfase); null en los casos anteriores a este dato. */
  creado: string | null;
  /** Término efectivo: el guardado o el propuesto desde la fecha de reparto; null si no hay ninguno. */
  termino: Termino | null;
  /** Día de vencimiento (AAAA-MM-DD), calculado por el servidor al día; null si no hay término o el caso terminó. */
  vence: string | null;
  /**
   * 0 el día del vencimiento, positivo antes (días que faltan, en la unidad del término: hábiles después de hoy hasta
   * vence, o corridos) y negativo después (atraso). null cuando vence es null.
   */
  dias_restantes: number | null;
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
  url?: string | null;
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
  advertencias: { campo: string; mensaje: string }[];
  encabezado: string;
  fecha_fallo: string;
  fecha_por_defecto: boolean;
}

export type ModoJev = "apagado" | "sombra" | "relleno";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";
export type Proveedor = "anthropic" | "gemini";
export type ProveedorCaso = Proveedor | "fake";
export type RazonamientoGemini = "low" | "medium" | "high" | "xhigh";

export interface PreferenciasGemini {
  modelo: string;
  razonamiento: RazonamientoGemini;
}

export interface PreferenciasIa {
  proveedor: Proveedor;
  modelo: string;
  modelos: string[];
  gemini: PreferenciasGemini;
  modelos_gemini: string[];
  razonamientos_gemini: Record<string, RazonamientoGemini[]>;
  api_key: boolean;
  gemini_key: boolean;
  jev_key: boolean;
  jev: { modo: ModoJev; umbral: number };
  effort: Effort;
  max_tokens: number;
  max_retries: number;
}

export interface PreferenciasIaCuerpo {
  proveedor?: Proveedor;
  modelo?: string;
  effort?: Effort;
  gemini?: PreferenciasGemini;
  jev: { modo: ModoJev; umbral: number };
  max_tokens: number;
  max_retries: number;
}

export interface EstadoServidor {
  proveedor: Proveedor;
  api_key: boolean;
  gemini_key: boolean;
  jev_key: boolean;
  modelo: string;
  modelos: string[];
  modelos_gemini: string[];
  /** Festivos (AAAA-MM-DD) del año anterior, el actual y el siguiente, en orden. */
  festivos: string[];
}

export interface EstadoDataset {
  vigente: boolean;
  url: string;
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
