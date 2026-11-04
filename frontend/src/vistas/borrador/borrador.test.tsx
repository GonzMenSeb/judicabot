import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jobActual } from "../../estado";
import Borrador from "./index";
import { CASO_MOCK_BORRADOR, ESTADO_BORRADOR, VISTA_BORRADOR } from "./mock";
import type { EstadoCaso } from "./tipos";

const CASO = CASO_MOCK_BORRADOR;

interface Respuestas {
  vista?: unknown | number;
  estado?: unknown | number;
  run?: unknown | number;
}

class Falla {
  constructor(
    readonly estado: number,
    readonly detail: string,
  ) {}
}

function responder(cuerpo: unknown | number): Response {
  if (cuerpo instanceof Falla) {
    return new Response(JSON.stringify({ detail: cuerpo.detail }), { status: cuerpo.estado, headers: { "Content-Type": "application/json" } });
  }
  if (typeof cuerpo === "number") {
    return new Response(JSON.stringify({ detail: cuerpo === 409 ? "Ya hay una ejecución en curso para este caso." : "Falla" }), {
      status: cuerpo,
      headers: { "Content-Type": "application/json" },
    });
  }
  return new Response(JSON.stringify(cuerpo), { status: 200, headers: { "Content-Type": "application/json" } });
}

function simularRed({ vista = VISTA_BORRADOR, estado = ESTADO_BORRADOR, run = { job_id: "j-1" } }: Respuestas = {}) {
  const llamadas: { url: string; metodo: string; cuerpo: unknown }[] = [];
  const falso = vi.fn(async (url: string, init?: RequestInit) => {
    const metodo = init?.method ?? "GET";
    llamadas.push({ url, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith("/vista/borrador")) return responder(vista);
    if (url.endsWith("/estado")) return responder(estado);
    if (url.endsWith("/run")) return responder(run);
    return responder(404);
  });
  vi.stubGlobal("fetch", falso);
  return llamadas;
}

const conEstado = (estado: EstadoCaso["estado"], extra: Partial<EstadoCaso> = {}): EstadoCaso => ({
  ...ESTADO_BORRADOR,
  estado,
  ...extra,
});

async function abrir() {
  render(<Borrador caso={CASO} />);
  await screen.findByRole("heading", { level: 3, name: /ASUNTO/ });
}

beforeEach(() => {
  location.hash = "";
  jobActual.value = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Borrador con datos", () => {
  it("pinta cabecera, hoja con bloques, tabla agrupada y citas por estado", async () => {
    simularRed();
    await abrir();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Marta Inés Quintero Bedoya c. EPS Horizonte Salud S.A.S.");
    expect(screen.getByText(/Radicado 05001 40 88 009 2026 00412 01/)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "II. ANTECEDENTES DEL CASO" })).toBeTruthy();
    const hoja = screen.getByRole("article", { name: /Borrador del fallo/ });
    expect(hoja.querySelectorAll("table.bor-tabla").length).toBe(2);
    expect(hoja.querySelectorAll("ul.bor-lista li").length).toBe(1);
    const t760 = within(hoja).getByRole("button", { name: /sentencia T-760 de 2008/ });
    expect(t760.classList.contains("verificada")).toBe(true);
    expect(within(hoja).getByRole("button", { name: /SU-508/ }).classList.contains("revisar")).toBe(true);
    expect(within(hoja).getByRole("button", { name: /T-999/ }).classList.contains("rechazada")).toBe(true);
    expect(t760.textContent).toContain("Verificada");
  });

  it("muestra el texto del expediente como texto y no como HTML", async () => {
    const vista = structuredClone(VISTA_BORRADOR);
    const bloque = vista.paginas[0]?.bloques.find((b) => b.id === "asunto-1");
    if (!bloque) throw new Error("falta el bloque");
    bloque.segmentos = [{ texto: "<img src=x onerror=alert(1)><b>hola</b>" }];
    simularRed({ vista });
    await abrir();
    expect(screen.getByText("<img src=x onerror=alert(1)><b>hola</b>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("arma el riel con citas y alertas reales y el índice de secciones", async () => {
    simularRed();
    await abrir();
    const revisar = screen.getByRole("heading", { name: "Qué conviene revisar" }).closest("section") as HTMLElement;
    expect(within(revisar).getByText("1 verificada")).toBeTruthy();
    expect(within(revisar).getByText("1 con alerta")).toBeTruthy();
    expect(within(revisar).getByText("1 no verificada")).toBeTruthy();
    expect(within(revisar).getByText("Cita no verificada")).toBeTruthy();
    expect(within(revisar).getByText(/El documento 009.pdf tiene 2 páginas sin texto/)).toBeTruthy();
    expect(within(revisar).queryByText(/^ALERTA:/)).toBeNull();
    const indice = screen.getByRole("heading", { name: "Secciones" }).closest("section") as HTMLElement;
    expect(within(indice).getByRole("button", { name: "V. Consideraciones" })).toBeTruthy();
    expect(within(indice).getByRole("button", { name: "El mínimo vital" }).classList.contains("sub-i")).toBe(true);
  });

  it("compara el borrador con Jev en una tabla de tres columnas", async () => {
    simularRed();
    await abrir();
    const tarjeta = screen.getByRole("heading", { name: "Segunda lectura de Jev" }).closest("section") as HTMLElement;
    expect(within(tarjeta).getByRole("columnheader", { name: "El borrador dice" })).toBeTruthy();
    expect(within(tarjeta).getByRole("columnheader", { name: "Jev lee en el fallo" })).toBeTruthy();
    expect(within(tarjeta).getByRole("columnheader", { name: "Coincide" })).toBeTruthy();
    const sentido = within(tarjeta).getByRole("row", { name: /Sentido del fallo/ });
    expect(within(sentido).getByText("Declaró improcedente la acción de tutela")).toBeTruthy();
    expect(within(sentido).getByText("Niega el amparo")).toBeTruthy();
    expect(within(sentido).getByText(/Difiere/)).toBeTruthy();
    const rol = within(tarjeta).getByRole("row", { name: /Quién impugna/ });
    expect(within(rol).getByText(/Coincide/)).toBeTruthy();
    expect(within(tarjeta).getByText(/revise esa frase del borrador/)).toBeTruthy();
  });

  it("no muestra la tarjeta de Jev si no hay lecturas", async () => {
    const estado = structuredClone(ESTADO_BORRADOR);
    if (estado.resumen) estado.resumen.jev_metadatos = null;
    simularRed({ estado });
    await abrir();
    expect(screen.queryByRole("heading", { name: "Segunda lectura de Jev" })).toBeNull();
  });
});

describe("Borrador con fallos", () => {
  it("explica que el borrador no está listo si la vista da 404", async () => {
    simularRed({ vista: 404 });
    render(<Borrador caso={CASO} />);
    expect(await screen.findByText("El borrador aún no está listo")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ver el proceso" }).getAttribute("href")).toBe(`#/segunda/${CASO}/proceso`);
  });

  it("distingue el borrador que aún no existe del caso que no existe", async () => {
    simularRed({ vista: new Falla(404, "El borrador aún no existe.") });
    render(<Borrador caso={CASO} />);
    expect(await screen.findByText("El borrador aún no está listo")).toBeTruthy();
    expect(screen.queryByText("No se encontró el caso")).toBeNull();
  });

  it("dice que el caso no existe si la vista responde «Caso no encontrado»", async () => {
    simularRed({ vista: new Falla(404, "Caso no encontrado."), estado: new Falla(404, "Caso no encontrado.") });
    render(<Borrador caso={CASO} />);
    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
    expect(screen.queryByText("El borrador aún no está listo")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  it("dice que el caso no existe si /estado da 404 aunque la vista no diga nada del caso", async () => {
    simularRed({ vista: new Falla(404, "Vista no encontrada."), estado: new Falla(404, "Caso no encontrado.") });
    render(<Borrador caso={CASO} />);
    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.queryByText("El borrador aún no está listo")).toBeNull();
  });

  it("ofrece reintentar ante un error de la API", async () => {
    const llamadas = simularRed({ vista: 500 });
    render(<Borrador caso={CASO} />);
    expect(await screen.findByText("No se pudo cargar el borrador")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.url.endsWith("/vista/borrador")).length).toBe(2));
  });

  it("sigue mostrando el documento si falla /estado", async () => {
    simularRed({ estado: 500 });
    await abrir();
    expect(screen.getByText(/No se pudieron leer las alertas del caso/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("heading", { name: "Segunda lectura de Jev" })).toBeNull();
  });
});

describe("Borrador interacción", () => {
  it("abre el detalle de una cita, enfoca su título y devuelve el foco al cerrar", async () => {
    simularRed();
    await abrir();
    const cita = screen.getByRole("button", { name: /SU-508/ });
    cita.focus();
    fireEvent.click(cita);
    const panel = await screen.findByRole("region", { name: "sentencia SU-508 de 2020" });
    expect(within(panel).getByText("Con alerta", { selector: ".chip" })).toBeTruthy();
    expect(within(panel).getAllByText(/71\s*%/).length).toBeGreaterThan(0);
    expect(within(panel).getByText(/Compare con la relatoría/)).toBeTruthy();
    expect(cita.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(within(panel).getByRole("heading")));
    fireEvent.click(within(panel).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("region", { name: "sentencia SU-508 de 2020" })).toBeNull();
    expect(document.activeElement).toBe(cita);
  });

  it("selecciona la cita desde la lista de revisión", async () => {
    simularRed();
    await abrir();
    const revisar = screen.getByRole("heading", { name: "Qué conviene revisar" }).closest("section") as HTMLElement;
    fireEvent.click(within(revisar).getAllByRole("button", { name: "Ver en el texto" })[0] as HTMLElement);
    expect(await screen.findByRole("region", { name: "sentencia T-999 de 2019" })).toBeTruthy();
  });

  it("el interruptor de origen marca el texto de plantilla", async () => {
    simularRed();
    await abrir();
    const hoja = screen.getByRole("article", { name: /Borrador del fallo/ });
    expect(hoja.classList.contains("bor-origen")).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: /Marcar el texto que sale de plantillas/ }));
    expect(hoja.classList.contains("bor-origen")).toBe(true);
    expect(hoja.querySelectorAll(".bor-tpl").length).toBeGreaterThan(0);
    expect(screen.getByText(/Sombreado: texto de plantilla/)).toBeTruthy();
  });

  it("enlaza a la decisión", async () => {
    simularRed();
    await abrir();
    expect(screen.getByRole("link", { name: "Pasar a la decisión" }).getAttribute("href")).toBe(`#/segunda/${CASO}/decision`);
  });
});

describe("Pedir correcciones", () => {
  async function abrirDialogo() {
    await abrir();
    await waitFor(() => expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Pedir correcciones" }));
    return await screen.findByRole("heading", { name: "Pedir correcciones al borrador" });
  }

  it("exige instrucción y parte a rehacer antes de enviar", async () => {
    const llamadas = simularRed();
    await abrirDialogo();
    fireEvent.click(screen.getByRole("button", { name: "Rehacer" }));
    expect(await screen.findByText("Escriba la instrucción: sin ella el modelo no sabe qué corregir.")).toBeTruthy();
    expect(screen.getByText("Elija qué parte rehacer.")).toBeTruthy();
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);
  });

  it("envía rehacer_consideraciones, guarda el job y navega al proceso", async () => {
    const llamadas = simularRed();
    await abrirDialogo();
    fireEvent.click(screen.getByRole("radio", { name: /Rehacer las consideraciones/ }));
    fireEvent.input(screen.getByLabelText("Qué debe corregir"), { target: { value: "  El a quo declaró improcedente.  " } });
    fireEvent.click(screen.getByRole("button", { name: "Rehacer" }));
    await waitFor(() => expect(location.hash).toBe(`#/segunda/${CASO}/proceso`));
    const envio = llamadas.find((l) => l.metodo === "POST");
    expect(envio?.url).toBe(`/api/casos/${CASO}/run`);
    expect(envio?.cuerpo).toEqual({
      cmd: "decidir",
      decision: { accion: "rehacer_consideraciones", instruccion: "El a quo declaró improcedente." },
    });
    expect(jobActual.value).toBe("j-1");
  });

  it("muestra el 409 del servidor dentro del diálogo", async () => {
    simularRed({ run: 409 });
    await abrirDialogo();
    fireEvent.click(screen.getByRole("radio", { name: /Rehacer la apertura/ }));
    fireEvent.input(screen.getByLabelText("Qué debe corregir"), { target: { value: "Corregir" } });
    fireEvent.click(screen.getByRole("button", { name: "Rehacer" }));
    expect(await screen.findByText("Ya hay una ejecución en curso para este caso.")).toBeTruthy();
    expect(location.hash).not.toBe(`#/segunda/${CASO}/proceso`);
  });

  it("deshabilita la corrección si el caso no espera decisión", async () => {
    simularRed({ estado: conEstado("terminado") });
    await abrir();
    await waitFor(() => expect(screen.getByText(/Solo se pueden pedir correcciones/)).toBeTruthy());
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("avisa y deshabilita si hay un trabajo en curso", async () => {
    simularRed({ estado: conEstado("corriendo", { job_activo: "j-9" }) });
    await abrir();
    await waitFor(() => expect(screen.getByText(/Hay una redacción en curso para este caso\. El borrador/)).toBeTruthy());
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Ver el proceso" })).toBeTruthy();
  });
});
