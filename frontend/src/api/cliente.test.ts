import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ErrorApi, esCasoNoEncontrado, MENSAJE_RED } from "./cliente";

afterEach(() => {
  vi.unstubAllGlobals();
});

const respuesta = (cuerpo: unknown, status: number) =>
  new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } });

describe("peticion: errores de red", () => {
  it("convierte el TypeError de fetch en un ErrorApi con estado 0 y un mensaje claro", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await api.get("/api/casos").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ErrorApi);
    expect(error).toMatchObject({ estado: 0, detalle: null, message: MENSAJE_RED });
    expect(MENSAJE_RED).not.toMatch(/fetch/i);
  });

  it("no toca los abortos de la petición", async () => {
    const aborto = new DOMException("Aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(aborto));
    await expect(api.get("/api/casos")).rejects.toBe(aborto);
  });

  it("deja pasar los demás errores sin cambiarlos", async () => {
    const otro = new RangeError("raro");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(otro));
    await expect(api.get("/api/casos")).rejects.toBe(otro);
  });

  it("sigue convirtiendo las respuestas de error en ErrorApi con su detalle", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta({ detail: "Caso no encontrado." }, 404)));
    const error = await api.get("/api/casos/x/estado").catch((e: unknown) => e);
    expect(error).toMatchObject({ estado: 404, detalle: "Caso no encontrado.", message: "Caso no encontrado." });
  });
});

describe("esCasoNoEncontrado", () => {
  it("reconoce el 404 del caso, con o sin punto final", () => {
    expect(esCasoNoEncontrado(new ErrorApi(404, "Caso no encontrado.", "Caso no encontrado."))).toBe(true);
    expect(esCasoNoEncontrado(new ErrorApi(404, "Caso no encontrado", "x"))).toBe(true);
  });

  it("no confunde otros 404 ni otros errores", () => {
    expect(esCasoNoEncontrado(new ErrorApi(404, "El borrador aún no existe.", "x"))).toBe(false);
    expect(esCasoNoEncontrado(new ErrorApi(404, null, "x"))).toBe(false);
    expect(esCasoNoEncontrado(new ErrorApi(500, "Caso no encontrado.", "x"))).toBe(false);
    expect(esCasoNoEncontrado(new Error("Caso no encontrado."))).toBe(false);
  });
});
