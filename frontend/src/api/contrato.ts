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
  /** Nombre de un abogado en el borrador previo; el estado se lee de `/apoderados`, no viene en la vista. */
  apoderado_id?: string;
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

export type RolDocumento =
  | "acta_reparto_1a"
  | "acta_reparto_2a"
  | "escrito_tutela"
  | "auto_admisorio"
  | "auto_vinculacion"
  | "contestacion"
  | "fallo_a_quo"
  | "impugnacion"
  | "auto_concede_impugnacion"
  | "notificacion"
  | "correo"
  | "memorial"
  | "indice"
  | "anexo"
  | "producto_despacho"
  | "otro";

export type RolParte = "accionante" | "accionada" | "vinculada" | "otro";
export type EstadoApoderado = "verificado" | "revisar" | "no_verificado";
export type FaseApoderado = "en_cola" | "consultando" | "necesita_ayuda" | "listo";
export type EstadoVigencia =
  | "vigente"
  | "vigente_obs"
  | "no_vigente"
  | "no_inscrito"
  | "otra_persona"
  | "ilegible"
  | "inaccesible"
  | "sin_cedula"
  | "sin_consultar";
export type EstadoPoder = "hallado" | "hallado_reserva" | "manual" | "sin_poder" | "ajeno" | "descartado";
export type EstadoCadena = "confirmada" | "contradicha" | "sin_certificado" | "no_aplica";
export type TipoPoder = "poder" | "sustitucion" | "certificado_existencia";
export type OrigenVigencia = "extension" | "directa" | "manual" | "fake";
export type EstadoExtension = "conectada" | "desactualizada" | "no_conectada";
export type ModoConsulta = "extension" | "directa" | "fake" | "apagada";

export interface Cotejo {
  ok: boolean | null;
  texto: string;
}

export interface EvidenciaVista {
  doc_id: string;
  documento: string;
  rol: RolDocumento | null;
  pagina: number;
  total_paginas: number | null;
  cita: string;
  ocr: boolean;
  inicio: number | null;
  fin: number | null;
}

export interface CadenaVista {
  estado: EstadoCadena;
  otorgante: string;
  cargo: string;
  evidencia: EvidenciaVista | null;
}

export interface VigenciaVista {
  estado: EstadoVigencia;
  fase: FaseApoderado;
  cedula: string | null;
  tarjeta_registro: string | null;
  consultado_en: string | null;
  origen: OrigenVigencia | null;
  certificado_url: string | null;
  numero_certificado: string | null;
  codigo_verificacion: string | null;
  detalle: string;
  /** La vigencia por sí sola deja al abogado sin verificar (en rojo): tarjeta no vigente, o cédula no inscrita que consta en
   * una página del expediente leída sin OCR. Una cédula no inscrita que pudo leerse o escribirse mal no lo es, aunque el
   * abogado quede sin verificar por otra razón (un poder de otra parte). */
  grave: boolean;
}

export interface PoderVista {
  estado: EstadoPoder;
  tipo: TipoPoder | null;
  evidencia: EvidenciaVista | null;
  otorgante: string;
  parte: string;
  cadena: CadenaVista | null;
  mencion: EvidenciaVista | null;
  documentos_revisados: number;
  /** El código halló un poder del abogado (aunque se muestre otro o se haya descartado): «Deshacer el descarte» vuelve a él. */
  hay_hallado: boolean;
}

export interface ApoderadoVista {
  id: string;
  nombre: string;
  parte: string;
  rol_parte: RolParte;
  tipo_persona: "natural" | "juridica";
  estado: EstadoApoderado;
  fase: FaseApoderado;
  motivos: string[];
  cedula: string | null;
  tarjeta: string | null;
  vigencia: VigenciaVista;
  poder: PoderVista;
  cotejos: Cotejo[];
  revisado: boolean;
  revision_vencida: boolean;
  bloquea: boolean;
  huella: string;
}

export interface ParteSinApoderadoVista {
  nombre: string;
  rol_parte: RolParte;
  nota: string;
}

export interface ConsultaEstado {
  activa: boolean;
  extension: EstadoExtension;
  modo: ModoConsulta;
  pausa_hasta: string | null;
}

export interface ApoderadosRespuesta {
  identificacion: "lista" | "no_disponible" | "fallida";
  apoderados: ApoderadoVista[];
  sin_apoderado: ParteSinApoderadoVista[];
  alertas: string[];
  consulta: ConsultaEstado;
  bloquea_decision: boolean;
  editable: boolean;
}

export interface RevisionCuerpo {
  revisado: boolean;
  nota?: string;
  /** La `huella` del apoderado que vio quien revisa; obligatoria para marcar como revisado (409 si el estado cambió). */
  huella?: string | null;
}

export interface ConsultarCuerpo {
  /** Apoderados cuya vigencia se consulta; sin ids, todos los del caso. */
  ids?: string[] | null;
  /** «Reintentar consulta automática»: consulta de nuevo aunque haya resultado, caché o se agotaran los intentos del día. */
  forzar?: boolean;
}

export interface PoderManualCuerpo {
  doc_id: string;
  pagina: number;
}

/** Correcciones a mano de un apoderado: un campo que no viene no cambia; uno en `null` quita esa corrección. */
export interface AjusteCuerpo {
  poder_manual?: PoderManualCuerpo | null;
  poder_descartado?: boolean | null;
  cedula?: string | null;
  nota?: string;
}

export interface PaginaExpediente {
  doc_id: string;
  documento: string;
  rol: RolDocumento;
  pagina: number;
  total: number;
  texto: string;
  ocr: boolean;
  es_pdf: boolean;
}
