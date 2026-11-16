import { describe, expect, it } from "vitest";
import { ErrorApi, MENSAJE_RED } from "../../api/cliente";
import type { PreferenciasIa } from "../../api/contrato";
import { aCuerpo, aFormulario, igual, leerErrorServidor, nivelAjustado, validar } from "./formulario";

const prefs: PreferenciasIa = {
  proveedor: "anthropic",
  modelo: "claude-sonnet-5-5",
  modelos: ["claude-sonnet-5-5", "claude-opus-5-5"],
  gemini: { modelo: "gemini-4-hydrogen", razonamiento: "xhigh" },
  modelos_gemini: ["gemini-4-argon", "gemini-4-hydrogen"],
  razonamientos_gemini: { "gemini-4-argon": ["low", "medium", "high"], "gemini-4-hydrogen": ["low", "medium", "high", "xhigh"] },
  api_key: true,
  gemini_key: true,
  jev_key: false,
  jev: { modo: "sombra", umbral: 0.87 },
  effort: "high",
  max_tokens: 64000,
  max_retries: 1,
};

describe("formulario", () => {
  it("convierte ida y vuelta sin perder el umbral", () => {
    const f = aFormulario(prefs);
    expect(f.umbral).toBe(87);
    expect(aCuerpo(f, prefs)).toEqual({
      modelo: "claude-sonnet-5-5",
      effort: "high",
      gemini: { modelo: "gemini-4-hydrogen", razonamiento: "xhigh" },
      jev: { modo: "sombra", umbral: 0.87 },
      max_tokens: 64000,
      max_retries: 1,
    });
    expect(igual(f, aFormulario(prefs))).toBe(true);
    expect(igual({ ...f, maxTokens: " 64000 " }, f)).toBe(true);
    expect(igual({ ...f, maxRetries: "2" }, f)).toBe(false);
    expect(igual({ ...f, proveedor: "gemini" }, f)).toBe(false);
    expect(igual({ ...f, razonamiento: "low" }, f)).toBe(false);
  });

  it("solo envía las opciones del proveedor que tiene clave y modelos", () => {
    const f = aFormulario(prefs);
    expect(aCuerpo(f, { ...prefs, gemini_key: false })).not.toHaveProperty("gemini");
    const sinAnthropic = aCuerpo(f, { ...prefs, api_key: false });
    expect(sinAnthropic).not.toHaveProperty("modelo");
    expect(sinAnthropic).not.toHaveProperty("effort");
    expect(aCuerpo(f, { ...prefs, modelos_gemini: [] })).not.toHaveProperty("gemini");
    expect(aCuerpo(f, { ...prefs, api_key: false, gemini_key: false })).toEqual({
      jev: { modo: "sombra", umbral: 0.87 },
      max_tokens: 64000,
      max_retries: 1,
    });
  });

  it("solo envía el proveedor cuando el usuario lo cambió", () => {
    const f = aFormulario(prefs);
    expect(aCuerpo(f, prefs)).not.toHaveProperty("proveedor");
    expect(aCuerpo({ ...f, proveedor: "gemini" }, prefs)).toMatchObject({ proveedor: "gemini" });
    expect(aCuerpo({ ...f, proveedor: "gemini" }, { ...prefs, proveedor: "gemini" })).not.toHaveProperty("proveedor");
    expect(aCuerpo({ ...f, proveedor: "anthropic" }, { ...prefs, proveedor: "gemini" })).toMatchObject({ proveedor: "anthropic" });
  });

  it("valida rangos, enteros y modelos desconocidos", () => {
    const f = aFormulario(prefs);
    expect(validar(f, prefs)).toEqual({});
    expect(validar({ ...f, maxTokens: "64001" }, prefs).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxTokens: "12,5" }, prefs).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxTokens: "" }, prefs).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxRetries: "-1" }, prefs).max_retries).toBeTruthy();
    expect(validar({ ...f, maxRetries: "0" }, prefs).max_retries).toBeUndefined();
    expect(validar({ ...f, maxRetries: "6" }, prefs).max_retries).toBeTruthy();
    expect(validar({ ...f, modelo: "otro" }, prefs).modelo).toBeTruthy();
    expect(validar({ ...f, umbral: 101 }, prefs).umbral).toBeTruthy();
  });

  it("valida el modelo y el nivel de Gemini solo con su clave", () => {
    const f = aFormulario(prefs);
    expect(validar({ ...f, modeloGemini: "gemini-4-carbon" }, prefs).gemini_modelo).toBe("Elija uno de los modelos disponibles.");
    expect(validar({ ...f, modeloGemini: "gemini-4-argon" }, prefs).razonamiento).toBe("Elija un nivel que admita el modelo.");
    expect(validar({ ...f, modeloGemini: "gemini-4-argon", razonamiento: "high" }, prefs)).toEqual({});
    expect(validar({ ...f, modeloGemini: "gemini-4-carbon" }, { ...prefs, gemini_key: false })).toEqual({});
    expect(validar({ ...f, modelo: "otro" }, { ...prefs, api_key: false })).toEqual({});
  });

  it("ajusta el nivel al cambiar a un modelo que no lo admite", () => {
    expect(nivelAjustado(prefs, "gemini-4-argon", "xhigh")).toBe("high");
    expect(nivelAjustado(prefs, "gemini-4-argon", "low")).toBe("low");
    expect(nivelAjustado(prefs, "gemini-4-hydrogen", "xhigh")).toBe("xhigh");
    expect(nivelAjustado({ ...prefs, razonamientos_gemini: { x: ["low", "medium"] } }, "x", "xhigh")).toBe("medium");
  });

  it("interpreta los errores del servidor", () => {
    const campos = leerErrorServidor(new ErrorApi(422, { errores: [{ campo: "jev.umbral", mensaje: "debe ser un número finito." }] }, "Error 422"), "x");
    expect(campos).toEqual({ campos: { umbral: "Debe ser un número finito." }, generales: [] });
    const gemini = leerErrorServidor(
      new ErrorApi(422, { errores: [{ campo: "gemini.razonamiento", mensaje: "con gemini-4-argon debe ser uno de: low, medium o high." }, { campo: "proveedor", mensaje: "no." }] }, "Error 422"),
      "x",
    );
    expect(gemini.campos).toEqual({ razonamiento: "Con gemini-4-argon debe ser uno de: low, medium o high.", proveedor: "No." });
    expect(leerErrorServidor(new ErrorApi(422, { errores: [{ campo: "gemini.modelo", mensaje: "m." }] }, "Error 422"), "x").campos).toEqual({ gemini_modelo: "M." });
    expect(leerErrorServidor(new ErrorApi(422, "Clave inválida.", "Clave inválida."), "x").generales).toEqual(["Clave inválida."]);
    expect(leerErrorServidor(new ErrorApi(502, null, "Error 502"), "x").generales[0]).toMatch(/servidor/);
    expect(leerErrorServidor(new ErrorApi(400, null, "Error 400"), "No se pudo.").generales).toEqual(["No se pudo."]);
    expect(leerErrorServidor(new TypeError("Failed to fetch"), "Sin conexión.").generales).toEqual(["Sin conexión."]);
    expect(leerErrorServidor(new ErrorApi(0, null, MENSAJE_RED), "x").generales).toEqual([MENSAJE_RED]);
  });
});
