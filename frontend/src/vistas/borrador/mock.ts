import { ErrorApi } from "../../api/cliente";
import type {
  AjusteCuerpo,
  ApoderadosRespuesta,
  ApoderadoVista,
  Bloque,
  CitaVista,
  ConsultarCuerpo,
  EvidenciaVista,
  PaginaExpediente,
  RevisionCuerpo,
  Segmento,
  TipoBloque,
  Vista,
} from "../../api/contrato";
import type { MockRuta, PeticionMock } from "../../api/mock";
import { conRevision, partirResaltado } from "./apoderados";
import type { EstadoCaso } from "./tipos";

export const CASO_MOCK_BORRADOR = "borrador-quintero";

type Origen = Bloque["origen"];

const t = (texto: string, extra: Partial<Segmento> = {}): Segmento => ({ texto, ...extra });
const c = (texto: string, cita_id: string): Segmento => ({ texto, cita_id });
const a = (texto: string, apoderado_id: string): Segmento => ({ texto, apoderado_id });

const ID_VERIFICADA = "ap-3f9c2a71d0";
const ID_POR_REVISAR = "ap-81be04c5f2";
const ID_NO_VERIFICADO = "ap-c47d19e6a8";

function bloque(id: string, tipo: TipoBloque, origen: Origen, seccion: string | null, ...segmentos: (Segmento | string)[]): Bloque {
  return { id, tipo, origen, seccion, segmentos: segmentos.map((s) => (typeof s === "string" ? t(s) : s)) };
}

const PIE = [
  "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
  "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
  "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
];
const pie = (n: number): Bloque[] => PIE.map((texto, k) => bloque(`pie-${n}-${k + 1}`, "pie", "plantilla", null, texto));

const citas: CitaVista[] = [
  {
    id: "c1",
    texto: "la salud tiene doble connotación: derecho fundamental y servicio público esencial",
    fuente: "sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa",
    cobertura: 0.98,
    estado: "verificada",
    detalle: null,
    url: "https://www.corteconstitucional.gov.co/relatoria/2008/T-760-08.htm",
  },
  {
    id: "c2",
    texto: "la garantía de continuidad de los tratamientos en curso hace parte del núcleo esencial",
    fuente: "sentencia SU-508 de 2020",
    cobertura: 0.71,
    estado: "revisar",
    detalle: "La cobertura del fragmento citado es 71 %. Compare con la relatoría antes de firmar.",
  },
  {
    id: "c3",
    texto: "la EPS no puede suspender el servicio por trámites internos",
    fuente: "sentencia T-999 de 2019",
    cobertura: 0,
    estado: "rechazada",
    detalle: "No aparece en el dataset de la Corte Constitucional.; Quite la cita o reemplácela por una verificable.",
  },
];

const pagina1: Bloque[] = [
  bloque("encabezado-1", "encabezado", "plantilla", null, t("JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO DE MEDELLÍN", { negrita: true })),
  bloque("encabezado-2", "tabla", "plantilla", null, t("Radicado", { negrita: true }), t("05001 40 88 009 2026 00412 01")),
  bloque("encabezado-3", "tabla", "plantilla", null, t("Accionante", { negrita: true }), t("MARTA INÉS QUINTERO BEDOYA")),
  bloque("encabezado-4", "tabla", "plantilla", null, t("Accionada", { negrita: true }), t("EPS HORIZONTE SALUD S.A.S.")),
  bloque("encabezado-5", "tabla", "plantilla", null, t("Procedencia", { negrita: true }), t("JUZGADO 9 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN")),
  bloque("encabezado-6", "tabla", "plantilla", null, t("Derechos", { negrita: true }), t("SALUD, MÍNIMO VITAL")),
  bloque("encabezado-7", "encabezado", "plantilla", null, t("BORRADOR PREVIO A LA DECISIÓN (SECCIONES I A V)", { negrita: true })),
  bloque("asunto", "titulo", "plantilla", "asunto", t("I.\tASUNTO", { negrita: true })),
  bloque(
    "asunto-1",
    "parrafo",
    "plantilla",
    "asunto",
    "Procede el Despacho a resolver la impugnación presentada por la accionante contra el fallo de tutela emitido el veintiocho (28) de septiembre de dos mil veintiséis (2026) por el Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín, por medio del cual se declaró improcedente la acción de tutela.",
  ),
  bloque("antecedentes-del-caso", "titulo", "plantilla", "antecedentes-del-caso", t("II.\tANTECEDENTES DEL CASO", { negrita: true })),
  bloque(
    "antecedentes-del-caso-1",
    "parrafo",
    "modelo",
    "antecedentes-del-caso",
    "La señora MARTA INÉS QUINTERO BEDOYA, identificada con cédula de ciudadanía 43.999.101, por medio de apoderado judicial, el doctor ",
    a("Luis Fernando Ospina Arango", ID_POR_REVISAR),
    ", presentó acción de tutela el catorce (14) de septiembre de dos mil veintiséis (2026) contra la EPS HORIZONTE SALUD S.A.S., entidad a la que se encuentra afiliada en el régimen contributivo, por considerar vulnerados sus derechos fundamentales a la salud y al mínimo vital.",
  ),
  bloque(
    "antecedentes-del-caso-2",
    "parrafo",
    "modelo",
    "antecedentes-del-caso",
    "Relató que padece una enfermedad crónica por la cual su médico tratante le prescribió un medicamento de uso continuo, que la entidad le suministró hasta agosto de dos mil veintiséis (2026), cuando dejó de entregárselo sin una razón que le fuera comunicada por escrito. Agregó que no cuenta con recursos para comprarlo por su cuenta y que de ella dependen económicamente sus hijos menores de edad.",
  ),
  bloque(
    "antecedentes-del-caso-3",
    "parrafo",
    "modelo",
    "antecedentes-del-caso",
    "Con fundamento en lo anterior, solicitó que se ordenara a la entidad suministrar el medicamento prescrito, de manera continua y sin dilaciones, y que se le brindara el tratamiento integral que su patología requiera. Adjuntó la fórmula médica vigente y la copia de su historia clínica.",
  ),
  bloque(
    "antecedentes-del-caso-4",
    "parrafo",
    "modelo",
    "antecedentes-del-caso",
    "El Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín admitió la acción el quince (15) de septiembre de dos mil veintiséis (2026) y ordenó notificar a la accionada. La EPS HORIZONTE SALUD S.A.S. contestó el diecisiete (17) de septiembre siguiente por intermedio de su apoderada judicial, la doctora ",
    a("Andrea Paola Giraldo Montoya", ID_VERIFICADA),
    "; manifestó que el medicamento no figuraba autorizado para la afiliada y que esta podía acudir a la Superintendencia Nacional de Salud, por lo que solicitó negar el amparo. La CLÍNICA SANTA AURORA S.A.S., vinculada al trámite, intervino por medio del doctor ",
    a("Carlos Eduardo Pineda Ruiz", ID_NO_VERIFICADO),
    ", quien solicitó su desvinculación por falta de legitimación en la causa por pasiva.",
  ),
];

const pagina2: Bloque[] = [
  bloque("la-sentencia-impugnada", "titulo", "plantilla", "la-sentencia-impugnada", t("III.\tLA SENTENCIA IMPUGNADA", { negrita: true })),
  bloque(
    "la-sentencia-impugnada-1",
    "parrafo",
    "modelo",
    "la-sentencia-impugnada",
    "Mediante sentencia del veintiocho (28) de septiembre de dos mil veintiséis (2026), el Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín declaró improcedente la acción de tutela.",
  ),
  bloque(
    "la-sentencia-impugnada-2",
    "parrafo",
    "modelo",
    "la-sentencia-impugnada",
    "Para sustentar su decisión, el juez de primera instancia consideró que no se cumplía el requisito de subsidiariedad, pues la accionante disponía de un mecanismo ante la Superintendencia Nacional de Salud, que ejerce funciones jurisdiccionales para resolver controversias entre los afiliados y las entidades promotoras de salud. Añadió que no encontró acreditado un perjuicio irremediable que habilitara el estudio de fondo.",
  ),
  bloque("la-impugnacion", "titulo", "plantilla", "la-impugnacion", t("IV.\tLA IMPUGNACIÓN", { negrita: true })),
  bloque(
    "la-impugnacion-1",
    "parrafo",
    "modelo",
    "la-impugnacion",
    "En relación con el reparo R1, la impugnante señala que «la orden médica vigente que prescribe el medicamento y que anexé al escrito de tutela no fue valorada por el juez».",
  ),
  bloque(
    "la-impugnacion-2",
    "parrafo",
    "modelo",
    "la-impugnacion",
    "En relación con el reparo R2, la impugnante señala que «la salud es un derecho fundamental y no puedo esperar el trámite ante la Superintendencia teniendo una enfermedad crónica».",
  ),
  bloque("consideraciones", "titulo", "plantilla", "consideraciones", t("V.\tCONSIDERACIONES", { negrita: true })),
  bloque("consideraciones-1", "encabezado", "plantilla", "consideraciones", t("Competencia", { negrita: true })),
  bloque(
    "consideraciones-2",
    "parrafo",
    "plantilla",
    "consideraciones",
    "Este Despacho es competente para conocer y resolver el recurso de impugnación interpuesto contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de amparo. En su condición de superior funcional, le corresponde adelantar un examen integral de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina fijada por la Corte Constitucional.",
  ),
  bloque("consideraciones-3", "encabezado", "plantilla", "consideraciones", t("Presupuestos generales de procedibilidad de la acción de tutela", { negrita: true })),
  bloque(
    "consideraciones-4",
    "parrafo",
    "plantilla",
    "consideraciones",
    "La acción de tutela, consagrada en el artículo 86 de la Constitución Política y reglamentada por el Decreto 2591 de 1991, se erige como un mecanismo preferente y sumario concebido para la protección inmediata y efectiva de los derechos constitucionales fundamentales cuando estos resulten vulnerados o amenazados por la acción u omisión de las autoridades públicas o de los particulares.",
  ),
  bloque("consideraciones-5", "encabezado", "modelo", "consideraciones", t("La salud y la continuidad del tratamiento", { negrita: true })),
  bloque(
    "consideraciones-6",
    "parrafo",
    "modelo",
    "consideraciones",
    "La Corte Constitucional ha reiterado que la salud tiene una doble connotación, como derecho fundamental y como servicio público esencial (",
    c("sentencia T-760 de 2008", "c1"),
    "). En esa medida, el Estado y las entidades que prestan el servicio están obligados a garantizarlo conforme a los principios de eficiencia, universalidad y solidaridad.",
  ),
];

const pagina3: Bloque[] = [
  bloque(
    "consideraciones-7",
    "parrafo",
    "modelo",
    "consideraciones",
    "De la mano de lo anterior, la jurisprudencia ha precisado que la continuidad de los tratamientos en curso hace parte del núcleo esencial del derecho (",
    c("sentencia SU-508 de 2020", "c2"),
    "). Al respecto, el alto tribunal señaló:",
  ),
  bloque(
    "consideraciones-8",
    "cita_bloque",
    "modelo",
    "consideraciones",
    t("“una vez iniciado un tratamiento, su interrupción por razones administrativas desconoce el principio de continuidad, pues el paciente no puede asumir las consecuencias de las barreras internas de la entidad”", {
      cursiva: true,
    }),
  ),
  bloque("consideraciones-9", "encabezado", "modelo", "consideraciones", t("La subsidiariedad y la vía ante la Superintendencia Nacional de Salud", { negrita: true })),
  bloque(
    "consideraciones-10",
    "parrafo",
    "modelo",
    "consideraciones",
    "El requisito de subsidiariedad exige verificar si el afectado dispone de otro mecanismo de defensa judicial idóneo y eficaz. La Corte ha sostenido que, en materia de salud, el mecanismo ante la Superintendencia Nacional de Salud no desplaza al juez de tutela cuando no resulta eficaz frente a las circunstancias particulares del caso (",
    c("⟦CITA NO VERIFICADA: sentencia T-999 de 2019⟧", "c3"),
    ").",
  ),
  bloque("consideraciones-11", "encabezado", "modelo", "consideraciones", t("El mínimo vital", { negrita: true })),
  bloque(
    "consideraciones-12",
    "parrafo",
    "modelo",
    "consideraciones",
    "El mínimo vital, por su parte, se afecta cuando la persona no puede satisfacer sus necesidades básicas y las de su núcleo familiar. Cuando la falta de un tratamiento obliga a asumir un gasto que no se puede costear, la vulneración de la salud puede proyectarse sobre este derecho.",
  ),
  bloque(
    "consideraciones-13",
    "parrafo",
    "plantilla",
    "consideraciones",
    "Definido el marco jurídico aplicable y los criterios constitucionales relevantes, procede este Despacho a continuación a examinar la situación fáctica y jurídica específica puesta en conocimiento en este trámite constitucional.",
  ),
  bloque("informe-de-citas", "titulo", "plantilla", "informe-de-citas", t("INFORME DE CITAS", { negrita: true })),
  bloque("informe-de-citas-1", "parrafo", "plantilla", "informe-de-citas", "3 citas: 1 ok, 1 con alerta, 1 rechazada."),
  bloque(
    "informe-de-citas-2",
    "tabla",
    "plantilla",
    "informe-de-citas",
    t("Sentencia", { negrita: true }),
    t("Estado", { negrita: true }),
    t("Cobertura", { negrita: true }),
    t("Palabras", { negrita: true }),
    t("Sección", { negrita: true }),
    t("M.P. (dataset)", { negrita: true }),
    t("URL", { negrita: true }),
    t("Texto citado", { negrita: true }),
    t("Motivos", { negrita: true }),
  ),
  bloque(
    "informe-de-citas-3",
    "tabla",
    "plantilla",
    "informe-de-citas",
    "T-760 de 2008",
    "OK",
    "98 %",
    "11",
    "mayoría",
    "Manuel José Cepeda Espinosa",
    "https://www.corteconstitucional.gov.co/relatoria/2008/t-760-08.htm",
    "“la salud tiene doble connotación: derecho fundamental y servicio público esencial”",
    "—",
  ),
  bloque(
    "informe-de-citas-4",
    "tabla",
    "plantilla",
    "informe-de-citas",
    "SU-508 de 2020",
    "ALERTA",
    "71 %",
    "14",
    "mayoría",
    "—",
    "https://www.corteconstitucional.gov.co/relatoria/2020/su508-20.htm",
    "“la garantía de continuidad de los tratamientos en curso hace parte del núcleo esencial”",
    "La cobertura del fragmento citado es 71 %.",
  ),
  bloque("alertas-por-nodo", "titulo", "plantilla", "alertas-por-nodo", t("ALERTAS POR NODO", { negrita: true })),
  bloque("alertas-por-nodo-1", "parrafo", "plantilla", "alertas-por-nodo", t("apertura", { negrita: true })),
  bloque(
    "alertas-por-nodo-2",
    "lista",
    "plantilla",
    "alertas-por-nodo",
    "ALERTA: Jev lee el sentido del fallo como 'niega' (97 %) y la cláusula decision_a_quo ('declaró improcedente la acción de tutela') como 'improcedente' (91 %); verifique decision_a_quo.",
  ),
  ...pie(3),
];

export const VISTA_BORRADOR: Vista = {
  tipo: "borrador",
  sha256: "0".repeat(64),
  paginas: [{ bloques: [...pagina1, ...pie(1)] }, { bloques: [...pagina2, ...pie(2)] }, { bloques: pagina3 }],
  citas,
  indice: [
    { id: "asunto", titulo: "I. ASUNTO" },
    { id: "antecedentes-del-caso", titulo: "II. ANTECEDENTES DEL CASO" },
    { id: "la-sentencia-impugnada", titulo: "III. LA SENTENCIA IMPUGNADA" },
    { id: "la-impugnacion", titulo: "IV. LA IMPUGNACIÓN" },
    { id: "consideraciones", titulo: "V. CONSIDERACIONES" },
    { id: "informe-de-citas", titulo: "INFORME DE CITAS" },
    { id: "alertas-por-nodo", titulo: "ALERTAS POR NODO" },
  ],
};

export const ESTADO_BORRADOR: EstadoCaso = {
  ok: true,
  estado: "esperando_decision",
  job_activo: null,
  resumen: {
    metadatos: {
      cui_1a: "05001408800920260041200",
      cui_2a: "05001 40 88 009 2026 00412 01",
      juzgado_a_quo: "Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín",
      accionante: "Marta Inés Quintero Bedoya",
      accionadas: ["EPS Horizonte Salud S.A.S."],
      impugnante: "Marta Inés Quintero Bedoya (accionante)",
      impugnante_rol: "accionante",
      decision_a_quo: "declaró improcedente la acción de tutela",
    },
    jev_metadatos: {
      modelo: "jev-1",
      umbral: 0.8,
      preguntas: {
        sentido_fallo: { choice: "niega", confidence: 0.97 },
        sentido_clausula: { choice: "improcedente", confidence: 0.91 },
        rol_impugnante: { choice: "accionante", confidence: 0.99 },
      },
      coincide: { sentido: false, rol_impugnante: true },
    },
    bitacora: [
      { nodo: "roles", intento: 1, proveedor: "jev", modelo_pedido: "jev-1", modelo_efectivo: "jev-1" },
      { nodo: "apertura", intento: 1, proveedor: "anthropic", modelo_pedido: "claude-sonnet-5-5", modelo_efectivo: "claude-sonnet-5-5" },
      { nodo: "metadatos", intento: 1, proveedor: "jev", modelo_pedido: "jev-1", modelo_efectivo: "jev-1" },
      { nodo: "consideraciones", intento: 1, proveedor: "anthropic", modelo_pedido: "claude-sonnet-5-5", modelo_efectivo: "claude-sonnet-5-5" },
    ],
    alertas: {
      ingesta: [
        "1a-007 007_007RespuestaEPSHorizonteSaludSAS_ContestacionTutela_Radicado2026-00412_Anexos.pdf: texto truncado a 120000 caracteres para el LLM.",
        "1a-002 002_002EscritoTutelaQuinteroBedoya.pdf (escrito_tutela): páginas sin texto legible: 3, 4.",
      ],
      apertura: [
        "ALERTA: Jev lee el sentido del fallo como 'niega' (97 %) y la cláusula decision_a_quo ('declaró improcedente la acción de tutela') como 'improcedente' (91 %); verifique decision_a_quo.",
        "ALERTA: antecedentes: tiene 1202 palabras, por encima del máximo esperado (510 a 1140).",
        "ALERTA: En metadatos, campo accionadas, la ingesta extrajo ['EPS HORIZONTE SALUD S.A.S.', 'SUPERINTENDENCIA NACIONAL DE SALUD'] y el modelo leyó ['EPS Horizonte Salud S.A.S.', 'Superintendencia Nacional de Salud – Supersalud']; se conserva el de la ingesta, verifique cuál es correcto.",
      ],
      consideraciones: [
        "BLOQUEA: La cita c3 (sentencia T-999 de 2019) fue rechazada: no aparece en el dataset de la Corte Constitucional.",
      ],
    },
  },
};

const CONTESTACION = "007_007RespuestaEPSHorizonteSaludSAS_ContestacionTutela_Radicado2026-00412_Anexos.pdf";

const evidencia = (doc_id: string, documento: string, rol: EvidenciaVista["rol"], pagina: number, total: number, cita: string): EvidenciaVista => ({
  doc_id,
  documento,
  rol,
  pagina,
  total_paginas: total,
  cita,
  ocr: false,
  inicio: null,
  fin: null,
});

const VERIFICADA: ApoderadoVista = {
  id: ID_VERIFICADA,
  nombre: "ANDREA PAOLA GIRALDO MONTOYA",
  parte: "EPS HORIZONTE SALUD S.A.S.",
  rol_parte: "accionada",
  tipo_persona: "juridica",
  estado: "verificado",
  fase: "listo",
  motivos: [],
  cedula: "1017234568",
  tarjeta: "287415",
  vigencia: {
    estado: "vigente",
    fase: "listo",
    cedula: "1017234568",
    tarjeta_registro: "287415",
    consultado_en: "2026-11-17T10:42:00-05:00",
    origen: "extension",
    certificado_url: null,
    numero_certificado: "4471203",
    codigo_verificacion: null,
    detalle: "",
    grave: false,
  },
  poder: {
    estado: "hallado",
    tipo: "poder",
    evidencia: evidencia(
      "1a-007",
      CONTESTACION,
      "contestacion",
      4,
      12,
      "confiero poder especial, amplio y suficiente a la doctora ANDREA PAOLA GIRALDO MONTOYA, identificada con la cédula de ciudadanía No. 1.017.234.568 y tarjeta profesional No. 287.415 del C. S. de la J., para que en nombre de la entidad que represento conteste la acción de tutela de la referencia",
    ),
    otorgante: "JUAN CARLOS RESTREPO URIBE",
    parte: "EPS HORIZONTE SALUD S.A.S.",
    cadena: {
      estado: "confirmada",
      otorgante: "JUAN CARLOS RESTREPO URIBE",
      cargo: "representante legal",
      evidencia: evidencia("1a-007", CONTESTACION, "contestacion", 6, 12, "Representante legal: JUAN CARLOS RESTREPO URIBE, identificado con cédula de ciudadanía"),
    },
    mencion: evidencia("1a-007", CONTESTACION, "contestacion", 1, 12, "actuando como apoderada judicial de la EPS HORIZONTE SALUD S.A.S., según el poder que se adjunta"),
    documentos_revisados: 14,
    hay_hallado: true,
  },
  cotejos: [
    { ok: true, texto: "El nombre coincide con quien actúa en el expediente" },
    { ok: true, texto: "T.P. 287415 coincide con el certificado de vigencia" },
    { ok: true, texto: "Representa a EPS HORIZONTE SALUD S.A.S., accionada" },
    { ok: true, texto: "Lo otorga JUAN CARLOS RESTREPO URIBE, representante legal, acreditado en el certificado de existencia (Doc. 1a-007, p. 6)" },
  ],
  revisado: false,
  revision_vencida: false,
  bloquea: false,
  huella: "5d0c8e1f2a3b4c6d",
};

const POR_REVISAR: ApoderadoVista = {
  id: ID_POR_REVISAR,
  nombre: "LUIS FERNANDO OSPINA ARANGO",
  parte: "MARTA INÉS QUINTERO BEDOYA",
  rol_parte: "accionante",
  tipo_persona: "natural",
  estado: "revisar",
  fase: "necesita_ayuda",
  motivos: ["Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial."],
  cedula: "71654320",
  tarjeta: "198344",
  vigencia: {
    estado: "sin_consultar",
    fase: "necesita_ayuda",
    cedula: "71654320",
    tarjeta_registro: null,
    consultado_en: null,
    origen: null,
    certificado_url: null,
    numero_certificado: null,
    codigo_verificacion: null,
    detalle: "",
    grave: false,
  },
  poder: {
    estado: "hallado",
    tipo: "poder",
    evidencia: evidencia(
      "1a-002",
      "002_002EscritoTutelaQuinteroBedoya.pdf",
      "escrito_tutela",
      6,
      6,
      "Yo, MARTA INÉS QUINTERO BEDOYA, mayor de edad, confiero poder especial, amplio y suficiente al doctor LUIS FERNANDO OSPINA ARANGO, abogado con T.P. 198.344 del C. S. de la J., para que en mi nombre presente acción de tutela",
    ),
    otorgante: "MARTA INÉS QUINTERO BEDOYA",
    parte: "MARTA INÉS QUINTERO BEDOYA",
    cadena: { estado: "no_aplica", otorgante: "", cargo: "", evidencia: null },
    mencion: null,
    documentos_revisados: 14,
    hay_hallado: true,
  },
  cotejos: [
    { ok: true, texto: "El nombre coincide con quien actúa en el expediente" },
    { ok: null, texto: "La T.P. aún no se ha cotejado con el certificado de vigencia" },
    { ok: true, texto: "Representa a MARTA INÉS QUINTERO BEDOYA, accionante" },
  ],
  revisado: false,
  revision_vencida: false,
  bloquea: false,
  huella: "9a8b7c6d5e4f3a2b",
};

const NO_VERIFICADO: ApoderadoVista = {
  id: ID_NO_VERIFICADO,
  nombre: "CARLOS EDUARDO PINEDA RUIZ",
  parte: "CLÍNICA SANTA AURORA S.A.S.",
  rol_parte: "vinculada",
  tipo_persona: "juridica",
  estado: "no_verificado",
  fase: "listo",
  motivos: ["La tarjeta profesional 97551 figura como «SUSPENDIDA» en el certificado N.° 4471388."],
  cedula: "16000040",
  tarjeta: "097551",
  vigencia: {
    estado: "no_vigente",
    fase: "listo",
    cedula: "16000040",
    tarjeta_registro: "97551",
    consultado_en: "2026-11-17T10:43:00-05:00",
    origen: "extension",
    certificado_url: null,
    numero_certificado: "4471388",
    codigo_verificacion: null,
    detalle: "",
    grave: true,
  },
  poder: {
    estado: "hallado",
    tipo: "poder",
    evidencia: evidencia(
      "1a-011",
      "011_011RespuestaClinicaSantaAurora.pdf",
      "contestacion",
      5,
      7,
      "otorgo poder especial al doctor CARLOS EDUARDO PINEDA RUIZ, con T.P. 097.551, para que represente a la clínica en la acción de tutela",
    ),
    otorgante: "",
    parte: "CLÍNICA SANTA AURORA S.A.S.",
    cadena: { estado: "sin_certificado", otorgante: "", cargo: "", evidencia: null },
    mencion: null,
    documentos_revisados: 14,
    hay_hallado: true,
  },
  cotejos: [
    { ok: true, texto: "El nombre coincide con quien actúa en el expediente" },
    { ok: true, texto: "T.P. 097551 coincide con el certificado de vigencia" },
    { ok: true, texto: "Representa a CLÍNICA SANTA AURORA S.A.S., vinculada" },
    { ok: null, texto: "No hay certificado de existencia y representación de CLÍNICA SANTA AURORA S.A.S. en el expediente" },
  ],
  revisado: false,
  revision_vencida: false,
  bloquea: true,
  huella: "0f1e2d3c4b5a6978",
};

const MOTIVO_NO_INSCRITO =
  "El Registro Nacional de Abogados certifica que la cédula del abogado no está inscrita como abogado(a). Verifique el número; si actúa con licencia temporal, esta consulta no la cubre.";

/**
 * El mismo abogado de la clínica cuando el Registro Nacional de Abogados certifica que su cédula no está inscrita
 * como abogado(a): la cédula consta en una página del expediente leída sin OCR, así que queda en rojo. En el
 * simulacro sale con `?consulta=no_inscrito`.
 */
export const NO_INSCRITO: ApoderadoVista = {
  ...NO_VERIFICADO,
  motivos: [MOTIVO_NO_INSCRITO],
  vigencia: {
    ...NO_VERIFICADO.vigencia,
    estado: "no_inscrito",
    tarjeta_registro: null,
    numero_certificado: "4471391",
    grave: true,
  },
  cotejos: [
    { ok: true, texto: "El nombre coincide con quien actúa en el expediente" },
    { ok: false, texto: "La cédula no figura inscrita como abogado(a) en el Registro Nacional de Abogados" },
    { ok: true, texto: "Representa a CLÍNICA SANTA AURORA S.A.S., vinculada" },
    { ok: null, texto: "No hay certificado de existencia y representación de CLÍNICA SANTA AURORA S.A.S. en el expediente" },
  ],
  huella: "7e6d5c4b3a291807",
};

export const APODERADOS_BORRADOR: ApoderadosRespuesta = {
  identificacion: "lista",
  apoderados: [NO_VERIFICADO, POR_REVISAR, VERIFICADA],
  sin_apoderado: [{ nombre: "SUPERINTENDENCIA NACIONAL DE SALUD", rol_parte: "accionada", nota: "Actúa por su representante legal o por un funcionario." }],
  alertas: [],
  consulta: { activa: false, extension: "no_conectada", modo: "extension", pausa_hasta: null },
  bloquea_decision: true,
  editable: true,
};

/** Lo que responde el mock para cualquier otro caso (p. ej., el de la decisión): sin identificación, nada bloquea. */
export const APODERADOS_SIN_IDENTIFICACION: ApoderadosRespuesta = {
  identificacion: "no_disponible",
  apoderados: [],
  sin_apoderado: [],
  alertas: [],
  consulta: { activa: false, extension: "no_conectada", modo: "extension", pausa_hasta: null },
  bloquea_decision: false,
  editable: true,
};

/**
 * Variantes del simulacro de apoderados, con ?consulta=… en la URL de `VITE_MOCK=1 pnpm dev`:
 * - sin parámetro: extensión conectada; la consulta de quien sigue sin consultar pasa por En cola → Consultando… → vigente;
 * - `ayuda`: la primera consulta no obtiene respuesta (Necesita su ayuda, con la pausa de la Rama Judicial) y
 *   «Reintentar consulta automática» la resuelve;
 * - `apagada`: la consulta automática está apagada (el certificado se sube a mano);
 * - `sin_extension` / `desactualizada`: la extensión no está o es vieja, y la cola espera;
 * - `sin_identificar`: el caso es anterior a la identificación y «Identificar apoderados» la hace;
 * - `no_inscrito`: el abogado de la clínica tiene una cédula que no está inscrita como abogado(a) (en rojo).
 */
type EscenarioConsulta = "" | "ayuda" | "apagada" | "sin_extension" | "desactualizada" | "sin_identificar" | "no_inscrito";

function escenarioConsulta(): EscenarioConsulta {
  if (typeof location === "undefined") return "";
  const valor = new URLSearchParams(location.search).get("consulta") ?? "";
  return (["ayuda", "apagada", "sin_extension", "desactualizada", "sin_identificar", "no_inscrito"] as const).find((e) => e === valor) ?? "";
}

function estadoInicialMock(): ApoderadosRespuesta {
  const datos = structuredClone(APODERADOS_BORRADOR);
  const escenario = escenarioConsulta();
  datos.consulta.extension = escenario === "sin_extension" ? "no_conectada" : escenario === "desactualizada" ? "desactualizada" : "conectada";
  if (escenario === "apagada") datos.consulta.modo = "apagada";
  if (escenario === "sin_identificar") return { ...structuredClone(APODERADOS_SIN_IDENTIFICACION), consulta: datos.consulta };
  if (escenario === "no_inscrito") datos.apoderados = datos.apoderados.map((a) => (a.id === NO_INSCRITO.id ? structuredClone(NO_INSCRITO) : a));
  return datos;
}

let apoderadosMock = estadoInicialMock();
/** La cola simulada: cada lectura de /apoderados la hace avanzar un paso (en cola → consultando → resultado). */
let colaMock: { id: string; consultando: boolean; forzada: boolean }[] = [];
/** Lecturas que faltan para que termine la identificación simulada (null: no se está identificando). */
let identificacionMock: number | null = null;

function revisarMock({ ruta, cuerpo }: PeticionMock): ApoderadoVista {
  const id = decodeURIComponent(/\/apoderados\/([^/]+)\/revision$/.exec(ruta)?.[1] ?? "");
  const actual = apoderadosMock.apoderados.find((a) => a.id === id);
  if (!actual) throw new ErrorApi(404, "Apoderado no encontrado.", "Apoderado no encontrado.");
  if (!editableMock()) throw falla(409, NO_EDITABLE);
  const revision = cuerpo as RevisionCuerpo | undefined;
  if (revision?.revisado && revision.huella !== actual.huella) {
    throw new ErrorApi(409, "El estado del apoderado cambió; revíselo de nuevo.", "El estado del apoderado cambió; revíselo de nuevo.");
  }
  const vista = conRevision(actual, Boolean(revision?.revisado));
  const apoderados = apoderadosMock.apoderados.map((a) => (a.id === id ? vista : a));
  apoderadosMock = { ...apoderadosMock, apoderados, bloquea_decision: apoderados.some((a) => a.bloquea) };
  return structuredClone(vista);
}

const RUTA_APODERADOS = `/api/casos/${CASO_MOCK_BORRADOR}/apoderados`;
const RUTA_EXPEDIENTE = `/api/casos/${CASO_MOCK_BORRADOR}/expediente`;

const falla = (estado: number, detalle: string): ErrorApi => new ErrorApi(estado, detalle, detalle);

/** Los documentos del expediente simulado: nombre, rol, total de páginas y las citas que las evidencias toman de ellos. */
interface DocumentoMock {
  documento: string;
  rol: PaginaExpediente["rol"];
  total: number;
  citas: Map<number, string[]>;
}

function documentosMock(): Map<string, DocumentoMock> {
  const documentos = new Map<string, DocumentoMock>();
  for (const ap of APODERADOS_BORRADOR.apoderados) {
    for (const e of [ap.poder.evidencia, ap.poder.cadena?.evidencia, ap.poder.mencion]) {
      if (!e?.rol) continue;
      const doc = documentos.get(e.doc_id) ?? { documento: e.documento, rol: e.rol, total: e.total_paginas ?? e.pagina, citas: new Map<number, string[]>() };
      doc.citas.set(e.pagina, [...(doc.citas.get(e.pagina) ?? []), e.cita]);
      documentos.set(e.doc_id, doc);
    }
  }
  return documentos;
}

/** Parte la cita en renglones como los de un PDF, para que el visor tenga que encontrarla a través de los saltos. */
function renglones(texto: string, ancho = 78): string {
  const lineas: string[] = [];
  let actual = "";
  for (const palabra of texto.split(/\s+/)) {
    if (actual && actual.length + palabra.length + 1 > ancho) {
      lineas.push(actual);
      actual = palabra;
    } else {
      actual = actual ? `${actual} ${palabra}` : palabra;
    }
  }
  if (actual) lineas.push(actual);
  return lineas.join("\n");
}

export function paginaMock(docId: string, n: number): PaginaExpediente {
  const doc = documentosMock().get(docId);
  if (!doc) throw falla(404, "Documento no encontrado en el expediente.");
  if (!Number.isInteger(n) || n < 1 || n > doc.total) throw falla(404, "La página no existe en el documento.");
  const citas = doc.citas.get(n) ?? [];
  const texto = [
    `Señor\nJUEZ NOVENO PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS\nMedellín\nRef.: Acción de tutela 05001 40 88 009 2026 00412 00`,
    ...citas.map((cita) => renglones(`Por medio del presente escrito, ${cita}, en los términos que siguen.`)),
    `Página ${n} de ${doc.total} · ${doc.documento}`,
  ].join("\n\n");
  return { doc_id: docId, documento: doc.documento, rol: doc.rol, pagina: n, total: doc.total, texto, ocr: false, es_pdf: true };
}

const certificadosMock = new Map<string, Blob>();
const MAX_CERTIFICADO = 2 * 1024 * 1024;

/** Lo que haría el servidor al leer un certificado subido: la tarjeta queda vigente o no y el estado del abogado se vuelve a evaluar. */
function conCertificado(ap: ApoderadoVista, vigente: boolean, url: string): ApoderadoVista {
  const tarjeta = ap.tarjeta ?? ap.vigencia.tarjeta_registro;
  const poderOk = ap.poder.estado === "hallado" || ap.poder.estado === "manual";
  const estado = !vigente ? "no_verificado" : poderOk ? "verificado" : "revisar";
  const sobreTarjeta = /tarjeta|vigencia/i;
  const motivos = vigente
    ? estado === "verificado"
      ? []
      : ap.motivos.filter((m) => !sobreTarjeta.test(m))
    : [`La tarjeta profesional${tarjeta ? ` ${tarjeta}` : ""} figura como «SUSPENDIDA» en el certificado subido por el despacho.`];
  const cotejoTarjeta = { ok: true, texto: `T.P. ${tarjeta ?? "sin número"} coincide con el certificado de vigencia` };
  return {
    ...ap,
    estado,
    fase: "listo",
    motivos,
    vigencia: {
      ...ap.vigencia,
      estado: vigente ? "vigente" : "no_vigente",
      fase: "listo",
      tarjeta_registro: tarjeta,
      consultado_en: new Date().toISOString(),
      origen: "manual",
      certificado_url: url,
      numero_certificado: vigente ? "4471999" : "4472000",
      codigo_verificacion: "5e1d0c9b8a7f6e5d4c3b2a19f8e7d6c5b4a39281706f5e4d3c2b1a0918273645",
      detalle: "Certificado subido por el despacho.",
    },
    cotejos: ap.cotejos.map((c) => (/^(La )?T\.P\./.test(c.texto) ? cotejoTarjeta : c)),
    revisado: false,
    revision_vencida: ap.revisado || ap.revision_vencida,
    bloquea: estado === "no_verificado",
    huella: `${vigente ? "c0" : "d1"}${ap.huella.slice(2)}`,
  };
}

/**
 * La subida del certificado de vigencia. El nombre del archivo no viaja (useApoderados lo cambia por
 * certificado.pdf para que no lleve la cédula), así que el simulacro lo decide por el contenido: un PDF cuyo
 * texto dice «NO VIGENTE» o «SUSPENDIDO» deja al abogado en rojo, cualquier otro PDF completo lo deja vigente,
 * un PDF truncado no se puede leer y lo que no es un PDF se rechaza.
 */
async function subirMock({ ruta, cuerpo }: PeticionMock): Promise<ApoderadoVista> {
  const id = decodeURIComponent(/\/apoderados\/([^/]+)\/certificado$/.exec(ruta)?.[1] ?? "");
  const actual = apoderadosMock.apoderados.find((ap) => ap.id === id);
  if (!actual) throw falla(404, "Apoderado no encontrado.");
  if (!editableMock()) throw falla(409, "El caso no está esperando la decisión: no se puede subir el certificado ahora.");
  const archivo = cuerpo instanceof FormData ? cuerpo.get("archivo") : null;
  if (!(archivo instanceof Blob)) throw falla(422, "No se recibió el archivo.");
  if (archivo.size > MAX_CERTIFICADO) throw falla(413, "El archivo pesa más de 2 MB.");
  const contenido = new TextDecoder("latin1").decode(await archivo.arrayBuffer());
  if (!contenido.startsWith("%PDF-")) throw falla(422, "El archivo no es un PDF.");
  if (!contenido.includes("%%EOF")) throw falla(422, "No se pudo leer el certificado.");
  const vigente = !/NO\s+VIGENTE|SUSPENDID|no_vigente/i.test(contenido);
  certificadosMock.set(id, archivo);
  // En el navegador el PDF se abre desde la memoria; sin URL.createObjectURL (pruebas) queda la ruta del servidor.
  const url = typeof URL.createObjectURL === "function" ? URL.createObjectURL(archivo) : `${RUTA_APODERADOS}/${encodeURIComponent(id)}/certificado`;
  const vista = conCertificado(actual, vigente, url);
  const apoderados = apoderadosMock.apoderados.map((ap) => (ap.id === id ? vista : ap));
  apoderadosMock = { ...apoderadosMock, apoderados, bloquea_decision: apoderados.some((ap) => ap.bloquea) };
  return structuredClone(vista);
}

function certificadoMock({ ruta }: PeticionMock): Blob {
  const id = decodeURIComponent(/\/apoderados\/([^/]+)\/certificado$/.exec(ruta)?.[1] ?? "");
  const pdf = certificadosMock.get(id);
  if (!pdf) throw falla(404, "No hay certificado guardado para este apoderado.");
  return pdf;
}

/** Vuelve el simulacro de /apoderados a su estado inicial (para las pruebas). */
export function reiniciarApoderadosMock(): void {
  apoderadosMock = estadoInicialMock();
  colaMock = [];
  identificacionMock = null;
  certificadosMock.clear();
}

const CONSULTA_APAGADA = "La consulta automática de la vigencia está apagada en esta instalación: descargue el certificado en la página de la Rama Judicial y súbalo aquí.";
const NO_EDITABLE = "El caso no está esperando la decisión: la revisión de los apoderados no se puede cambiar ahora.";

/** Vuelve a evaluar al abogado como lo haría el servidor (las reglas de estado_apoderados.py, simplificadas). */
function evaluarMock(ap: ApoderadoVista): ApoderadoVista {
  const { estado: v, fase } = ap.vigencia;
  const p = ap.poder.estado;
  // La cédula no inscrita es grave si consta en el expediente sin OCR; el simulador no lo sabe y se queda con lo que dijo el servidor.
  const grave = v === "no_vigente" || (v === "no_inscrito" && ap.vigencia.grave);
  const estado = grave || p === "ajeno" ? "no_verificado" : v === "vigente" && (p === "hallado" || p === "manual") ? "verificado" : "revisar";
  const motivos: string[] = [];
  if (v === "no_vigente") motivos.push(`La tarjeta profesional ${ap.tarjeta ?? ""} figura como «SUSPENDIDA» en el certificado.`.replace("  ", " "));
  else if (v === "no_inscrito") motivos.push(MOTIVO_NO_INSCRITO);
  else if (v === "inaccesible") motivos.push("La Rama Judicial no respondió a la consulta de la vigencia.");
  else if (v === "sin_cedula") motivos.push("No se encontró la cédula del abogado en el expediente: no se pudo consultar su tarjeta.");
  else if (v === "sin_consultar") motivos.push("Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial.");
  if (p === "descartado") motivos.push("El poder hallado se descartó en la revisión: señale el poder a mano.");
  if (p === "sin_poder") motivos.push(`No se halló en el expediente un poder que lo faculte para representar a ${ap.parte}.`);
  const enCurso = fase === "en_cola" || fase === "consultando";
  const ayuda = !enCurso && ["sin_consultar", "inaccesible", "sin_cedula", "ilegible", "otra_persona"].includes(v);
  const nueva = { ...ap, estado, motivos: estado === "verificado" ? [] : motivos } as ApoderadoVista;
  nueva.fase = enCurso ? fase : ayuda ? "necesita_ayuda" : "listo";
  nueva.vigencia = { ...nueva.vigencia, fase: nueva.fase, grave };
  const huella = `${estado}-${v}-${p}-${ap.poder.evidencia?.doc_id ?? ""}${ap.poder.evidencia?.pagina ?? ""}`;
  const cambio = huella !== ap.huella;
  return { ...nueva, huella, revisado: cambio ? false : ap.revisado, revision_vencida: cambio ? ap.revisado || ap.revision_vencida : ap.revision_vencida, bloquea: estado === "no_verificado" && !(cambio ? false : ap.revisado) };
}

function guardarMock(vista: ApoderadoVista): ApoderadoVista {
  const apoderados = apoderadosMock.apoderados.map((ap) => (ap.id === vista.id ? vista : ap));
  apoderadosMock = { ...apoderadosMock, apoderados, bloquea_decision: apoderados.some((ap) => ap.bloquea) };
  return vista;
}

const conFase = (ap: ApoderadoVista, fase: ApoderadoVista["fase"]): ApoderadoVista => ({ ...ap, fase, vigencia: { ...ap.vigencia, fase } });

/** Lo que trae la consulta simulada: en el escenario `ayuda`, la primera vez la Rama Judicial no responde. */
function resultadoConsulta(ap: ApoderadoVista, forzada: boolean): ApoderadoVista {
  if (escenarioConsulta() === "ayuda" && !forzada) {
    apoderadosMock.consulta.pausa_hasta = new Date(Date.now() + 15 * 60_000).toISOString();
    return evaluarMock({ ...ap, fase: "listo", vigencia: { ...ap.vigencia, estado: "inaccesible", fase: "listo", detalle: "La Rama Judicial no respondió." } });
  }
  apoderadosMock.consulta.pausa_hasta = null;
  const tarjeta = ap.tarjeta ?? ap.vigencia.tarjeta_registro;
  return evaluarMock({
    ...ap,
    fase: "listo",
    vigencia: {
      ...ap.vigencia,
      estado: "vigente",
      fase: "listo",
      tarjeta_registro: tarjeta,
      consultado_en: new Date().toISOString(),
      origen: "extension",
      numero_certificado: "4471777",
      detalle: "",
    },
    cotejos: ap.cotejos.map((c) => (/^(La )?T\.P\./.test(c.texto) ? { ok: true, texto: `T.P. ${tarjeta ?? "sin número"} coincide con el certificado de vigencia` } : c)),
  });
}

/** Cada lectura avanza la cola un paso: el primero de la fila pasa a consultarse y, a la siguiente, tiene resultado. */
function avanzarColaMock(): void {
  const [primero] = colaMock;
  if (primero) {
    const ap = apoderadosMock.apoderados.find((a) => a.id === primero.id);
    if (!ap) colaMock.shift();
    else if (!primero.consultando) {
      primero.consultando = true;
      guardarMock(conFase(ap, "consultando"));
    } else {
      colaMock.shift();
      guardarMock(resultadoConsulta(ap, primero.forzada));
    }
  }
  apoderadosMock.consulta.activa = colaMock.length > 0;
}

/** Como el servidor: mientras corre el trabajo de la identificación el caso no admite cambios. */
const editableMock = (): boolean => apoderadosMock.editable && identificacionMock === null;

function leerApoderadosMock(): ApoderadosRespuesta {
  if (identificacionMock !== null) {
    identificacionMock -= 1;
    if (identificacionMock <= 0) {
      identificacionMock = null;
      apoderadosMock = { ...structuredClone(APODERADOS_BORRADOR), consulta: apoderadosMock.consulta };
    }
  }
  avanzarColaMock();
  return { ...structuredClone(apoderadosMock), editable: editableMock() };
}

/** Pone en la cola simulada la consulta de los abogados pedidos, como POST …/consultar. */
function encolarMock(ids: readonly string[], forzar: boolean): void {
  const { consulta } = apoderadosMock;
  for (const id of ids) {
    const ap = apoderadosMock.apoderados.find((a) => a.id === id);
    if (!ap?.cedula || colaMock.some((e) => e.id === id)) continue;
    if (!forzar && !["sin_consultar", "inaccesible"].includes(ap.vigencia.estado)) continue;
    // Sin una extensión que sepa consultar, la cola espera: el abogado sigue necesitando ayuda.
    if (consulta.modo === "extension" && consulta.extension !== "conectada") continue;
    colaMock.push({ id, consultando: false, forzada: forzar });
    guardarMock(conFase(ap, "en_cola"));
  }
  apoderadosMock.consulta.activa = colaMock.length > 0;
}

function consultarMock({ cuerpo }: PeticionMock): ApoderadosRespuesta {
  const pedido = (cuerpo ?? {}) as ConsultarCuerpo;
  if (!editableMock()) throw falla(409, NO_EDITABLE);
  if (apoderadosMock.consulta.modo === "apagada") throw falla(409, CONSULTA_APAGADA);
  const ids = pedido.ids ?? apoderadosMock.apoderados.map((a) => a.id);
  if (ids.some((id) => !apoderadosMock.apoderados.some((a) => a.id === id))) throw falla(404, "Apoderado no encontrado.");
  encolarMock(ids, Boolean(pedido.forzar));
  return structuredClone(apoderadosMock);
}

/** La página señalada a mano: debe nombrar al abogado; la cita es el párrafo donde aparece. */
function poderManualMock(ap: ApoderadoVista, docId: string, n: number): EvidenciaVista {
  let pagina: PaginaExpediente;
  try {
    pagina = paginaMock(docId, n);
  } catch {
    throw falla(422, "La página indicada no existe en el expediente.");
  }
  const parrafo = pagina.texto.split("\n\n").find((p) => partirResaltado(p, ap.nombre).some((t) => t.marcado));
  if (!parrafo) throw falla(422, "El nombre del abogado no aparece en esa página.");
  return { ...evidencia(docId, pagina.documento, pagina.rol, n, pagina.total, parrafo.replace(/\s+/g, " ").trim()), ocr: pagina.ocr };
}

function ajustarMock({ ruta, cuerpo }: PeticionMock): ApoderadoVista {
  const id = decodeURIComponent(/\/apoderados\/([^/]+)\/ajustes$/.exec(ruta)?.[1] ?? "");
  if (!editableMock()) throw falla(409, NO_EDITABLE);
  const actual = apoderadosMock.apoderados.find((ap) => ap.id === id);
  if (!actual) throw falla(404, "Apoderado no encontrado.");
  const pedido = (cuerpo ?? {}) as AjusteCuerpo;
  if (!("poder_manual" in pedido) && !("poder_descartado" in pedido) && !("cedula" in pedido)) {
    throw falla(422, "Indique qué corregir: el poder señalado a mano, si el poder hallado no es correcto o la cédula del abogado.");
  }
  let ap = structuredClone(actual);
  const original = APODERADOS_BORRADOR.apoderados.find((a) => a.id === id)?.poder;
  if (pedido.cedula !== undefined && pedido.cedula !== null) {
    const digitos = pedido.cedula.replace(/\D/g, "");
    if (!/^[\d.\s]+$/.test(pedido.cedula.trim()) || digitos.length < 5 || digitos.length > 10) throw falla(422, "La cédula debe tener entre 5 y 10 dígitos.");
    if (ap.cedula && ap.cedula !== digitos) throw falla(409, "La cédula del abogado consta en el expediente; no se puede cambiar a mano.");
    ap = { ...ap, cedula: digitos, vigencia: { ...ap.vigencia, cedula: digitos, estado: ap.vigencia.estado === "sin_cedula" ? "sin_consultar" : ap.vigencia.estado } };
  }
  if (pedido.poder_manual) {
    const ev = poderManualMock(ap, pedido.poder_manual.doc_id, pedido.poder_manual.pagina);
    ap = { ...ap, poder: { ...ap.poder, estado: "manual", tipo: "poder", evidencia: ev, parte: ap.parte, cadena: null } };
  } else if (pedido.poder_descartado === true) {
    if (!ap.poder.evidencia) throw falla(409, "No hay un poder hallado que se pueda descartar.");
    ap = { ...ap, poder: { ...ap.poder, estado: "descartado", evidencia: null, cadena: null } };
  } else if ((pedido.poder_descartado === false || pedido.poder_manual === null) && original) {
    ap = { ...ap, poder: structuredClone(original) };
  }
  guardarMock(evaluarMock(ap));
  if (pedido.cedula && apoderadosMock.consulta.modo !== "apagada") encolarMock([id], false);
  return structuredClone(apoderadosMock.apoderados.find((a) => a.id === id) as ApoderadoVista);
}

/** «Identificar apoderados» en el escenario `sin_identificar`: el trabajo dura dos lecturas y deja la identificación lista. */
function identificarMock(): ApoderadosRespuesta {
  if (apoderadosMock.identificacion === "lista") return structuredClone(apoderadosMock);
  if (identificacionMock !== null) throw falla(409, "Ya hay una ejecución en curso para este caso.");
  identificacionMock = 2;
  return { ...structuredClone(apoderadosMock), editable: editableMock() };
}

const noEncontrado = (detalle: string) => () => {
  throw falla(404, detalle);
};

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/vista\/borrador$/, respuesta: VISTA_BORRADOR },
  { metodo: "GET", ruta: RUTA_APODERADOS, respuesta: leerApoderadosMock },
  { metodo: "POST", ruta: `${RUTA_APODERADOS}/consultar`, respuesta: consultarMock },
  { metodo: "POST", ruta: `${RUTA_APODERADOS}/identificar`, respuesta: identificarMock },
  { metodo: "PUT", ruta: new RegExp(`^${RUTA_APODERADOS}/[^/]+/ajustes$`), respuesta: ajustarMock },
  { metodo: "PUT", ruta: new RegExp(`^${RUTA_APODERADOS}/[^/]+/revision$`), respuesta: revisarMock },
  { metodo: "PUT", ruta: new RegExp(`^${RUTA_APODERADOS}/[^/]+/certificado$`), respuesta: subirMock },
  { metodo: "GET", ruta: new RegExp(`^${RUTA_APODERADOS}/[^/]+/certificado$`), respuesta: certificadoMock },
  {
    metodo: "GET",
    ruta: new RegExp(`^${RUTA_EXPEDIENTE}/([^/]+)/paginas/(\\d+)$`),
    respuesta: ({ ruta }) => {
      const [, docId = "", n = "0"] = /\/expediente\/([^/]+)\/paginas\/(\d+)$/.exec(ruta) ?? [];
      return paginaMock(decodeURIComponent(docId), Number(n));
    },
  },
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/apoderados$/, respuesta: APODERADOS_SIN_IDENTIFICACION },
  { metodo: "PUT", ruta: /^\/api\/casos\/[^/]+\/apoderados\/[^/]+\/(?:revision|certificado|ajustes)$/, respuesta: noEncontrado("Apoderado no encontrado.") },
  {
    metodo: "POST",
    ruta: /^\/api\/casos\/[^/]+\/apoderados\/(?:consultar|identificar)$/,
    respuesta: () => {
      throw falla(409, "El caso no está esperando la decisión: no se pueden identificar ni consultar los apoderados ahora.");
    },
  },
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/expediente\/[^/]+\/paginas\/\d+$/, respuesta: noEncontrado("Documento no encontrado en el expediente.") },
  { metodo: "GET", ruta: `/api/casos/${CASO_MOCK_BORRADOR}/estado`, respuesta: ESTADO_BORRADOR },
  {
    metodo: "POST",
    ruta: `/api/casos/${CASO_MOCK_BORRADOR}/run`,
    respuesta: () => ({ job_id: "job-borrador-demo" }),
  },
];
