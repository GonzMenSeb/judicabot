import { describe, expect, it } from "vitest";
import type { Evento } from "../../api/contrato";
import { agrupar, duracionEventos, estadoEtapas, formatearTiempo, marcaDe, mensajeError } from "./modelo";

const ev = (n: number, etapa: Evento["etapa"], tipo: Evento["tipo"] = "lee", segundos = n): Evento => ({
  n,
  t: new Date(Date.UTC(2026, 10, 3, 12, 0, segundos)).toISOString(),
  etapa,
  tipo,
  texto: `evento ${n}`,
  datos: null,
});

describe("agrupar", () => {
  it("separa por etapa y toma como activa la de la última etapa con evento", () => {
    const { porEtapa, activa } = agrupar([ev(1, "ingesta"), ev(2, "ingesta"), ev(3, "apertura")]);
    expect(porEtapa.ingesta.map((e) => e.n)).toEqual([1, 2]);
    expect(porEtapa.apertura.map((e) => e.n)).toEqual([3]);
    expect(activa).toBe("apertura");
  });

  it("incluye los eventos del sistema en la etapa en curso", () => {
    const { porEtapa, activa } = agrupar([ev(1, "ingesta"), ev(2, "sistema", "sistema"), ev(3, "apertura"), ev(4, "sistema", "sistema")]);
    expect(porEtapa.ingesta.map((e) => e.n)).toEqual([1, 2]);
    expect(porEtapa.apertura.map((e) => e.n)).toEqual([3, 4]);
    expect(activa).toBe("apertura");
  });

  it("asigna los eventos del sistema previos a la primera etapa con evento a esa etapa", () => {
    const { porEtapa, huerfanos } = agrupar([ev(1, "sistema", "sistema"), ev(2, "caso_concreto")]);
    expect(porEtapa.caso_concreto.map((e) => e.n)).toEqual([1, 2]);
    expect(huerfanos).toEqual([]);
  });

  it("deja huérfanos los eventos del sistema si aún no hay etapa", () => {
    const { huerfanos, activa } = agrupar([ev(1, "sistema", "sistema")]);
    expect(huerfanos).toHaveLength(1);
    expect(activa).toBeNull();
  });
});

describe("estadoEtapas", () => {
  it("marca hechas las anteriores, en curso la activa y pendientes las siguientes", () => {
    expect(estadoEtapas("consideraciones", null)).toEqual({
      ingesta: "hecho",
      apertura: "hecho",
      consideraciones: "actual",
      verificacion: "espera",
      caso_concreto: "espera",
      documentos: "espera",
    });
  });

  it("completa la activa al terminar y la marca con error si falló", () => {
    expect(estadoEtapas("apertura", { estado: "terminado", error: null }).apertura).toBe("hecho");
    expect(estadoEtapas("apertura", { estado: "error", error: "x" }).apertura).toBe("error");
  });

  it("deja todo pendiente sin eventos", () => {
    expect(Object.values(estadoEtapas(null, null)).every((e) => e === "espera")).toBe(true);
  });
});

describe("tiempos", () => {
  it("formatea mm:ss", () => {
    expect(formatearTiempo(0)).toBe("00:00");
    expect(formatearTiempo(61_500)).toBe("01:01");
    expect(formatearTiempo(-5)).toBe("00:00");
  });

  it("calcula la marca relativa al primer evento y la duración", () => {
    const a = ev(1, "ingesta", "lee", 10);
    const b = ev(2, "ingesta", "lee", 75);
    expect(marcaDe(b, Date.parse(a.t))).toBe("01:05");
    expect(marcaDe(b, Number.NaN)).toBe("");
    expect(duracionEventos([a, b])).toBe(65_000);
    expect(duracionEventos([])).toBe(0);
  });
});

describe("mensajeError", () => {
  it("prefiere el error del fin, luego el último evento de error", () => {
    const e = [ev(1, "ingesta", "error")];
    expect(mensajeError({ estado: "error", error: "Falló la cita" }, e)).toBe("Falló la cita");
    expect(mensajeError({ estado: "error", error: null }, e)).toBe("evento 1");
    expect(mensajeError(null, [])).toBe("La ejecución se detuvo antes de terminar.");
  });
});
