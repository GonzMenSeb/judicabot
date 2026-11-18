import { describe, expect, it } from "vitest";
import { type AvisoAlcance, avisosDeAlcance } from "./alcance";

const ids = (avisos: AvisoAlcance[]) => avisos.map((a) => a.id);

describe("avisosDeAlcance", () => {
  it("la instrucción del issue #17 (Competencia, Decreto 2591 y transición) avisa de texto fijo y no del RESUELVE", () => {
    const instruccion =
      'En la sección Competencia agregue que el Despacho es competente por el factor territorial y elimine la mención al Decreto 2591 de 1991. En la transición diga "A continuación se resuelve el caso".';
    const avisos = avisosDeAlcance(instruccion, "rehacer_consideraciones");
    expect(ids(avisos)).toEqual(["plantilla-fija"]);
    expect(avisos[0]?.texto).toContain("son texto fijo de la plantilla: una corrección no los cambia");
  });

  it.each([
    ["Cambie el accionante del encabezado a Juan Pérez.", "rehacer_apertura", ["encabezado"]],
    ["Agregue un numeral en el resuelve que ordene entregar el medicamento.", "rehacer_consideraciones", ["resuelve"]],
    ["Corrija el Asunto: fue una impugnación del accionante.", "rehacer_consideraciones", ["asunto"]],
    ["En los antecedentes falta la fecha en que se presentó la tutela; agréguela.", "rehacer_consideraciones", ["alcance-apertura"]],
    ["En inmediatez cite la regla de plazo razonable de seis meses.", "rehacer_apertura", ["alcance-consideraciones"]],
    ["AAA-uno: en inmediatez cite la regla de plazo razonable de seis meses.", "rehacer_apertura", ["alcance-consideraciones"]],
    ["BBB-dos: aclare en los antecedentes la fecha de la tutela.", "rehacer_consideraciones", ["alcance-apertura"]],
  ] as const)("«%s» con %s avisa %j", (instruccion, accion, esperados) => {
    expect(ids(avisosDeAlcance(instruccion, accion))).toEqual(esperados);
  });

  it("el Asunto solo avisa con «Rehacer las consideraciones»: con la apertura sí se rehace", () => {
    expect(ids(avisosDeAlcance("Corrija el Asunto: fue una impugnación del accionante.", "rehacer_apertura"))).toEqual([]);
  });

  it("una instrucción que corresponde a la opción elegida no avisa", () => {
    for (const accion of ["rehacer_apertura", "rehacer_consideraciones"] as const) {
      expect(avisosDeAlcance("El a quo declaró improcedente, no negó.", accion)).toEqual([]);
    }
    expect(avisosDeAlcance("En los antecedentes falta la fecha de la tutela.", "rehacer_apertura")).toEqual([]);
    expect(avisosDeAlcance("En inmediatez cite la regla de plazo razonable.", "rehacer_consideraciones")).toEqual([]);
  });

  it("no distingue mayúsculas ni tildes", () => {
    expect(ids(avisosDeAlcance("COMPETENCIA y ARTÍCULO 86", null))).toEqual(["plantilla-fija"]);
    expect(ids(avisosDeAlcance("competencia y articulo 86", null))).toEqual(["plantilla-fija"]);
  });

  it("sin opción elegida solo valen los avisos de plantilla, no los de alcance", () => {
    expect(avisosDeAlcance("En los antecedentes falta la fecha de la tutela.", null)).toEqual([]);
    expect(avisosDeAlcance("En inmediatez cite la regla de plazo razonable.", null)).toEqual([]);
    expect(avisosDeAlcance("Corrija el Asunto.", null)).toEqual([]);
    expect(ids(avisosDeAlcance("Cambie el radicado del encabezado.", null))).toEqual(["encabezado"]);
  });

  it("una instrucción vacía o en blanco no avisa", () => {
    for (const accion of [null, "rehacer_apertura", "rehacer_consideraciones"] as const) {
      expect(avisosDeAlcance("", accion)).toEqual([]);
      expect(avisosDeAlcance("   ", accion)).toEqual([]);
    }
  });

  it("cada regla aporta como máximo un aviso y respeta el orden de las reglas", () => {
    const avisos = avisosDeAlcance(
      "Competencia, legitimación y artículo 86; también el encabezado, el radicado y el resuelve; y la competencia otra vez.",
      "rehacer_consideraciones",
    );
    expect(ids(avisos)).toEqual(["plantilla-fija", "encabezado", "resuelve"]);
  });

  it("«se resuelve el caso» no es el RESUELVE, pero «el resuelve», «parte resolutiva» y «numeral» sí", () => {
    expect(avisosDeAlcance("Diga que se resuelve el caso.", "rehacer_consideraciones")).toEqual([]);
    expect(ids(avisosDeAlcance("Cambie el resuelve.", "rehacer_consideraciones"))).toEqual(["resuelve"]);
    expect(ids(avisosDeAlcance("Ajuste la parte resolutiva.", "rehacer_consideraciones"))).toEqual(["resuelve"]);
    expect(ids(avisosDeAlcance("Agregue un numeral.", "rehacer_consideraciones"))).toEqual(["resuelve"]);
  });

  it("los textos de los avisos sugieren la otra opción sin ordenarla", () => {
    const [apertura] = avisosDeAlcance("En los antecedentes falta la fecha.", "rehacer_consideraciones");
    expect(apertura?.texto).toContain("solo cambia la sección V");
    expect(apertura?.texto).toContain("elija «Rehacer la apertura»");
    const [consideraciones] = avisosDeAlcance("En inmediatez cite la regla.", "rehacer_apertura");
    expect(consideraciones?.texto).toContain("cambia las secciones I a IV");
    expect(consideraciones?.texto).toContain("sin su instrucción");
    expect(consideraciones?.texto).toContain("elija «Rehacer las consideraciones»");
  });
});
