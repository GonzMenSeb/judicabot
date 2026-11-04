import type { CampoFormato, Despacho, FormatoCuerpo, FormatoRespuesta } from "../../api/contrato";
import type { MockRuta } from "../../api/mock";

const campo = (
  clave: string,
  etiqueta: string,
  ayuda: string,
  tipo: CampoFormato["tipo"],
  grupo: string,
  ...documentos: string[]
): CampoFormato => ({ clave, etiqueta, ayuda, tipo, grupo, documentos });

export const DOCUMENTOS_MOCK: FormatoRespuesta["documentos"] = [
  { id: "fallo", nombre: "Fallo de segunda instancia" },
  { id: "auto", nombre: "Auto que asume conocimiento" },
  { id: "oficio", nombre: "Oficio a la Corte Constitucional" },
  { id: "correos", nombre: "Borradores de correo" },
  { id: "formato", nombre: "Formato de calidad" },
];

export const CAMPOS_MOCK: CampoFormato[] = [
  campo(
    "nombre",
    "Nombre del despacho (encabezado del fallo)",
    "Título que encabeza el fallo, con la ciudad si así se firma. Con la plantilla B sale siempre en mayúsculas.",
    "texto_largo",
    "Despacho",
    "fallo",
  ),
  campo(
    "nombre_corto",
    "Nombre del despacho sin la ciudad",
    "Título del auto que asume conocimiento y del oficio a la Corte Constitucional. Escríbalo sin la ciudad: esta se toma del campo «Ciudad» y se imprime en la línea de la fecha.",
    "texto_largo",
    "Despacho",
    "auto",
    "oficio",
  ),
  campo(
    "nombre_cuerpo",
    "Nombre del despacho dentro del texto",
    "Aparece en la frase «En mérito de lo expuesto, el …» de la parte resolutiva del fallo y como autor del archivo de Word.",
    "texto_largo",
    "Despacho",
    "fallo",
  ),
  campo(
    "ciudad",
    "Ciudad",
    "Va antes de la fecha en el fallo, en el auto y en el oficio (por ejemplo, «Medellín, tres (03) de noviembre de dos mil veintiséis (2026)»).",
    "texto",
    "Despacho",
    "fallo",
    "auto",
    "oficio",
  ),
  campo(
    "juez",
    "Nombre del juez",
    "Firma del fallo y del auto. También se usa como evaluador en el formato de calidad y en el correo de remisión de compulsa de copias.",
    "texto",
    "Firmas",
    "fallo",
    "auto",
    "correos",
    "formato",
  ),
  campo("cargo_juez", "Cargo del juez", "Se imprime debajo del nombre del juez en el fallo y en el auto.", "texto", "Firmas", "fallo", "auto"),
  campo("escribiente", "Nombre del escribiente", "Firma la constancia del auto y cierra los borradores de correo.", "texto", "Firmas", "auto", "correos"),
  campo(
    "cargo_escribiente",
    "Cargo del escribiente",
    "Se imprime debajo del nombre del escribiente en el auto y en los borradores de correo.",
    "texto",
    "Firmas",
    "auto",
    "correos",
  ),
  campo(
    "firmante_oficio",
    "Nombre de quien firma el oficio",
    "Firma del oficio con el que se remite el expediente a la Corte Constitucional.",
    "texto",
    "Firmas",
    "oficio",
  ),
  campo("cargo_firmante_oficio", "Cargo de quien firma el oficio", "Se imprime debajo del nombre de quien firma el oficio.", "texto", "Firmas", "oficio"),
  campo("cargo_evaluador", "Cargo del evaluador", "Cargo que se escribe junto al nombre del juez en el formato de calidad.", "texto", "Firmas", "formato"),
  campo("correo", "Correo electrónico del despacho", "Va en la firma de los borradores de correo.", "texto", "Contacto", "correos"),
  campo("telefono_correo", "Teléfono en la firma de los correos", "Va al final de la firma de los borradores de correo.", "texto", "Contacto", "correos"),
  campo(
    "firma_correo",
    "Líneas del juzgado en la firma de los correos",
    "Una línea por renglón. Van entre el cargo del escribiente y el correo del despacho.",
    "lista",
    "Contacto",
    "correos",
  ),
  campo(
    "cierre_fallo",
    "Fórmula de cierre del fallo",
    "Línea centrada que va antes de la firma del juez (por ejemplo, «NOTIFÍQUESE Y CÚMPLASE»).",
    "texto",
    "Cierres y pies de página",
    "fallo",
  ),
  campo("cierre_auto", "Fórmula de cierre del auto", "Línea centrada que va antes de la firma del juez en el auto.", "texto", "Cierres y pies de página", "auto"),
  campo(
    "pie",
    "Pie de página del fallo (plantilla A)",
    "Una sola línea al pie de cada página del fallo con la plantilla A; la plantilla B usa las líneas de «Pie de página del fallo (plantilla B)». También es el pie de los documentos internos (informe de verificación, declaración de uso de IA y requerimiento).",
    "texto_largo",
    "Cierres y pies de página",
    "fallo",
  ),
  campo(
    "pie_fallo",
    "Pie de página del fallo (plantilla B)",
    "Una línea por renglón. Solo se usa con la plantilla B.",
    "lista",
    "Cierres y pies de página",
    "fallo",
  ),
  campo("pie_auto", "Pie de página del auto", "Una línea por renglón al pie del auto que asume conocimiento.", "lista", "Cierres y pies de página", "auto"),
];

export const VALORES_MOCK: Despacho = {
  nombre: "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO DE MEDELLÍN",
  nombre_corto: "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO",
  nombre_cuerpo: "Juzgado Tercero Penal del Circuito con Función de Conocimiento de Medellín",
  ciudad: "Medellín",
  juez: "SANTIAGO ALEJANDRO CADAVID DUQUE",
  cargo_juez: "JUEZ",
  escribiente: "John Mendoza",
  cargo_escribiente: "Escribiente",
  firmante_oficio: "JOHN MANUEL MENDOZA",
  cargo_firmante_oficio: "Escribiente",
  cargo_evaluador: "Juez 3° Penal del Circuito de Conocimiento",
  pie: "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
  correo: "pcto03med@cendoj.ramajudicial.gov.co",
  telefono_correo: "Tel: 6042328525 Ext. 2903",
  cierre_fallo: "NOTIFÍQUESE Y CÚMPLASE",
  cierre_auto: "NOTIFÍQUESE Y CÚMPLASE",
  pie_fallo: [
    "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
    "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
    "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
  ],
  pie_auto: [
    "Juzgado Tercero Penal del Circuito con Función de Conocimiento, Edificio José Félix de Restrepo Carrera 52 # 42 – 73, Medellín, Antioquia",
    "Correo Electrónico pcto03med@cendoj.ramajudicial.gov.co, Teléfono 2328525 Ext. 92903",
  ],
  firma_correo: ["Juzgado 3 Penal del Circuito con Funciones", "de Conocimiento de Medellín"],
};

let vigente: FormatoCuerpo = { valores: VALORES_MOCK, plantilla_gen: "B" };

const respuesta = (): FormatoRespuesta => ({
  campos: CAMPOS_MOCK,
  valores: vigente.valores,
  plantilla_gen: vigente.plantilla_gen,
  documentos: DOCUMENTOS_MOCK,
});

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: "/api/formato", respuesta: () => structuredClone(respuesta()) },
  {
    metodo: "PUT",
    ruta: "/api/formato",
    respuesta: (peticion) => {
      vigente = structuredClone(peticion.cuerpo as FormatoCuerpo);
      return structuredClone(respuesta());
    },
  },
];
