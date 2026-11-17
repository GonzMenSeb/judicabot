import { describe, expect, it } from "vitest";
import { accionDe, descripcionAvance, etapaDestino, hrefCaso, partesDe, tonoDe, tramosDe, varianteDe } from "./agrupar";

describe("ficha", () => {
  it("mapea estados a tonos, acciones y variantes", () => {
    expect(tonoDe("esperando_decision")).toBe("sello");
    expect(tonoDe("error")).toBe("alerta");
    expect(tonoDe("revision")).toBe("");
    expect(accionDe("esperando_decision")).toBe("Decidir");
    expect(varianteDe("esperando_decision")).toBe("sello");
    expect(varianteDe("terminado")).toBe("secundario");
  });
});

describe("destino", () => {
  it.each([
    ["sin_iniciar", 0, "documentos"],
    ["revision", 0, "documentos"],
    ["incompleto", 0, "documentos"],
    ["esperando_decision", 2, "borrador"],
    ["corriendo", 1, "proceso"],
    ["terminado", 4, "fallo"],
    ["error", 0, "documentos"],
    ["error", 1, "proceso"],
    ["error", 3, "proceso"],
  ] as const)("%s en etapa %i lleva a %s", (estado, etapa, esperado) => {
    expect(etapaDestino({ estado, etapa })).toBe(esperado);
  });

  it("codifica el id del caso", () => {
    expect(hrefCaso({ id: "a b", estado: "terminado", etapa: 4 })).toBe("#/segunda/a%20b/fallo");
  });
});

describe("avance", () => {
  it("marca hechos antes de la etapa y activo en la etapa", () => {
    expect(tramosDe(0)).toEqual(["a", "", "", ""]);
    expect(tramosDe(2)).toEqual(["h", "h", "a", ""]);
    expect(tramosDe(4)).toEqual(["h", "h", "h", "h"]);
  });

  it("describe el avance en palabras", () => {
    expect(descripcionAvance(2)).toBe("Avance: paso 3 de 4, Decisión");
    expect(descripcionAvance(4)).toBe("Avance: completo");
  });
});

describe("partesDe", () => {
  it("omite las partes si el nombre ya las contiene", () => {
    expect(partesDe({ nombre: "Marta Quintero c. EPS", accionante: "Marta Quintero", accionadas: ["EPS"] })).toBeNull();
  });

  it("arma accionante contra accionadas", () => {
    expect(partesDe({ nombre: "Tutela 1", accionante: "Ana", accionadas: ["EPS A", "EPS B"] })).toBe("Ana c. EPS A, EPS B");
    expect(partesDe({ nombre: "Tutela 1", accionante: "Ana", accionadas: [] })).toBe("Ana");
    expect(partesDe({ nombre: "Tutela 1", accionante: null, accionadas: [] })).toBeNull();
  });
});
