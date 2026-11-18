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

describe("peticion: detalle con objeto", () => {
  it("un 422 con detail { mensaje, errores } deja message en el texto de mensaje y conserva el objeto", async () => {
    const detail = { mensaje: "Su decisión no se aplicó: x.", errores: [] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta({ detail }, 422)));
    const error = await api.post("/api/casos/x/run", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ErrorApi);
    expect(error).toMatchObject({ estado: 422, detalle: detail, message: "Su decisión no se aplicó: x." });
  });

  it.each([{ errores: [] }, { mensaje: "   ", errores: [] }, { mensaje: 4 }])(
    "sin un mensaje de texto útil en %j sigue siendo «Error 422»",
    async (detail) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta({ detail }, 422)));
      const error = await api.post("/api/casos/x/run", {}).catch((e: unknown) => e);
      expect(error).toMatchObject({ estado: 422, detalle: detail, message: "Error 422" });
    },
  );
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
