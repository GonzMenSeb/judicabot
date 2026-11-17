import { fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consulta } from "../../rutas";
import { casosMock } from "../casos/mock";
import { json, simularFetch } from "../casos/utilesPrueba";
import Inicio from "./index";

beforeEach(() => {
  history.replaceState(null, "", "/");
  consulta.value = "";
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const formato = { campos: [], valores: { nombre_cuerpo: "Juzgado Tercero Penal del Circuito" }, plantilla_gen: "B", documentos: [] };

describe("Inicio", () => {
  it("ofrece el proceso de segunda instancia como enlace y los demás como próximamente", async () => {
    simularFetch({ "GET /api/casos": () => json(casosMock), "GET /api/formato": () => json(formato) });
    render(<Inicio />);
    expect(screen.getByRole("heading", { level: 1, name: "Elige el proceso a realizar" })).toBeTruthy();

    const activo = screen.getByRole("link", { name: "Fallo de tutela de segunda instancia" });
    expect(activo.getAttribute("href")).toBe("#/segunda");

    for (const titulo of ["Fallo de tutela de primera instancia", "Incidente de desacato", "Penal"]) {
      const tarjeta = screen.getByRole("group", { name: titulo });
      expect(tarjeta.getAttribute("aria-disabled")).toBe("true");
      expect(tarjeta.hasAttribute("tabindex")).toBe(false);
      expect(within(tarjeta).queryByRole("link")).toBeNull();
      expect(within(tarjeta).queryByRole("button")).toBeNull();
      expect(within(tarjeta).getByText("Próximamente")).toBeTruthy();
    }
    expect(screen.getAllByRole("link")).toEqual(expect.arrayContaining([activo]));
    expect(await screen.findByText("1 espera su decisión")).toBeTruthy();
    expect(screen.getByText("5 casos abiertos")).toBeTruthy();
  });

  it("muestra el despacho, la fecha y «Mi trabajo» con los casos abiertos, lo vencido y lo que vence hoy arriba", async () => {
    simularFetch({ "GET /api/casos": () => json(casosMock), "GET /api/formato": () => json(formato) });
    render(<Inicio />);
    expect(await screen.findByText(/^Juzgado Tercero Penal del Circuito, /)).toBeTruthy();
    const seccion = await screen.findByRole("region", { name: "Mi trabajo" });
    const titulos = within(seccion)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(titulos).toEqual([
      "Cárdenas Ospina c. Aseguradora Montaña Azul",
      "Arango Londoño c. EPS Ceiba Salud",
      "Quintero Bedoya c. EPS Horizonte Salud",
      "Zapata Henao c. EPS Sendero",
      "Restrepo Gil c. Fondo Pensional Altamira",
    ]);
    expect(within(seccion).getByRole("link", { name: /^Decidir:/ }).getAttribute("href")).toBe("#/segunda/quintero-bedoya/borrador");
    expect(within(seccion).getByRole("searchbox", { name: "Buscar casos" })).toBeTruthy();
    expect(within(seccion).getByRole("button", { name: /^Juzgado de 1ª inst\./ })).toBeTruthy();
    expect(within(seccion).queryByRole("heading", { level: 3, name: /Por decidir/ })).toBeNull();
  });

  it("sigue funcionando sin el formato y sin casos", async () => {
    simularFetch({ "GET /api/casos": () => json([]), "GET /api/formato": () => json({ detail: "x" }, 500) });
    render(<Inicio />);
    expect(await screen.findByText("0 casos abiertos")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Mi trabajo" })).toBeNull();
    expect(screen.queryByText(/su decisión/)).toBeNull();
  });

  it("avisa si no pudo cargar los casos y permite reintentar", async () => {
    let intento = 0;
    simularFetch({
      "GET /api/casos": () => {
        intento += 1;
        if (intento === 1) throw new TypeError("Failed to fetch");
        return json(casosMock);
      },
      "GET /api/formato": () => json(formato),
    });
    render(<Inicio />);
    expect((await screen.findByRole("status")).textContent).toMatch(/No se pudo cargar el resumen de los casos/);
    expect(screen.getByRole("link", { name: "Fallo de tutela de segunda instancia" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("5 casos abiertos")).toBeTruthy();
    expect(screen.queryByText(/No se pudo cargar el resumen/)).toBeNull();
  });
});
