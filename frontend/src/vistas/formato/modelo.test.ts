import { describe, expect, it } from "vitest";
import { CAMPOS_MOCK, VALORES_MOCK } from "./mock";
import { agrupar, con, cuerpoParaGuardar, esSucio, leerErrores, lineas, texto } from "./modelo";

describe("modelo del formato", () => {
  it("agrupa los campos por grupo en el orden del catálogo", () => {
    const secciones = agrupar(CAMPOS_MOCK);
    expect(secciones.map((s) => s.grupo)).toEqual(["Despacho", "Firmas", "Contacto", "Cierres y pies de página"]);
    expect(secciones.flatMap((s) => s.campos)).toHaveLength(CAMPOS_MOCK.length);
  });

  it("lee texto y líneas tolerando tipos inesperados", () => {
    expect(texto(VALORES_MOCK, "ciudad")).toBe("Medellín");
    expect(texto(VALORES_MOCK, "firma_correo")).toContain("\n");
    expect(texto(VALORES_MOCK, "inexistente")).toBe("");
    expect(lineas(VALORES_MOCK, "pie_auto")).toHaveLength(2);
    expect(lineas(VALORES_MOCK, "ciudad")).toEqual(["Medellín"]);
    expect(lineas(VALORES_MOCK, "inexistente")).toEqual([]);
  });

  it("detecta cambios de valores y de plantilla", () => {
    const base = { valores: VALORES_MOCK, plantilla: "B" as const };
    expect(esSucio(base, { ...base })).toBe(false);
    expect(esSucio({ ...base, plantilla: "A" }, base)).toBe(true);
    expect(esSucio({ ...base, valores: con(VALORES_MOCK, "juez", "Otra") }, base)).toBe(true);
  });

  it("descarta las líneas vacías de las listas al guardar y conserva el resto", () => {
    const valores = con(con(VALORES_MOCK, "pie_auto", ["uno", "  ", "", "dos"]), "ciudad", " Bogotá ");
    const cuerpo = cuerpoParaGuardar({ valores, plantilla: "A" }, CAMPOS_MOCK);
    expect(cuerpo.plantilla_gen).toBe("A");
    expect(cuerpo.valores.pie_auto).toEqual(["uno", "dos"]);
    expect(cuerpo.valores.ciudad).toBe(" Bogotá ");
  });

  it("asigna los errores por campo, con el prefijo de listas, y deja el resto como generales", () => {
    const errores = leerErrores(
      { errores: [{ campo: "ciudad", mensaje: "debe ser texto." }, { campo: "pie_fallo.1", mensaje: "tiene un valor no válido." }, { campo: "", mensaje: "no es un JSON válido." }, { campo: "plantilla_gen", mensaje: "valor no válido." }] },
      CAMPOS_MOCK,
    );
    expect(errores?.porCampo).toEqual({ ciudad: "Debe ser texto.", pie_fallo: "Tiene un valor no válido." });
    expect(errores?.generales).toEqual(["No es un JSON válido.", "plantilla_gen: Valor no válido."]);
    expect(leerErrores("texto", CAMPOS_MOCK)).toBeNull();
    expect(leerErrores({}, CAMPOS_MOCK)).toBeNull();
  });
});
