export type Resultado = "CONFIRMAR" | "REVOCAR" | "MODIFICAR";
export type SustitutivaApi =
  | "AMPARAR"
  | "NEGAR"
  | "IMPROCEDENTE"
  | "CARENCIA_HECHO_SUPERADO"
  | "CARENCIA_DANO_CONSUMADO"
  | "CARENCIA_SOBREVINIENTE";
export type SustitutivaForm = SustitutivaApi | "CARENCIA" | "";
export type DisposicionReparo = "ACOGE" | "DESESTIMA" | "ACOGE_PARCIAL" | "REFORMULA" | "ABSORBIDO";
export type DisposicionDerecho = "AMPARA" | "NIEGA" | "SIN_PRONUNCIAMIENTO";
export type Causal = "COSA_JUZGADA" | "SUBSIDIARIEDAD";
export type Verbo = "ORDENAR" | "PREVENIR" | "ADVERTIR";
export type Unidad = "horas_habiles" | "dias_habiles" | "horas" | "dias";

export interface ReparoPayload {
  id: string;
  sintesis?: string | null;
}

export interface PayloadDecision {
  reparos?: ReparoPayload[];
  decision_a_quo?: string | null;
  impugnante?: string | null;
  impugnante_rol?: string | null;
  impugnantes?: string[];
  derechos_invocados?: string[];
  pruebas_nuevas_2a?: string[];
  fecha_hoy?: string;
  errores?: string[];
}

export interface RespuestaEstado {
  ok: boolean;
  estado: string;
  payload: PayloadDecision | null;
  error: string | null;
}

export interface ConfigCaso {
  despacho?: { juez?: string; cierre_fallo?: string };
  llm?: { proveedor?: string };
}

export interface OrdenForm {
  id: number;
  verbo: Verbo;
  destinatario: string;
  conducta: string;
  n: string;
  unidad: Unidad;
  via: boolean;
  condicion: string;
  mismo: boolean;
}

export interface LibreForm {
  id: number;
  texto: string;
}

export interface DerechoForm {
  id: number;
  nombre: string;
  disposicion: DisposicionDerecho;
  propio: boolean;
}

export interface ReparoForm {
  id: string;
  disposicion: DisposicionReparo;
  nota: string;
}

export interface Formulario {
  resultado: Resultado | "";
  sustitutiva: SustitutivaForm;
  causal: Causal | "";
  eje: string;
  decididoPor: string;
  reparos: ReparoForm[];
  derechos: DerechoForm[];
  ordenes: OrdenForm[];
  desvincular: string;
  prevenir: string;
  compulsa: boolean;
  organo: string;
  respectoDe: string;
  hechosRef: string;
  notificar: boolean;
  remitir: boolean;
  generarFormato: boolean;
  fechaFallo: string;
  fechaOficio: string;
  etiqueta: string;
  libres: LibreForm[];
  orden: string[];
  reordenado: boolean;
  siguienteId: number;
}

export interface OrdenCuerpo {
  mismo_termino: boolean;
  verbo: Verbo;
  destinatario: string;
  via_representante: boolean;
  conducta: string;
  plazo: { n: number; unidad: Unidad };
  condicion: string;
}

export interface DecisionCuerpo {
  accion: "decidir";
  resultado: Resultado | null;
  sustitutiva: SustitutivaApi | null;
  causal: Causal | null;
  eje: string;
  por_reparo: { reparo_id: string; disposicion: DisposicionReparo; nota: string }[];
  derechos: { derecho: string; disposicion: DisposicionDerecho }[];
  ordenes: OrdenCuerpo[];
  desvincular: string[];
  prevenir: string[];
  compulsa: { respecto_de: string; hechos_ref: string; organo?: string } | null;
  numerales: { notificar: boolean; remitir_corte: boolean };
  decidido_por: string;
  generar_formato: boolean;
  fecha_fallo: string | null;
  fecha_oficio: string | null;
  etiqueta_encabezado: string;
  numerales_libres: string[];
  orden_numerales: string[];
}

export interface Hallazgo {
  campo: string;
  mensaje: string;
}
