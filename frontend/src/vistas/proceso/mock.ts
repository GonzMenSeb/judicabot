import type { MockRuta } from "../../api/mock";
import { casoActual, jobActual } from "../../estado";

type Paso = [etapa: string, tipo: string, texto: string];

const REDACCION: Paso[] = [
  ["ingesta", "lee", "Abro la carpeta 01PrimeraInstancia/C01Principal: 9 archivos PDF."],
  ["ingesta", "lee", "pdftotext extrae el texto de 8 archivos. En 009.pdf, 2 de 3 páginas no tienen capa de texto."],
  ["ingesta", "verifica", "OCR en español sobre las páginas 2 y 3 de 009.pdf: texto recuperado, calidad media."],
  ["ingesta", "lee", "005.pdf dice «Fallo: 412/2026» y trae una parte resolutiva: es el fallo de primera instancia. 006.pdf es la impugnación y 007.pdf el auto que la concede."],
  ["ingesta", "verifica", "Jev confirma los roles con 93 % o más. Propone «Memorial» para 009.pdf (94 %)."],
  ["ingesta", "verifica", "Están las tres piezas obligatorias: escrito de tutela, fallo de primera instancia e impugnación."],
  ["apertura", "lee", "Entrego al modelo los 9 documentos con su rol, su nombre y las páginas marcadas."],
  ["apertura", "razona", "El escrito de tutela (002.pdf, p. 1) dice que a la accionante le suspendieron el medicamento que su médico le prescribió. Los derechos invocados son la salud y el mínimo vital."],
  ["apertura", "razona", "El encabezado del fallo de primera instancia dice «NIEGA», pero su parte resolutiva (005.pdf, p. 5) declara improcedente la acción por subsidiariedad. Me quedo con la parte resolutiva."],
  ["apertura", "razona", "La impugnación (006.pdf) plantea dos reparos: no se valoró la orden médica vigente (R1) y se desconoció el carácter fundamental de la salud (R2)."],
  ["apertura", "escribe", "Redacto los antecedentes (4 párrafos), la sentencia impugnada (3) y la impugnación (2), citando entre comillas solo lo que consta en los PDF."],
  ["apertura", "verifica", "Cada fecha, nombre y radicado del texto aparece en los documentos: 14 de 14 coinciden."],
  ["consideraciones", "razona", "Del problema jurídico salen tres temas (el máximo permitido es 3): continuidad del tratamiento, subsidiariedad frente a la Superintendencia de Salud y mínimo vital."],
  ["consideraciones", "lee", "Busco en el dataset de la Corte Constitucional sentencias sobre salud y continuidad de tratamientos."],
  ["consideraciones", "razona", "T-760 de 2008 sirve para la doble connotación de la salud. SU-508 de 2020 sirve para la continuidad del tratamiento. Guardo el fragmento literal de cada una."],
  ["consideraciones", "escribe", "Redacto «La salud y la continuidad del tratamiento», con dos citas textuales."],
  ["consideraciones", "escribe", "Redacto «La subsidiariedad y la vía ante la Superintendencia Nacional de Salud» y «El mínimo vital»."],
  ["consideraciones", "razona", "No saco conclusiones sobre este caso: el caso concreto se escribe después, con la decisión del juez."],
  ["verificacion", "verifica", "T-760 de 2008: encontrada en el dataset. Magistrado ponente: Manuel José Cepeda Espinosa."],
  ["verificacion", "verifica", "El fragmento citado coincide en un 98 % con la relatoría. Verificada."],
  ["verificacion", "verifica", "SU-508 de 2020: encontrada, pero el fragmento coincide solo en un 71 %. Queda con alerta."],
  ["verificacion", "verifica", "T-999 de 2019: no aparece en el dataset. Queda sin verificar."],
  ["verificacion", "verifica", "Informe de citas: 1 verificada, 1 con alerta, 1 sin verificar."],
  ["verificacion", "razona", "Borrador listo. Me detengo antes del caso concreto."],
];

const DECISION: Paso[] = [
  ["caso_concreto", "lee", "Recibo su decisión: REVOCAR, AMPARAR."],
  ["caso_concreto", "razona", "El eje que usted dio es: «El a quo omitió valorar la orden médica vigente; la EPS suspendió el tratamiento sin justificación.»"],
  ["caso_concreto", "escribe", "Resuelvo R1 y R2 según la disposición que usted marcó, citando las sentencias ya verificadas."],
  ["caso_concreto", "verifica", "El texto concluye que se debe revocar el fallo de primera instancia, igual que su decisión."],
  ["documentos", "escribe", "Armo el fallo con la plantilla Generación A, el RESUELVE y la firma del juez."],
  ["documentos", "escribe", "Genero el Formato Factor Calidad, el oficio a la Corte y dos borradores de correo."],
  ["documentos", "verifica", "Valido la estructura de cada .docx: sin errores."],
];

interface Escenario {
  pasos: Paso[];
  paso: number;
  ritmo: number;
  fin: { estado: "terminado" | "error"; error: string | null } | null;
}

function escenarioDe(jobId: string): Escenario {
  const sim = /^sim-(.+)$/.exec(jobId)?.[1];
  if (sim === "mitad") return { pasos: REDACCION.slice(0, 15), paso: 0, ritmo: 40, fin: null };
  if (sim === "listo") return { pasos: REDACCION, paso: 0, ritmo: 40, fin: { estado: "terminado", error: null } };
  if (sim === "fallo" || jobId.startsWith("job-decidir")) return { pasos: DECISION, paso: 0, ritmo: sim ? 40 : 900, fin: { estado: "terminado", error: null } };
  if (sim === "error") {
    return {
      pasos: [...REDACCION.slice(0, 16), ["consideraciones", "error", "El modelo devolvió una respuesta que no cumple el formato esperado (intento 3 de 3)."]],
      paso: 0,
      ritmo: 40,
      fin: { estado: "error", error: "El modelo no devolvió una respuesta válida tras 3 intentos. Puede continuar la ejecución desde donde quedó." },
    };
  }
  return { pasos: REDACCION, paso: 0, ritmo: 900, fin: { estado: "terminado", error: null } };
}

class FuenteSimulada {
  private oyentes = new Map<string, Array<(ev: Event) => void>>();
  private temporizador: ReturnType<typeof setTimeout> | undefined;
  private cerrada = false;
  private escenario: Escenario;
  readonly url: string;
  readonly readyState = 1;

  constructor(url: string) {
    this.url = url;
    const [ruta = "", consulta = ""] = url.split("?");
    const jobId = decodeURIComponent(/\/api\/jobs\/([^/]+)\/eventos/.exec(ruta)?.[1] ?? "");
    const desde = Number(new URLSearchParams(consulta).get("desde") ?? 0) || 0;
    this.escenario = escenarioDe(jobId);
    this.escenario.paso = desde;
    this.temporizador = setTimeout(() => {
      this.emitir("open");
      this.avanzar();
    }, 60);
  }

  addEventListener(tipo: string, oyente: (ev: Event) => void) {
    this.oyentes.set(tipo, [...(this.oyentes.get(tipo) ?? []), oyente]);
  }

  close() {
    this.cerrada = true;
    clearTimeout(this.temporizador);
  }

  private emitir(tipo: string, datos?: unknown) {
    if (this.cerrada) return;
    const ev = datos === undefined ? new Event(tipo) : new MessageEvent(tipo, { data: JSON.stringify(datos) });
    this.oyentes.get(tipo)?.forEach((oyente) => oyente(ev));
  }

  private avanzar() {
    const e = this.escenario;
    const paso = e.pasos[e.paso];
    if (paso) {
      e.paso += 1;
      this.emitir("evento", {
        n: e.paso,
        t: new Date(Date.UTC(2026, 10, 3, 14, 0, 0) + e.paso * 4200).toISOString(),
        etapa: paso[0],
        tipo: paso[1],
        texto: paso[2],
        datos: null,
      });
      this.temporizador = setTimeout(() => this.avanzar(), e.ritmo);
    } else if (e.fin) {
      this.emitir("fin", e.fin);
    }
  }
}

function sembrarEscenario() {
  const escenario = new URLSearchParams(location.search).get("escenario");
  const caso = /^#\/segunda\/([^/]+)\/proceso/.exec(location.hash)?.[1];
  if (!escenario || !caso) return;
  casoActual.value = decodeURIComponent(caso);
  jobActual.value = `sim-${escenario}`;
}

if (import.meta.env.VITE_MOCK && typeof window !== "undefined") {
  (window as unknown as { EventSource: unknown }).EventSource = FuenteSimulada;
  sembrarEscenario();
}

export const mocks: MockRuta[] = [
  { metodo: "POST", ruta: /^\/api\/casos\/[^/]+\/run$/, respuesta: () => ({ job_id: "sim-vivo" }) },
];
