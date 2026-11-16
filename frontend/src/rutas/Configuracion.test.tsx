import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FormatoRespuesta } from "../api/contrato";
import { estadoServidor, toasts } from "../estado";
import { CAMPOS_MOCK, DOCUMENTOS_MOCK, VALORES_MOCK } from "../vistas/formato/mock";
import { mostrada, Rutas } from "./Rutas";
import { Shell } from "./Shell";
import { coincidir, configuracion, ruta } from "./router";

vi.mock("../vistas/inicio", () => ({ default: () => <div data-vista="inicio"><h1>Inicio</h1></div> }));
vi.mock("../vistas/casos", () => ({ default: () => <div data-vista="casos"><h1>Casos</h1></div> }));
vi.mock("../vistas/ia", () => ({ default: () => <div data-vista="ia"><h2>Modelo</h2></div> }));

const formato: FormatoRespuesta = { campos: CAMPOS_MOCK, valores: VALORES_MOCK, plantilla_gen: "B", documentos: DOCUMENTOS_MOCK };

const json = (cuerpo: unknown) => new Response(JSON.stringify(cuerpo), { headers: { "Content-Type": "application/json" } });

const cambioDeHash = () => new Promise((r) => addEventListener("hashchange", r, { once: true }));

async function esperarHash(accion: () => void) {
  const cambio = cambioDeHash();
  await act(async () => {
    accion();
    await cambio;
  });
}

const panel = () => screen.getByRole("dialog", { name: "Configuración" });
const engranaje = () => screen.getByRole("link", { name: /^Configuración/ });
const navegacion = () => within(panel()).getByRole("navigation", { name: "Secciones de configuración" });

async function abrirSobreCasos() {
  render(
    <Shell>
      <Rutas />
    </Shell>,
  );
  await esperarHash(() => (location.hash = "#/segunda"));
  await screen.findByRole("heading", { name: "Casos" });
  await esperarHash(() => fireEvent.click(engranaje()));
  await within(panel()).findByRole("heading", { level: 2, name: "Despacho" });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => json(url === "/api/formato" ? formato : { api_key: false, jev_key: false, modelo: "claude-opus-5-5", modelos: [] })),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  estadoServidor.value = null;
  toasts.value = [];
  mostrada.value = null;
  history.replaceState(null, "", "/");
  ruta.value = coincidir("");
  configuracion.value = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

describe("panel de configuración", () => {
  it("el engranaje abre la primera sección sobre la página, con la navegación y el estado de la IA", async () => {
    await abrirSobreCasos();
    expect(location.hash).toBe("#/configuracion/formato");
    expect(within(document.querySelector("main") as HTMLElement).getByRole("heading", { name: "Casos" })).toBeTruthy();
    expect(within(panel()).getByRole("heading", { level: 1, name: "Formato de documentos" })).toBeTruthy();
    const actual = within(navegacion()).getByRole("link", { current: "page" });
    expect(actual.getAttribute("href")).toBe("#/configuracion/formato");
    expect(document.activeElement).toBe(actual);
    const ia = await within(navegacion()).findByRole("link", { name: /Inteligencia artificial.*Opus 5\.5.*falta la clave/ });
    expect(ia.getAttribute("href")).toBe("#/configuracion/ia");
    expect(ia.querySelector(".punto")?.className).toBe("punto mal");
    expect(engranaje().getAttribute("aria-label")).toBeNull();
    expect(engranaje().textContent).toBe("Configuración, falta la clave");
  });

  it("cambia de sección con la navegación del panel", async () => {
    await abrirSobreCasos();
    await esperarHash(() => fireEvent.click(within(navegacion()).getByRole("link", { name: /Inteligencia artificial/ })));
    expect(location.hash).toBe("#/configuracion/ia");
    expect(await within(panel()).findByRole("heading", { level: 2, name: "Modelo" })).toBeTruthy();
    expect(within(panel()).getByRole("heading", { level: 1, name: "Inteligencia artificial" })).toBeTruthy();
    expect(within(navegacion()).getByRole("link", { current: "page" }).getAttribute("href")).toBe("#/configuracion/ia");
  });

  it("la navegación lista las tres secciones en orden y la extensión es la tercera", async () => {
    await abrirSobreCasos();
    const [formato, ia, extension, ...otras] = within(navegacion()).getAllByRole("link");
    expect(otras).toHaveLength(0);
    expect([formato, ia, extension].map((e) => e?.getAttribute("href"))).toEqual(["#/configuracion/formato", "#/configuracion/ia", "#/configuracion/extension"]);
    expect(formato?.textContent?.trim()).toBe("Formato de documentos");
    expect(ia?.textContent).toMatch(/^Inteligencia artificial/);
    expect(extension?.textContent?.trim()).toBe("Extensión de la relatoría");

    await esperarHash(() => fireEvent.click(extension as HTMLElement));
    expect(location.hash).toBe("#/configuracion/extension");
    expect(within(panel()).getByRole("heading", { level: 1, name: "Extensión de la relatoría" })).toBeTruthy();
    expect(await within(panel()).findByRole("link", { name: "Descargar extensión (.zip)" })).toBeTruthy();
    expect(within(navegacion()).getByRole("link", { current: "page" }).getAttribute("href")).toBe("#/configuracion/extension");
    expect(document.title).toBe("Extensión de la relatoría · Configuración · Judicabot");
  });

  it("la X cierra, vuelve a la página de fondo y devuelve el foco al engranaje", async () => {
    await abrirSobreCasos();
    await esperarHash(() => fireEvent.click(within(panel()).getByRole("button", { name: "Cerrar configuración" })));
    expect(location.hash).toBe("#/segunda");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Casos" })).toBeTruthy();
    expect(document.activeElement).toBe(engranaje());
  });

  it("Escape cierra el panel", async () => {
    await abrirSobreCasos();
    await esperarHash(() => fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" }));
    expect(location.hash).toBe("#/segunda");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("un clic en el fondo cierra el panel", async () => {
    await abrirSobreCasos();
    const dialogo = document.querySelector("dialog.panel") as HTMLElement;
    fireEvent.mouseDown(dialogo);
    await esperarHash(() => fireEvent.click(dialogo));
    expect(location.hash).toBe("#/segunda");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("el botón Atrás cierra el panel sin recargar la página de fondo", async () => {
    await abrirSobreCasos();
    const fondo = ruta.value;
    await esperarHash(() => history.back());
    expect(location.hash).toBe("#/segunda");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(ruta.value).toBe(fondo);
  });

  it("con cambios sin guardar en el formato, cerrar pide confirmación", async () => {
    await abrirSobreCasos();
    fireEvent.input(within(panel()).getByLabelText("Ciudad"), { target: { value: "Cali" } });
    await within(panel()).findByRole("region", { name: "Cambios sin guardar" });

    fireEvent.click(within(panel()).getByRole("button", { name: "Cerrar configuración" }));
    const guardia = await within(panel()).findByRole("dialog", { name: "Hay cambios sin guardar" });
    expect(location.hash).toBe("#/configuracion/formato");
    fireEvent.click(within(guardia).getByRole("button", { name: "Seguir editando" }));
    await waitFor(() => expect(within(panel()).queryByRole("dialog")).toBeNull());
    expect((within(panel()).getByLabelText("Ciudad") as HTMLInputElement).value).toBe("Cali");

    fireEvent.keyDown(within(panel()).getByLabelText("Ciudad"), { key: "Escape" });
    const otra = await within(panel()).findByRole("dialog", { name: "Hay cambios sin guardar" });
    fireEvent.keyDown(within(otra).getByRole("button", { name: "Seguir editando" }), { key: "Escape" });
    await waitFor(() => expect(within(panel()).queryByRole("dialog")).toBeNull());
    expect(location.hash).toBe("#/configuracion/formato");

    fireEvent.click(within(panel()).getByRole("button", { name: "Cerrar configuración" }));
    const ultima = await within(panel()).findByRole("dialog", { name: "Hay cambios sin guardar" });
    await esperarHash(() => fireEvent.click(within(ultima).getByRole("button", { name: "Salir sin guardar" })));
    expect(location.hash).toBe("#/segunda");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Casos" })).toBeTruthy();
  });

  it("con cambios sin guardar en el formato, cambiar de sección pide confirmación", async () => {
    await abrirSobreCasos();
    fireEvent.input(within(panel()).getByLabelText("Ciudad"), { target: { value: "Cali" } });
    await within(panel()).findByRole("region", { name: "Cambios sin guardar" });

    fireEvent.click(within(navegacion()).getByRole("link", { name: /Inteligencia artificial/ }));
    const guardia = await within(panel()).findByRole("dialog", { name: "Hay cambios sin guardar" });
    expect(location.hash).toBe("#/configuracion/formato");
    await esperarHash(() => fireEvent.click(within(guardia).getByRole("button", { name: "Salir sin guardar" })));
    expect(location.hash).toBe("#/configuracion/ia");
    expect(await within(panel()).findByRole("heading", { level: 2, name: "Modelo" })).toBeTruthy();
  });
});
