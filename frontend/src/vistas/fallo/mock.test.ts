import { describe, expect, it } from "vitest";
import type { Vista } from "../../api/contrato";
import { resolverMock } from "../../api/mock";

const COMPETENCIA =
  "Este Despacho es competente para conocer y resolver el recurso de impugnación interpuesto contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de amparo. En su condición de superior funcional, le corresponde adelantar un examen integral de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina fijada por la Corte Constitucional.";

const texto = (b: Vista["paginas"][number]["bloques"][number]) => b.segmentos.map((s) => s.texto).join("");

describe("mock del fallo", () => {
  it("trae Competencia como un solo párrafo de plantilla", async () => {
    const vista = (await resolverMock({ metodo: "GET", ruta: "/api/casos/quintero-eps-horizonte/vista/fallo", cuerpo: undefined })) as Vista;
    const bloques = vista.paginas.flatMap((p) => p.bloques);
    const i = bloques.findIndex((b) => b.tipo === "encabezado" && texto(b) === "Competencia");
    expect(i).toBeGreaterThanOrEqual(0);
    expect(bloques[i + 1]).toMatchObject({ tipo: "parrafo", origen: "plantilla" });
    expect(texto(bloques[i + 1] as (typeof bloques)[number])).toBe(COMPETENCIA);
    expect(bloques[i + 2]).toMatchObject({ tipo: "encabezado", origen: "plantilla" });
    expect(texto(bloques[i + 2] as (typeof bloques)[number])).toMatch(/^Presupuestos generales de procedibilidad/);
  });
});
