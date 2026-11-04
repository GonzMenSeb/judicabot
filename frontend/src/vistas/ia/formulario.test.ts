import { describe, expect, it } from "vitest";
import { ErrorApi, MENSAJE_RED } from "../../api/cliente";
import type { PreferenciasIa } from "../../api/contrato";
import { aCuerpo, aFormulario, igual, leerErrorServidor, validar } from "./formulario";

const prefs: PreferenciasIa = {
  modelo: "claude-sonnet-5-5",
  modelos: ["claude-sonnet-5-5", "claude-opus-5-5"],
  api_key: true,
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
    expect(aCuerpo(f)).toEqual({ modelo: "claude-sonnet-5-5", jev: { modo: "sombra", umbral: 0.87 }, effort: "high", max_tokens: 64000, max_retries: 1 });
    expect(igual(f, aFormulario(prefs))).toBe(true);
    expect(igual({ ...f, maxTokens: " 64000 " }, f)).toBe(true);
    expect(igual({ ...f, maxRetries: "2" }, f)).toBe(false);
  });

  it("valida rangos, enteros y modelos desconocidos", () => {
    const f = aFormulario(prefs);
    expect(validar(f, prefs.modelos)).toEqual({});
    expect(validar({ ...f, maxTokens: "64001" }, prefs.modelos).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxTokens: "12,5" }, prefs.modelos).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxTokens: "" }, prefs.modelos).max_tokens).toBeTruthy();
    expect(validar({ ...f, maxRetries: "-1" }, prefs.modelos).max_retries).toBeTruthy();
    expect(validar({ ...f, maxRetries: "0" }, prefs.modelos).max_retries).toBeUndefined();
    expect(validar({ ...f, maxRetries: "6" }, prefs.modelos).max_retries).toBeTruthy();
    expect(validar({ ...f, modelo: "otro" }, prefs.modelos).modelo).toBeTruthy();
    expect(validar({ ...f, umbral: 101 }, prefs.modelos).umbral).toBeTruthy();
  });

  it("interpreta los errores del servidor", () => {
    const campos = leerErrorServidor(new ErrorApi(422, { errores: [{ campo: "jev.umbral", mensaje: "debe ser un número finito." }] }, "Error 422"), "x");
    expect(campos).toEqual({ campos: { umbral: "Debe ser un número finito." }, generales: [] });
    expect(leerErrorServidor(new ErrorApi(422, "Clave inválida.", "Clave inválida."), "x").generales).toEqual(["Clave inválida."]);
    expect(leerErrorServidor(new ErrorApi(502, null, "Error 502"), "x").generales[0]).toMatch(/servidor/);
    expect(leerErrorServidor(new ErrorApi(400, null, "Error 400"), "No se pudo.").generales).toEqual(["No se pudo."]);
    expect(leerErrorServidor(new TypeError("Failed to fetch"), "Sin conexión.").generales).toEqual(["Sin conexión."]);
    expect(leerErrorServidor(new ErrorApi(0, null, MENSAJE_RED), "x").generales).toEqual([MENSAJE_RED]);
  });
});
