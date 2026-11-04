import { act, render, screen } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rutas } from "./Rutas";
import { coincidir, navegar, ruta } from "./router";

vi.mock("../vistas/inicio", () => ({ default: () => <div data-vista="inicio"><h1>Inicio</h1></div> }));
vi.mock("../vistas/decision", () => ({ default: ({ caso }: { caso?: string }) => <div data-vista="decision"><h1>Decisión</h1><p>{caso}</p></div> }));
vi.mock("../vistas/borrador", () => ({ default: () => <div data-vista="borrador"><h1>Borrador</h1></div> }));

describe("coincidir", () => {
  it("resuelve las rutas declaradas", () => {
    expect(coincidir("")).toEqual({ vista: "inicio", params: {} });
    expect(coincidir("#/")).toEqual({ vista: "inicio", params: {} });
    expect(coincidir("#/segunda")).toEqual({ vista: "casos", params: {} });
    expect(coincidir("#/segunda/")).toEqual({ vista: "casos", params: {} });
    expect(coincidir("#/formato")).toEqual({ vista: "formato", params: {} });
    expect(coincidir("#/ia")).toEqual({ vista: "ia", params: {} });
  });

  it.each(["documentos", "proceso", "borrador", "decision", "fallo"])("resuelve la etapa %s de un caso", (etapa) => {
    expect(coincidir(`#/segunda/caso-1/${etapa}`)).toEqual({ vista: etapa, params: { caso: "caso-1" } });
  });

  it("decodifica el caso y tolera codificaciones inválidas", () => {
    expect(coincidir("#/segunda/a%20b/fallo").params.caso).toBe("a b");
    expect(coincidir("#/segunda/%E0%A4%A/fallo").params.caso).toBe("%E0%A4%A");
  });

  it.each(["#/nada", "#/segunda/caso-1", "#/segunda/caso-1/otra", "#/segunda/caso-1/fallo/extra", "#/formato/x", "#//"])(
    "vuelve al inicio con %s",
    (hash) => {
      expect(coincidir(hash).vista).toBe("inicio");
    },
  );
});

describe("navegación", () => {
  beforeEach(() => {
    location.hash = "";
    ruta.value = coincidir("");
  });

  it("actualiza la ruta al cambiar el hash", async () => {
    const cambio = new Promise((r) => addEventListener("hashchange", r, { once: true }));
    navegar("#/segunda/caso-9/borrador");
    await cambio;
    expect(ruta.value).toEqual({ vista: "borrador", params: { caso: "caso-9" } });
  });

  it("carga de forma perezosa la vista de la ruta", async () => {
    render(<Rutas />);
    expect(await screen.findByRole("heading", { name: "Inicio" })).toBeTruthy();

    await act(async () => {
      ruta.value = coincidir("#/segunda/caso-9/decision");
    });
    expect(await screen.findByRole("heading", { name: "Decisión" })).toBeTruthy();
    expect(screen.getByText("caso-9")).toBeTruthy();
  });
});
