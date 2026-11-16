import { act, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { errorEstadoServidor, estadoServidor, mostrarToast, tituloVista, toasts, useTitulo } from "../estado";
import { Rutas, mostrada } from "./Rutas";
import { Shell, seccionDe, tituloDeRuta } from "./Shell";
import { coincidir, configuracion, ruta, sincronizar } from "./router";

vi.mock("../vistas/inicio", () => ({ default: () => <div data-vista="inicio"><h1>Inicio</h1></div> }));
vi.mock("../vistas/casos", async () => {
  await new Promise((r) => setTimeout(r, 30));
  return { default: () => <div data-vista="casos"><h1>Casos</h1></div> };
});
vi.mock("../vistas/formato", () => ({ default: () => <div data-vista="formato"><p>Cuerpo del formato</p></div> }));
vi.mock("../vistas/borrador", () => ({ default: () => <div data-vista="borrador"><h1>Borrador</h1></div> }));

const irA = async (hash: string) => {
  await act(async () => {
    history.replaceState(null, "", hash);
    sincronizar();
  });
};

function Montaje() {
  return (
    <Shell>
      <Rutas />
    </Shell>
  );
}

const SERVIDOR = { proveedor: "anthropic", api_key: true, gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [], modelos_gemini: [] };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(SERVIDOR))),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  estadoServidor.value = null;
  errorEstadoServidor.value = false;
  toasts.value = [];
  tituloVista.value = null;
  mostrada.value = null;
  history.replaceState(null, "", "/");
  ruta.value = coincidir("");
  configuracion.value = null;
  document.title = "";
});

describe("helpers de ruta", () => {
  it("compone el título por vista", () => {
    expect(tituloDeRuta(coincidir("#/"))).toBe("Judicabot");
    expect(tituloDeRuta(coincidir("#/segunda"))).toBe("Casos de segunda instancia · Judicabot");
    expect(tituloDeRuta(coincidir("#/segunda/c9/decision"))).toBe("Decisión · c9 · Judicabot");
    expect(tituloDeRuta(coincidir("#/configuracion/formato"))).toBe("Formato de documentos · Configuración · Judicabot");
    expect(tituloDeRuta({ ...coincidir("#/segunda/c9/decision"), configuracion: "ia" })).toBe("Inteligencia artificial · Configuración · Judicabot");
  });
  it("resalta la sección del menú", () => {
    expect(seccionDe(coincidir("#/configuracion/ia"))).toBe("configuracion");
    expect(seccionDe(coincidir("#/segunda/c9/borrador"))).toBe("inicio");
    expect(seccionDe(coincidir("#/"))).toBe("inicio");
  });
});

describe("Shell", () => {
  it("envuelve la vista con la barra, un único main y la clave desde el servidor", async () => {
    render(<Montaje />);
    expect(await screen.findByRole("heading", { name: "Inicio" })).toBeTruthy();
    expect(document.querySelectorAll("main#contenido")).toHaveLength(1);
    expect(screen.getByRole("banner")).toBeTruthy();
    const engranaje = await screen.findByRole("link", { name: "Configuración" });
    expect(engranaje.getAttribute("href")).toBe("#/configuracion");
    expect(screen.queryByRole("link", { name: /Inteligencia artificial/ })).toBeNull();
    expect(document.title).toBe("Judicabot");
  });

  it("el engranaje refleja la clave del proveedor activo", async () => {
    render(<Montaje />);
    await act(async () => {
      estadoServidor.value = { ...SERVIDOR, proveedor: "gemini", modelo: "gemini-4-carbon" } as const;
    });
    const engranaje = await screen.findByRole("link", { name: "Configuración, falta la clave" });
    expect(engranaje.querySelector(".punto")?.className).toBe("punto mal");
    await act(async () => {
      estadoServidor.value = { ...SERVIDOR, proveedor: "gemini", api_key: false, gemini_key: true, modelo: "gemini-4-carbon" } as const;
    });
    expect(screen.getByRole("link", { name: "Configuración" }).querySelector(".punto")).toBeNull();
  });

  it("no roba el foco en la primera carga y lo mueve al main al navegar", async () => {
    render(<Montaje />);
    await screen.findByRole("heading", { name: "Inicio" });
    const principal = document.querySelector<HTMLElement>("main#contenido")!;
    expect(document.activeElement).not.toBe(principal);

    await irA("#/segunda/caso-7/borrador");
    await screen.findByRole("heading", { name: "Borrador" });
    await waitFor(() => expect(document.activeElement).toBe(principal));
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
    await waitFor(() => expect(document.title).toBe("Borrador · caso-7 · Judicabot"));
    expect(principal.getAttribute("aria-busy")).toBeNull();
  });

  it("ensancha el lienzo solo en el borrador", async () => {
    render(<Montaje />);
    await screen.findByRole("heading", { name: "Inicio" });
    const principal = document.querySelector<HTMLElement>("main#contenido")!;
    expect(principal.classList.contains("lienzo-ancho")).toBe(false);
    await irA("#/segunda/caso-7/borrador");
    await screen.findByRole("heading", { name: "Borrador" });
    expect(principal.classList.contains("lienzo-ancho")).toBe(true);
    await irA("#/");
    await screen.findByRole("heading", { name: "Inicio" });
    expect(principal.classList.contains("lienzo-ancho")).toBe(false);
  });

  it("mantiene la vista anterior mientras carga la siguiente, sin pantalla de carga", async () => {
    render(<Montaje />);
    await screen.findByRole("heading", { name: "Inicio" });
    let vistoCargando = false;
    const observador = new MutationObserver(() => {
      if (document.querySelector(".cargando-caja")) vistoCargando = true;
    });
    observador.observe(document.body, { childList: true, subtree: true });
    await act(async () => {
      ruta.value = coincidir("#/segunda");
    });
    expect(document.querySelector("main#contenido")?.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("heading", { name: "Inicio" })).toBeTruthy();
    await screen.findByRole("heading", { name: "Casos" });
    observador.disconnect();
    expect(vistoCargando).toBe(false);
  });

  it("deja que la vista fije su propio título", async () => {
    function ConTitulo() {
      useTitulo("Borrador · Quintero c. EPS");
      return <div>vista</div>;
    }
    render(
      <Shell>
        <ConTitulo />
      </Shell>,
    );
    await act(async () => {});
    expect(document.title).toBe("Borrador · Quintero c. EPS · Judicabot");
  });

  it("muestra los toasts en una región viva que existe vacía", async () => {
    render(<Montaje />);
    const region = document.querySelector(".toasts");
    expect(region?.getAttribute("aria-live")).toBe("polite");
    await act(async () => {
      mostrarToast("Guardado", { tipo: "ok", ms: 0 });
    });
    expect(region?.textContent).toContain("Guardado");
    expect(document.querySelector(".toasts")).toBe(region);
  });

  it("abre la configuración sobre la página sin moverla, con su título, y lleva los toasts al panel", async () => {
    render(<Montaje />);
    await irA("#/segunda/caso-7/borrador");
    await screen.findByRole("heading", { name: "Borrador" });
    await waitFor(() => expect(document.title).toBe("Borrador · caso-7 · Judicabot"));
    vi.mocked(window.scrollTo).mockClear();
    const principal = document.querySelector<HTMLElement>("main#contenido")!;

    await irA("#/configuracion/formato");
    const panel = await screen.findByRole("dialog", { name: "Configuración" });
    expect(await within(panel).findByText("Cuerpo del formato")).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 1, name: "Formato de documentos" })).toBeTruthy();
    expect(within(principal).getByRole("heading", { name: "Borrador" })).toBeTruthy();
    expect(principal.getAttribute("aria-busy")).toBeNull();
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /^Configuración/ }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(document.title).toBe("Formato de documentos · Configuración · Judicabot"));

    await act(async () => {
      mostrarToast("Formato guardado", { tipo: "ok", ms: 0 });
    });
    const regiones = document.querySelectorAll(".toasts");
    expect(regiones).toHaveLength(1);
    expect(panel.contains(regiones[0] ?? null)).toBe(true);
    expect(regiones[0]?.textContent).toContain("Formato guardado");

    await irA("#/segunda/caso-7/borrador");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(document.querySelectorAll(".toasts")).toHaveLength(1);
    expect(panel.contains(document.querySelector(".toasts"))).toBe(false);
    await waitFor(() => expect(document.title).toBe("Borrador · caso-7 · Judicabot"));
  });
});
