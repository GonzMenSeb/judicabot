import { describe, expect, it } from "vitest";
import type { CasoResumen } from "../../api/contrato";
import { accionDe, agrupar, descripcionAvance, etapaDestino, filtrar, grupoDe, hrefCaso, partesDe, tonoDe, tramosDe, varianteDe } from "./agrupar";
import { casosMock } from "./mock";

const casos = casosMock as CasoResumen[];

describe("agrupar", () => {
  it("separa en atención, en redacción y terminados con el orden de la lista", () => {
    const grupos = agrupar(casos);
    expect(grupos.map((g) => [g.id, g.casos.map((c) => c.id)])).toEqual([
      ["atencion", ["quintero-bedoya", "cardenas-ospina", "arango-londono"]],
      ["trabajando", ["restrepo-gil"]],
      ["terminados", ["mejia-rios", "duque-salazar"]],
    ]);
  });

  it("omite los grupos vacíos", () => {
    expect(agrupar(casos.filter((c) => c.estado === "terminado")).map((g) => g.id)).toEqual(["terminados"]);
    expect(agrupar([])).toEqual([]);
  });

  it("mapea estados a grupos, tonos, acciones y variantes", () => {
    expect(grupoDe("error")).toBe("atencion");
    expect(grupoDe("sin_iniciar")).toBe("atencion");
    expect(grupoDe("corriendo")).toBe("trabajando");
    expect(grupoDe("terminado")).toBe("terminados");
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

describe("filtrar", () => {
  it("busca sin tildes ni mayúsculas en nombre, partes, juzgado y radicado", () => {
    expect(filtrar(casos, "CARDENAS").map((c) => c.id)).toEqual(["cardenas-ospina"]);
    expect(filtrar(casos, "ceiba").map((c) => c.id)).toEqual(["arango-londono", "duque-salazar"]);
    expect(filtrar(casos, "00412").map((c) => c.id)).toEqual(["quintero-bedoya"]);
    expect(filtrar(casos, "juzgado 14").map((c) => c.id)).toEqual(["arango-londono"]);
  });

  it("ignora separadores en el radicado", () => {
    const caso = { ...casos[0]!, radicado: "05001 40 88 009 2026 00412 00" };
    expect(filtrar([caso], "2026-00412")).toHaveLength(1);
    expect(filtrar([caso], "2026-00999")).toHaveLength(0);
    expect(filtrar([caso], "2026 00412")).toHaveLength(1);
    expect(filtrar([caso], "202600412")).toHaveLength(1);
  });

  it("devuelve todo con consulta vacía y nada si no coincide", () => {
    expect(filtrar(casos, "  ")).toHaveLength(casos.length);
    expect(filtrar(casos, "zzz")).toEqual([]);
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
