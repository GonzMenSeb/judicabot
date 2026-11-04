import { ErrorApi } from "../../api/cliente";
import type { Bloque, CasoResumen, CitaVista, PaginaVista, Segmento, TipoBloque, Vista } from "../../api/contrato";
import type { MockRuta } from "../../api/mock";
import type { EstadoCaso } from "./tipos";

const CASO = "quintero-eps-horizonte";
const SIN_FALLO = "sin-fallo";

type Parte = string | Segmento;

const seg = (parte: Parte): Segmento => (typeof parte === "string" ? { texto: parte } : parte);
const cita = (texto: string, cita_id: string): Segmento => ({ texto, cita_id });
const neg = (texto: string): Segmento => ({ texto, negrita: true });

let contador = 0;
function bloque(tipo: TipoBloque, seccion: string | null, origen: Bloque["origen"], ...partes: Parte[]): Bloque {
  contador += 1;
  return { id: `${seccion ?? "encabezado"}-${contador}`, tipo, origen, seccion, segmentos: partes.map(seg) };
}
const plantilla = (tipo: TipoBloque, seccion: string | null, ...partes: Parte[]) => bloque(tipo, seccion, "plantilla", ...partes);
const modelo = (seccion: string, ...partes: Parte[]) => bloque("parrafo", seccion, "modelo", ...partes);
const titulo = (seccion: string, texto: string) => plantilla("titulo", seccion, texto);
const fila = (etiqueta: string, valor: string) => plantilla("tabla", null, neg(etiqueta), valor);

const PIE = [
  "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
  "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
  "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
];

const conPie = (n: number, bloques: Bloque[]): PaginaVista => ({
  bloques: [...bloques, ...PIE.map((t, k) => ({ ...plantilla("pie", null, t), id: `pie-${n}-${k + 1}` }))],
});

const CITAS: CitaVista[] = [
  { id: "c1", texto: "la salud tiene doble connotación: derecho fundamental y servicio público esencial", fuente: "sentencia T-760 de 2008", cobertura: 0.98, estado: "verificada", detalle: null },
  { id: "c2", texto: "la garantía de continuidad de los tratamientos en curso hace parte del núcleo esencial", fuente: "sentencia SU-508 de 2020", cobertura: 0.71, estado: "revisar", detalle: "La cobertura del fragmento citado es 71 %. Compare con la relatoría antes de firmar." },
  { id: "c3", texto: "la EPS no puede suspender el servicio por trámites internos", fuente: "sentencia T-999 de 2019", cobertura: null, estado: "rechazada", detalle: "No aparece en el dataset de la Corte Constitucional." },
];

const PAGINAS: PaginaVista[] = [
  conPie(1, [
    plantilla("parrafo", null, neg("JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO DE MEDELLÍN")),
    plantilla("parrafo", null, "Medellín, tres (03) de noviembre de dos mil veintiséis (2026)"),
    fila("Radicado", "050014088009 2026 00412 01"),
    fila("Accionante", "MARTA INÉS QUINTERO BEDOYA"),
    fila("Accionada", "EPS HORIZONTE SALUD S.A.S."),
    fila("Procedencia", "JUZGADO 9 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN"),
    fila("Derechos", "SALUD, MÍNIMO VITAL"),
    fila("Decisión", "REVOCA"),
    titulo("asunto", "I. ASUNTO"),
    modelo("asunto", "Procede el Despacho a resolver la impugnación presentada por la accionante contra el fallo de tutela emitido el veintiocho (28) de septiembre de dos mil veintiséis (2026) por el Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín, por medio del cual se declaró improcedente la acción de tutela."),
    titulo("antecedentes", "II. ANTECEDENTES DEL CASO"),
    modelo("antecedentes", "La señora MARTA INÉS QUINTERO BEDOYA, identificada con cédula de ciudadanía 43.999.101, presentó acción de tutela el catorce (14) de septiembre de dos mil veintiséis (2026) contra la EPS HORIZONTE SALUD S.A.S., entidad a la que se encuentra afiliada en el régimen contributivo, por considerar vulnerados sus derechos fundamentales a la salud y al mínimo vital."),
    modelo("antecedentes", "Relató que padece una enfermedad crónica por la cual su médico tratante le prescribió un medicamento de uso continuo, que la entidad le suministró hasta agosto de dos mil veintiséis (2026), cuando dejó de entregárselo sin una razón que le fuera comunicada por escrito."),
  ]),
  conPie(2, [
    modelo("antecedentes", "Con fundamento en lo anterior, solicitó que se ordenara a la entidad suministrar el medicamento prescrito, de manera continua y sin dilaciones, y que se le brindara el tratamiento integral que su patología requiera. Adjuntó la fórmula médica vigente y la copia de su historia clínica."),
    titulo("sentencia-impugnada", "III. LA SENTENCIA IMPUGNADA"),
    modelo("sentencia-impugnada", "Mediante sentencia del veintiocho (28) de septiembre de dos mil veintiséis (2026), el Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín declaró improcedente la acción de tutela."),
    modelo("sentencia-impugnada", "Para sustentar su decisión, el juez de primera instancia consideró que no se cumplía el requisito de subsidiariedad, pues la accionante disponía de un mecanismo ante la Superintendencia Nacional de Salud. Añadió que no encontró acreditado un perjuicio irremediable que habilitara el estudio de fondo."),
    titulo("impugnacion", "IV. LA IMPUGNACIÓN"),
    modelo("impugnacion", "En relación con el reparo R1, la impugnante señala que «la orden médica vigente que prescribe el medicamento y que anexé al escrito de tutela no fue valorada por el juez»."),
    modelo("impugnacion", "En relación con el reparo R2, la impugnante señala que «la salud es un derecho fundamental y no puedo esperar el trámite ante la Superintendencia teniendo una enfermedad crónica»."),
    modelo("impugnacion", "Con fundamento en lo anterior, la impugnante solicita al superior que revoque el fallo de primera instancia y ampare sus derechos fundamentales."),
  ]),
  conPie(3, [
    titulo("consideraciones", "V. CONSIDERACIONES"),
    bloque("encabezado", "consideraciones", "plantilla", "Competencia"),
    modelo("consideraciones", "Este Despacho es competente para resolver la impugnación presentada contra la sentencia de tutela proferida el veintiocho (28) de septiembre de dos mil veintiséis (2026), de conformidad con el artículo 32 del Decreto 2591 de 1991."),
    bloque("encabezado", "consideraciones", "plantilla", "Presupuestos generales de procedibilidad de la acción de tutela"),
    modelo("consideraciones", "La acción de tutela, consagrada en el artículo 86 de la Constitución Política y reglamentada por el Decreto 2591 de 1991, se erige como un mecanismo preferente y sumario concebido para la protección inmediata y efectiva de los derechos constitucionales fundamentales. El juicio de procedibilidad exige verificar la legitimación en la causa, la inmediatez y la subsidiariedad."),
    modelo("consideraciones", "En relación con la legitimación en la causa por activa, el ordenamiento constitucional faculta a toda persona para solicitar el amparo de sus garantías fundamentales, actuando por sí misma, por medio de apoderado judicial o mediante agente oficioso cuando el titular no se encuentre en condiciones de promover su propia defensa."),
  ]),
  conPie(4, [
    bloque("encabezado", "consideraciones", "plantilla", "La salud y la continuidad del tratamiento"),
    modelo("consideraciones", "La Corte Constitucional ha reiterado que la salud tiene una doble connotación, como derecho fundamental y como servicio público esencial ", cita("(sentencia T-760 de 2008)", "c1"), ". En esa medida, el Estado y las entidades que prestan el servicio están obligados a garantizarlo conforme a los principios de eficiencia, universalidad y solidaridad."),
    modelo("consideraciones", "De la mano de lo anterior, la jurisprudencia ha precisado que la continuidad de los tratamientos en curso hace parte del núcleo esencial del derecho ", cita("(sentencia SU-508 de 2020)", "c2"), ". Al respecto, el alto tribunal señaló:"),
    bloque("cita_bloque", "consideraciones", "modelo", { texto: "“la garantía de continuidad de los tratamientos en curso hace parte del núcleo esencial”", cita_id: "c2" }),
    bloque("encabezado", "consideraciones", "plantilla", "La subsidiariedad y la vía ante la Superintendencia Nacional de Salud"),
    modelo("consideraciones", "El requisito de subsidiariedad exige verificar si el afectado dispone de otro mecanismo de defensa judicial idóneo y eficaz. La Corte ha sostenido que, en materia de salud, el mecanismo ante la Superintendencia no desplaza al juez de tutela cuando no resulta eficaz frente a las circunstancias particulares del caso ", cita("⟦CITA NO VERIFICADA: sentencia T-999 de 2019⟧", "c3"), "."),
    bloque("encabezado", "consideraciones", "plantilla", "El mínimo vital"),
    modelo("consideraciones", "El mínimo vital se afecta cuando la persona no puede satisfacer sus necesidades básicas y las de su núcleo familiar."),
  ]),
  conPie(5, [
    titulo("caso-concreto", "VI. CASO CONCRETO"),
    modelo("caso-concreto", "Sobre el reparo R1, la impugnante señala que la orden médica vigente no fue valorada. El Despacho lo acoge: el a quo omitió valorar la orden médica vigente; la EPS suspendió el tratamiento sin justificación."),
    modelo("caso-concreto", "En consecuencia, el Despacho considera que debe revocar el fallo de primera instancia y amparar los derechos fundamentales invocados."),
    plantilla("parrafo", "resuelve", "En mérito de lo expuesto, el ", neg("Juzgado Tercero Penal del Circuito con Función de Conocimiento de Medellín"), ", administrando justicia en nombre de la República y por autoridad de la Ley,"),
    titulo("resuelve", "VII. RESUELVE"),
    bloque("resuelve_numeral", "resuelve", "plantilla", neg("PRIMERO: REVOCAR"), " la sentencia de primera instancia del veintiocho (28) de septiembre de dos mil veintiséis (2026)."),
    bloque("resuelve_numeral", "resuelve", "plantilla", neg("SEGUNDO: AMPARAR"), " los derechos fundamentales a la salud y al mínimo vital de MARTA INÉS QUINTERO BEDOYA."),
    bloque("resuelve_numeral", "resuelve", "plantilla", neg("TERCERO: ORDENAR"), " a la EPS HORIZONTE SALUD S.A.S. que, en el término de cuarenta y ocho (48) horas hábiles, autorice y entregue el medicamento prescrito a la accionante, sin dilaciones."),
    plantilla("firma", "resuelve", "NOTIFÍQUESE Y CÚMPLASE"),
    plantilla("firma", "resuelve", "SANTIAGO ALEJANDRO CADAVID DUQUE"),
    plantilla("firma", "resuelve", "JUEZ"),
  ]),
];

const VISTA: Vista = {
  tipo: "fallo",
  sha256: "9f2c4a6e1b7d8035a4c1e9f0b2d37a68c5e4f1a0b9d8c7e6f5a4b3c2d1e0f9a8",
  paginas: PAGINAS,
  citas: CITAS,
  indice: PAGINAS.flatMap((p) => p.bloques.filter((b) => b.tipo === "titulo")).map((b) => ({ id: b.id, titulo: b.segmentos.map((s) => s.texto).join("") })),
};

const PRINCIPAL = "02SegundaInstancia/C01Principal";
const ARCHIVOS = [
  `${PRINCIPAL}/001ActaRepartoSegunda.pdf`,
  `${PRINCIPAL}/002AutoAsumeSegunda202600412.docx`,
  `${PRINCIPAL}/003FalloSegunda202600412.docx`,
  `${PRINCIPAL}/004FormatoCalificacion202600412.docx`,
  `${PRINCIPAL}/fallo.vista.json`,
  "borradores_correo/EnvioFormatoCalidad.docx",
  "borradores_correo/NotificacionFalloPartes.docx",
  "por_radicar/OficioRemiteCorteConstitucional.docx",
  "trabajo/declaracion_ia.docx",
  "trabajo/informe_verificacion.docx",
  "trabajo/previo.docx",
  "trabajo/previo.vista.json",
];

const ESTADO: EstadoCaso = {
  ok: true,
  estado: "terminado",
  salidas: ARCHIVOS,
  resumen: {
    citas: [
      { id: "c1", sentencia_original: "sentencia T-760 de 2008", sentencia_norm: "T-760 de 2008", estado: "ok", cobertura: 0.98, motivos: [] },
      { id: "c2", sentencia_original: "sentencia SU-508 de 2020", sentencia_norm: "SU-508 de 2020", estado: "alerta", cobertura: 0.71, motivos: ["La cobertura del fragmento citado es 71 %."] },
      { id: "c3", sentencia_original: "sentencia T-999 de 2019", sentencia_norm: null, estado: "rechazada", cobertura: null, motivos: ["No aparece en el dataset de la Corte Constitucional."] },
    ],
    alertas: {
      ingesta: ["La página 3 de 004Memorial.pdf no tiene texto y no llegó al modelo."],
      consideraciones: [
        "ALERTA: La cita c2 (SU-508 de 2020) requiere revisión: La cobertura del fragmento citado es 71 %.",
        "ALERTA: El bloque 2 supera el rango de extensión previsto para consideraciones.",
      ],
    },
    metadatos: { cui_1a: "05001408800920260041200", cui_2a: "05001408800920260041201", juzgado_a_quo: "Juzgado 9 Penal Municipal con Función de Control de Garantías de Medellín", accionante: "Marta Inés Quintero Bedoya" },
  },
  error: null,
  job_activo: null,
};

const RESUMENES: CasoResumen[] = [
  {
    id: CASO,
    nombre: "Quintero c. EPS Horizonte",
    radicado: "05001408800920260041201",
    accionante: "Marta Inés Quintero Bedoya",
    accionadas: ["EPS Horizonte Salud S.A.S."],
    juzgado_a_quo: "Juzgado 9 Penal Municipal con Función de Control de Garantías de Medellín",
    estado: "terminado",
    etapa: 4,
    siguiente_paso: "Ver el fallo",
    n_insumos: 9,
    n_alertas: 3,
    job_activo: null,
    actualizado: new Date().toISOString(),
  },
  {
    id: SIN_FALLO,
    nombre: "Duque c. EPS Ceiba Salud",
    radicado: "05001408800920260028801",
    accionante: "Luis Duque Salazar",
    accionadas: ["EPS Ceiba Salud"],
    juzgado_a_quo: "Juzgado 4 Penal Municipal de Medellín",
    estado: "esperando_decision",
    etapa: 2,
    siguiente_paso: "Revisar el borrador y decidir",
    n_insumos: 6,
    n_alertas: 1,
    job_activo: null,
    actualizado: new Date().toISOString(),
  },
];

const CON_FALLO = new Set([CASO, "mejia-2026-00301"]);
const idDe = (ruta: string) => decodeURIComponent(/^\/api\/casos\/([^/?]+)/.exec(ruta)?.[1] ?? "");

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: "/api/casos", respuesta: RESUMENES },
  ...RESUMENES.map((resumen): MockRuta => ({ metodo: "GET", ruta: `/api/casos/${resumen.id}/resumen`, respuesta: resumen })),
  {
    metodo: "GET",
    ruta: /^\/api\/casos\/[^/]+\/vista\/fallo$/,
    respuesta: ({ ruta }) => {
      if (!CON_FALLO.has(idDe(ruta))) throw new ErrorApi(404, "El fallo aún no existe.", "El fallo aún no existe.");
      return VISTA;
    },
  },
  {
    metodo: "GET",
    ruta: /^\/api\/casos\/[^/]+\/salidas$/,
    respuesta: ({ ruta }) => {
      return { archivos: CON_FALLO.has(idDe(ruta)) ? ARCHIVOS : ARCHIVOS.slice(0, 2) };
    },
  },
  {
    metodo: "GET",
    ruta: /^\/api\/casos\/[^/]+\/estado$/,
    respuesta: ({ ruta }) => {
      if (!CON_FALLO.has(idDe(ruta))) {
        return { ok: true, estado: "esperando_decision", salidas: ARCHIVOS.slice(0, 2), resumen: { citas: [], alertas: {}, metadatos: ESTADO.resumen?.metadatos }, error: null, job_activo: null } satisfies EstadoCaso;
      }
      return ESTADO;
    },
  },
];
