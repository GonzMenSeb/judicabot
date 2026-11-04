import { act, render, screen, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { errorEstadoServidor, estadoServidor, mostrarToast, tituloVista, toasts, useTitulo } from "../estado";
import { Rutas, mostrada } from "./Rutas";
import { Shell, seccionDe, tituloDeRuta } from "./Shell";
import { coincidir, ruta } from "./router";

vi.mock("../vistas/inicio", () => ({ default: () => <div data-vista="inicio"><h1>Inicio</h1></div> }));
vi.mock("../vistas/formato", async () => {
  await new Promise((r) => setTimeout(r, 30));
  return { default: () => <div data-vista="formato"><h1>Formato de documentos</h1></div> };
});
vi.mock("../vistas/borrador", () => ({ default: () => <div data-vista="borrador"><h1>Borrador</h1></div> }));

const irA = async (hash: string) => {
  await act(async () => {
    ruta.value = coincidir(hash);
  });
};

function Montaje() {
  return (
    <Shell>
      <Rutas />
    </Shell>
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ api_key: true, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [] }))),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  estadoServidor.value = null;
  errorEstadoServidor.value = false;
  toasts.value = [];
  tituloVista.value = null;
  mostrada.value = null;
  ruta.value = coincidir("");
  document.title = "";
});

describe("helpers de ruta", () => {
  it("compone el título por vista", () => {
    expect(tituloDeRuta(coincidir("#/"))).toBe("Judicabot");
    expect(tituloDeRuta(coincidir("#/segunda"))).toBe("Casos de segunda instancia · Judicabot");
    expect(tituloDeRuta(coincidir("#/formato"))).toBe("Formato de documentos · Judicabot");
    expect(tituloDeRuta(coincidir("#/segunda/c9/decision"))).toBe("Decisión · c9 · Judicabot");
  });
  it("resalta la sección del menú", () => {
    expect(seccionDe("ia")).toBe("ia");
    expect(seccionDe("formato")).toBe("formato");
    expect(seccionDe("borrador")).toBe("inicio");
  });
});

describe("Shell", () => {
  it("envuelve la vista con la barra, un único main y la clave desde el servidor", async () => {
    render(<Montaje />);
    expect(await screen.findByRole("heading", { name: "Inicio" })).toBeTruthy();
    expect(document.querySelectorAll("main#contenido")).toHaveLength(1);
    expect(screen.getByRole("banner")).toBeTruthy();
    const ia = await screen.findByRole("link", { name: /Inteligencia artificial.*clave lista/ });
    expect(ia.textContent).toContain("Sonnet 5.5");
    expect(document.title).toBe("Judicabot");
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

  it("mantiene la vista anterior mientras carga la siguiente, sin pantalla de carga", async () => {
    render(<Montaje />);
    await screen.findByRole("heading", { name: "Inicio" });
    let vistoCargando = false;
    const observador = new MutationObserver(() => {
      if (document.querySelector(".cargando-caja")) vistoCargando = true;
    });
    observador.observe(document.body, { childList: true, subtree: true });
    await act(async () => {
      ruta.value = coincidir("#/formato");
    });
    expect(document.querySelector("main#contenido")?.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("heading", { name: "Inicio" })).toBeTruthy();
    await screen.findByRole("heading", { name: /Formato/ });
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
});
