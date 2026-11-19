import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cargarEstadoServidor, cerrarToast, claveActiva, claveDe, enumerar, errorEstadoServidor, estadoServidor, fechaRelativa, mostrarToast, nombreModelo, plural, pluralizar, porcentaje, proveedorDelCaso, proveedorSinClave, toasts } from "./index";

describe("fechaRelativa", () => {
  const ahora = Date.parse("2026-11-03T12:00:00Z");
  const hace = (segundos: number) => new Date(ahora - segundos * 1000).toISOString();

  it.each([
    [10, "ahora mismo"],
    [90, "hace 2 min"],
    [50 * 60, "hace 50 min"],
    [3 * 3600, "hace 3 h"],
    [30 * 3600, "ayer"],
    [4 * 86400, "hace 4 días"],
  ])("hace %i s -> %s", (segundos, esperado) => {
    expect(fechaRelativa(hace(segundos), ahora)).toBe(esperado);
  });

  it("usa fecha corta para lo antiguo y agrega el año si cambia", () => {
    expect(fechaRelativa("2026-09-15T12:00:00Z", ahora)).toMatch(/^15 de sep/);
    expect(fechaRelativa("2025-09-15T12:00:00Z", ahora)).toContain("2025");
  });

  it("tolera futuro e inválidos", () => {
    expect(fechaRelativa(new Date(ahora + 60000).toISOString(), ahora)).toBe("ahora mismo");
    expect(fechaRelativa("nada", ahora)).toBe("");
  });
});

describe("enumerar", () => {
  it("une con comas y «y»", () => {
    expect(enumerar([])).toBe("");
    expect(enumerar(["a"])).toBe("a");
    expect(enumerar(["a", "b"])).toBe("a y b");
    expect(enumerar(["a", "b", "c"])).toBe("a, b y c");
  });

  it("con límite resume el resto", () => {
    expect(enumerar(["a", "b", "c", "d"], 4)).toBe("a, b, c y d");
    expect(enumerar(["a", "b", "c", "d", "e", "f"], 4)).toBe("a, b, c, d y 2 más");
  });
});

describe("plural y porcentaje", () => {
  it("pluraliza con reglas del español", () => {
    expect(plural(1, "caso")).toBe("1 caso");
    expect(plural(0, "caso")).toBe("0 casos");
    expect(plural(2, "decisión")).toBe("2 decisiones");
    expect(plural(3, "papel")).toBe("3 papeles");
    expect(plural(2, "vez")).toBe("2 veces");
    expect(plural(2, "persona", "personas")).toBe("2 personas");
    expect(pluralizar(1, "página")).toBe("página");
    expect(pluralizar(2, "página")).toBe("páginas");
  });

  it("formatea fracciones con espacio duro antes del signo", () => {
    expect(porcentaje(0.97)).toBe("97 %");
    expect(porcentaje(0.715, 1)).toBe("71,5 %");
    expect(porcentaje(null)).toBe("—");
    expect(porcentaje(Number.NaN)).toBe("—");
  });

  it("da nombre legible al modelo", () => {
    expect(nombreModelo("claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(nombreModelo("gemini-4-argon")).toBe("Gemini 4 Argon");
    expect(nombreModelo("gemini-4-hydrogen")).toBe("Gemini 4 Hydrogen");
    expect(nombreModelo("gemini-3.8-flash")).toBe("Gemini 3.8 Flash");
    expect(nombreModelo("gemini-4-argon-001")).toBe("gemini-4-argon-001");
    expect(nombreModelo("otro")).toBe("otro");
  });
});

describe("toasts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    toasts.value = [];
  });
  afterEach(() => vi.useRealTimers());

  it("se cierran solos tras el plazo", () => {
    mostrarToast("Guardado", { tipo: "ok" });
    expect(toasts.value).toMatchObject([{ texto: "Guardado", tipo: "ok" }]);
    vi.advanceTimersByTime(3600);
    expect(toasts.value).toEqual([]);
  });

  it("los errores persisten hasta cerrarlos", () => {
    const id = mostrarToast("Falló", { tipo: "error" });
    vi.advanceTimersByTime(60000);
    expect(toasts.value).toHaveLength(1);
    cerrarToast(id);
    expect(toasts.value).toEqual([]);
  });

  it("ms 0 deja el aviso fijo y cerrar uno no toca a los demás", () => {
    const a = mostrarToast("A", { ms: 0 });
    mostrarToast("B", { ms: 0 });
    cerrarToast(a);
    expect(toasts.value.map((t) => t.texto)).toEqual(["B"]);
  });
});

describe("estadoServidor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    estadoServidor.value = null;
    errorEstadoServidor.value = false;
  });

  it("carga una sola vez y permite forzar", async () => {
    const cuerpo = { proveedor: "anthropic", api_key: true, gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: ["claude-sonnet-5-5"], modelos_gemini: [], festivos: [] };
    const falso = vi.fn(async () => new Response(JSON.stringify(cuerpo), { status: 200 }));
    vi.stubGlobal("fetch", falso);
    await Promise.all([cargarEstadoServidor(true), cargarEstadoServidor()]);
    expect(estadoServidor.value).toEqual(cuerpo);
    expect(falso).toHaveBeenCalledTimes(1);
    await cargarEstadoServidor();
    expect(falso).toHaveBeenCalledTimes(1);
    await cargarEstadoServidor(true);
    expect(falso).toHaveBeenCalledTimes(2);
  });

  it("la clave activa es la del proveedor elegido", () => {
    const base = { proveedor: "anthropic" as const, api_key: true, gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [], modelos_gemini: [], festivos: [] };
    expect(claveActiva(base)).toBe(true);
    expect(claveActiva({ ...base, proveedor: "gemini" })).toBe(false);
    expect(claveActiva({ ...base, proveedor: "gemini", gemini_key: true, api_key: false })).toBe(true);
    expect(claveDe(base, "gemini")).toBe(false);
  });

  it("dentro de un caso manda el proveedor que resuelve la ejecución, no el del servidor", () => {
    const base = { proveedor: "anthropic" as const, api_key: true, gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [], modelos_gemini: [], festivos: [] };
    expect(proveedorSinClave(base, "gemini")).toBe("gemini");
    expect(proveedorSinClave(base, "anthropic")).toBeNull();
    expect(proveedorSinClave(base, null)).toBeNull();
    expect(proveedorSinClave({ ...base, api_key: false }, undefined)).toBe("anthropic");
    expect(proveedorSinClave({ ...base, api_key: false }, "fake")).toBeNull();
    expect(proveedorSinClave(null, "gemini")).toBeNull();
    expect(proveedorDelCaso({ ...base, proveedor: "gemini" }, "anthropic")).toBe("anthropic");
    expect(proveedorDelCaso({ ...base, proveedor: "gemini" }, "fake")).toBe("gemini");
    expect(proveedorDelCaso({ ...base, proveedor: "gemini" }, null)).toBe("gemini");
  });

  it("marca error y permite reintentar", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    await cargarEstadoServidor(true);
    expect(errorEstadoServidor.value).toBe(true);
    expect(estadoServidor.value).toBeNull();
    const cuerpo = { proveedor: "gemini", api_key: false, gemini_key: true, jev_key: false, modelo: "gemini-4-argon", modelos: [], modelos_gemini: ["gemini-4-argon"], festivos: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(cuerpo), { status: 200 })));
    await cargarEstadoServidor();
    expect(errorEstadoServidor.value).toBe(false);
    expect(estadoServidor.value).toEqual(cuerpo);
  });
});
