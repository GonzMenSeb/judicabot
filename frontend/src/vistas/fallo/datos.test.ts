import { describe, expect, it } from "vitest";
import type { Vista } from "../../api/contrato";
import {
  agruparSalidas,
  calcularAvisos,
  citasDeEstado,
  citasDeVista,
  destinoSinFallo,
  nombreLegible,
  rutaFallo,
  urlSalida,
} from "./datos";
import type { EstadoCaso } from "./tipos";

const P = "02SegundaInstancia/C01Principal";
const ARCHIVOS = [
  `${P}/001ActaRepartoSegunda.pdf`,
  `${P}/002AutoAsumeSegunda202600412.docx`,
  `${P}/003FalloSegunda202600412.docx`,
  `${P}/fallo.vista.json`,
  "borradores_correo/NotificacionFalloPartes.docx",
  "por_radicar/OficioRemiteCorteConstitucional.docx",
  "trabajo/declaracion_ia.docx",
  "trabajo/informe_verificacion.docx",
  "trabajo/previo.vista.json",
  "otra/rara.docx",
];

describe("salidas", () => {
  it("encuentra el fallo principal y escapa la ruta en la URL", () => {
    expect(rutaFallo(ARCHIVOS)).toBe(`${P}/003FalloSegunda202600412.docx`);
    expect(rutaFallo([`${P}/001ActaRepartoSegunda.pdf`])).toBeNull();
    expect(urlSalida("caso uno", "a b/c#d.docx")).toBe("/api/casos/caso%20uno/salidas/a%20b/c%23d.docx");
  });

  it("da nombres legibles y cae al nombre del archivo si no conoce el patrón", () => {
    expect(nombreLegible("trabajo/declaracion_ia.docx")).toBe("Declaración de uso de IA");
    expect(nombreLegible(`${P}/004FormatoCalificacion202600412.docx`)).toBe("Formato Factor Calidad");
    expect(nombreLegible("otra/rara.docx")).toBe("rara");
  });

  it("agrupa por carpeta, oculta las vistas JSON y excluye el fallo principal", () => {
    const grupos = agruparSalidas(ARCHIVOS, rutaFallo(ARCHIVOS));
    expect(grupos.map((g) => g.titulo)).toEqual(["Para el expediente", "Por radicar", "Borradores de correo", "Documentos de trabajo", "otra"]);
    const todos = grupos.flatMap((g) => g.salidas.map((s) => s.archivo));
    expect(todos).not.toContain("fallo.vista.json");
    expect(todos).not.toContain("previo.vista.json");
    expect(todos).not.toContain("003FalloSegunda202600412.docx");
    expect(grupos[0]?.salidas.map((s) => s.nombre)).toEqual(["Acta de reparto de la impugnación", "Auto que asume el conocimiento"]);
  });
});

const vista = (citas: Vista["citas"], citadas: string[]): Vista => ({
  tipo: "fallo",
  sha256: "x",
  paginas: [
    {
      bloques: [
        {
          id: "b1",
          tipo: "parrafo",
          origen: "modelo",
          seccion: "s",
          segmentos: citadas.map((id) => ({ texto: `(${id})`, cita_id: id })),
        },
      ],
    },
  ],
  citas,
  indice: [],
});

const cv = (id: string, estado: Vista["citas"][number]["estado"]): Vista["citas"][number] => ({
  id,
  texto: "t",
  fuente: `fuente ${id}`,
  cobertura: null,
  estado,
  detalle: null,
});

describe("avisos", () => {
  it("cuenta solo las citas que aparecen en el texto del fallo", () => {
    const citas = citasDeVista(vista([cv("c1", "verificada"), cv("c2", "revisar"), cv("c3", "rechazada")], ["c1", "c2"]));
    expect(citas).toEqual([
      { fuente: "fuente c1", estado: "verificada" },
      { fuente: "fuente c2", estado: "revisar" },
    ]);
  });

  it("Revise combina citas sin verificar y con alerta y menciona el informe solo si existe", () => {
    const citas = citasDeEstado([
      { id: "c2", sentencia_original: "sentencia SU-508 de 2020", sentencia_norm: "SU-508 de 2020", estado: "alerta" },
      { id: "c3", sentencia_original: "sentencia T-999 de 2019", estado: "rechazada" },
      { id: "c1", sentencia_original: "sentencia T-760 de 2008", estado: "ok" },
    ]);
    const con = calcularAvisos({ citas, alertas: {}, archivos: ARCHIVOS });
    expect(con.revise).toHaveLength(1);
    expect(con.revise[0]?.texto).toBe(
      "Quedó una cita sin verificar (sentencia T-999 de 2019) y una con alerta (SU-508 de 2020). El informe de verificación las detalla.",
    );
    const sin = calcularAvisos({ citas, alertas: {}, archivos: [] });
    expect(sin.revise[0]?.texto).not.toContain("informe");
  });

  it("no inventa avisos: sin citas problemáticas, sin alertas y sin archivos no hay nada", () => {
    const avisos = calcularAvisos({ citas: citasDeEstado([{ id: "c1", sentencia_original: "T-1", estado: "ok" }]), alertas: [], archivos: [] });
    expect(avisos.revise).toEqual([]);
    expect(avisos.recuerde).toEqual([]);
    expect(avisos.citasVerificadas).toBe(1);
    expect(calcularAvisos({ citas: null, alertas: undefined, archivos: [] })).toEqual({ revise: [], recuerde: [], citasVerificadas: 0 });
  });

  it("las alertas del proceso excluyen las que ya son de una cita y limpian el prefijo", () => {
    const avisos = calcularAvisos({
      citas: [],
      alertas: {
        consideraciones: ["ALERTA: La cita c2 (SU-508 de 2020) requiere revisión: x.", "ALERTA: El bloque 2 es largo.", "ALERTA: El bloque 2 es largo."],
        ingesta: ["Una página no tiene texto."],
      },
      archivos: [],
    });
    expect(avisos.revise[0]?.detalle).toEqual(["Consideraciones: El bloque 2 es largo.", "Documentos: Una página no tiene texto."]);
    expect(avisos.revise[0]?.texto).toContain("2 alertas");
  });

  it("Recuerde sale de los archivos realmente generados", () => {
    const avisos = calcularAvisos({ citas: null, alertas: null, archivos: ARCHIVOS });
    expect(avisos.recuerde.map((a) => a.clave)).toEqual(["ia", "radicar", "correos"]);
    expect(avisos.recuerde[1]?.texto).toBe("Quedó por radicar: Oficio a la Corte Constitucional.");
    expect(calcularAvisos({ citas: null, alertas: null, archivos: [`${P}/003FalloSegunda202600412.docx`] }).recuerde).toEqual([]);
  });
});

describe("destino cuando no hay fallo", () => {
  const estado = (e: Partial<EstadoCaso>): EstadoCaso => ({ estado: "revision", ...e });
  it("elige la etapa que corresponde al estado real", () => {
    expect(destinoSinFallo("c", estado({ estado: "esperando_decision" })).destino.href).toBe("#/segunda/c/decision");
    expect(destinoSinFallo("c", estado({ estado: "revision" })).destino.href).toBe("#/segunda/c/documentos");
    expect(destinoSinFallo("c", estado({ estado: "error", error: "Falló" })).destino.href).toBe("#/segunda/c/proceso");
    expect(destinoSinFallo("c", estado({ job_activo: "j1" })).destino.href).toBe("#/segunda/c/proceso");
    expect(destinoSinFallo("c", null).destino.href).toBe("#/segunda");
  });
});
