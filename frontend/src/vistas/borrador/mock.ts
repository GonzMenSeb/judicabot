import type { Bloque, CitaVista, Segmento, TipoBloque, Vista } from "../../api/contrato";
import type { MockRuta } from "../../api/mock";
import type { EstadoCaso } from "./tipos";

export const CASO_MOCK_BORRADOR = "borrador-quintero";

type Origen = Bloque["origen"];

const t = (texto: string, extra: Partial<Segmento> = {}): Segmento => ({ texto, ...extra });
const c = (texto: string, cita_id: string): Segmento => ({ texto, cita_id });

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
    detalle: "No aparece en el dataset de la Corte Constitucional; Quite la cita o reemplácela por una verificable.",
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
    "La señora MARTA INÉS QUINTERO BEDOYA, identificada con cédula de ciudadanía 43.999.101, presentó acción de tutela el catorce (14) de septiembre de dos mil veintiséis (2026) contra la EPS HORIZONTE SALUD S.A.S., entidad a la que se encuentra afiliada en el régimen contributivo, por considerar vulnerados sus derechos fundamentales a la salud y al mínimo vital.",
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
    "El Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín admitió la acción el quince (15) de septiembre de dos mil veintiséis (2026) y ordenó notificar a la accionada. La EPS HORIZONTE SALUD S.A.S. contestó el diecisiete (17) de septiembre siguiente; manifestó que el medicamento no figuraba autorizado para la afiliada y que esta podía acudir a la Superintendencia Nacional de Salud, por lo que solicitó negar el amparo.",
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
      ingesta: ["El documento 009.pdf tiene 2 páginas sin texto."],
      apertura: [
        "ALERTA: Jev lee el sentido del fallo como 'niega' (97 %) y la cláusula decision_a_quo ('declaró improcedente la acción de tutela') como 'improcedente' (91 %); verifique decision_a_quo.",
      ],
      consideraciones: [
        "ALERTA: La cita sentencia T-999 de 2019 no se encontró en el dataset de la Corte Constitucional.",
      ],
    },
  },
};

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/vista\/borrador$/, respuesta: VISTA_BORRADOR },
  { metodo: "GET", ruta: `/api/casos/${CASO_MOCK_BORRADOR}/estado`, respuesta: ESTADO_BORRADOR },
  {
    metodo: "POST",
    ruta: `/api/casos/${CASO_MOCK_BORRADOR}/run`,
    respuesta: () => ({ job_id: "job-borrador-demo" }),
  },
];
