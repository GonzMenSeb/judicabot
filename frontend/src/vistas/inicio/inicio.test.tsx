import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toasts } from "../../estado";
import { consulta } from "../../rutas";
import { Toasts } from "../../ui";
import Casos from "../casos";
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
  toasts.value = [];
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

  it("al eliminar el último caso «Mi trabajo» desaparece, el foco pasa al contenido y Deshacer lo trae de vuelta", async () => {
    const quintero = casosMock.find((c) => c.id === "quintero-bedoya")!;
    const entrada = "quintero-bedoya@20261117T150000000000Z";
    let eliminado = false;
    simularFetch({
      "GET /api/casos": () => json(eliminado ? [] : [quintero]),
      "GET /api/formato": () => json(formato),
      "DELETE /api/casos/quintero-bedoya": () => {
        eliminado = true;
        return json({ id: "quintero-bedoya", papelera: entrada });
      },
      [`POST /api/papelera/${encodeURIComponent(entrada)}/restaurar`]: () => {
        eliminado = false;
        return json({ id: "quintero-bedoya" });
      },
    });
    render(
      <>
        <main id="contenido" tabIndex={-1}>
          <Inicio />
        </main>
        <Toasts />
      </>,
    );
    const seccion = await screen.findByRole("region", { name: "Mi trabajo" });
    expect(screen.getByText("1 espera su decisión")).toBeTruthy();
    fireEvent.click(within(seccion).getByRole("button", { name: `Eliminar: ${quintero.nombre}` }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "¿Eliminar este caso?" })).getByRole("button", { name: "Eliminar caso" }));
    await waitFor(() => expect(document.activeElement?.id).toBe("contenido"));
    expect(screen.queryByRole("region", { name: "Mi trabajo" })).toBeNull();
    expect(screen.getByText("0 casos abiertos")).toBeTruthy();
    expect(screen.queryByText(/su decisión/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(await screen.findByRole("region", { name: "Mi trabajo" })).toBeTruthy();
    expect(screen.getByText("1 espera su decisión")).toBeTruthy();
    expect(screen.getByText(`Se restauró «${quintero.nombre}».`)).toBeTruthy();
  });

  it("Deshacer después de pasar a la página del proceso recarga esa lista, no la de Inicio", async () => {
    const quintero = casosMock.find((c) => c.id === "quintero-bedoya")!;
    const entrada = "quintero-bedoya@20261117T150000000000Z";
    let eliminado = false;
    const llamadas = simularFetch({
      "GET /api/casos": () => json(eliminado ? casosMock.filter((c) => c !== quintero) : casosMock),
      "GET /api/formato": () => json(formato),
      "DELETE /api/casos/quintero-bedoya": () => {
        eliminado = true;
        return json({ id: "quintero-bedoya", papelera: entrada });
      },
      [`POST /api/papelera/${encodeURIComponent(entrada)}/restaurar`]: () => {
        eliminado = false;
        return json({ id: "quintero-bedoya" });
      },
    });
    const { rerender } = render(
      <>
        <main id="contenido" tabIndex={-1}>
          <Inicio />
        </main>
        <Toasts />
      </>,
    );
    fireEvent.click(await screen.findByRole("button", { name: `Eliminar: ${quintero.nombre}` }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "¿Eliminar este caso?" })).getByRole("button", { name: "Eliminar caso" }));
    await screen.findByRole("button", { name: "Deshacer" });

    rerender(
      <>
        <main id="contenido" tabIndex={-1}>
          <Casos />
        </main>
        <Toasts />
      </>,
    );
    const lista = await screen.findByRole("region", { name: "Casos" });
    await within(lista).findByRole("link", { name: /Arango Londoño/ });
    expect(within(lista).queryByText(quintero.nombre)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(await within(lista).findByText(quintero.nombre)).toBeTruthy();
    expect(screen.getByText(`Se restauró «${quintero.nombre}».`)).toBeTruthy();
    expect(llamadas.filter((l) => l.ruta === "/api/casos")).toHaveLength(3);
  });

  it("una recarga que salió antes de eliminar no devuelve el caso eliminado a «Mi trabajo»", async () => {
    const quintero = casosMock.find((c) => c.id === "quintero-bedoya")!;
    const cardenas = casosMock.find((c) => c.id === "cardenas-ospina")!;
    const entrada = "quintero-bedoya@20261117T150000000000Z";
    let soltar: (r: Response) => void = () => undefined;
    let cargas = 0;
    simularFetch({
      "GET /api/casos": () => (++cargas === 2 ? new Promise<Response>((ok) => (soltar = ok)) : json(casosMock)),
      "GET /api/formato": () => json(formato),
      "DELETE /api/casos/quintero-bedoya": () => json({ id: "quintero-bedoya", papelera: entrada }),
      "DELETE /api/casos/cardenas-ospina": () => json({ id: "cardenas-ospina", papelera: "cardenas-ospina@20261117T150001000000Z" }),
      [`POST /api/papelera/${encodeURIComponent(entrada)}/restaurar`]: () => json({ id: "quintero-bedoya" }),
    });
    render(
      <>
        <main id="contenido" tabIndex={-1}>
          <Inicio />
        </main>
        <Toasts />
      </>,
    );
    const seccion = await screen.findByRole("region", { name: "Mi trabajo" });
    const eliminar = async (nombre: string) => {
      fireEvent.click(await within(seccion).findByRole("button", { name: `Eliminar: ${nombre}` }));
      fireEvent.click(within(screen.getByRole("dialog", { name: "¿Eliminar este caso?" })).getByRole("button", { name: "Eliminar caso" }));
      await waitFor(() => expect(within(seccion).queryByText(nombre)).toBeNull());
    };
    await eliminar(quintero.nombre);
    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(cargas).toBe(2));
    await eliminar(cardenas.nombre);

    await act(async () => soltar(json(casosMock)));
    expect(await within(seccion).findByText(quintero.nombre)).toBeTruthy();
    expect(within(seccion).queryByText(cardenas.nombre)).toBeNull();
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
