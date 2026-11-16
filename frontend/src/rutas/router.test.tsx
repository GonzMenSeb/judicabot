import { act, render, screen } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rutas } from "./Rutas";
import { coincidir, configuracion, hashDe, navegar, navegarDirecto, protegerSalida, ruta, sincronizar } from "./router";

vi.mock("../vistas/inicio", () => ({ default: () => <div data-vista="inicio"><h1>Inicio</h1></div> }));
vi.mock("../vistas/decision", () => ({ default: ({ caso }: { caso?: string }) => <div data-vista="decision"><h1>Decisión</h1><p>{caso}</p></div> }));
vi.mock("../vistas/borrador", () => ({ default: () => <div data-vista="borrador"><h1>Borrador</h1></div> }));

describe("coincidir", () => {
  it("resuelve las rutas declaradas", () => {
    expect(coincidir("")).toEqual({ vista: "inicio", params: {} });
    expect(coincidir("#/")).toEqual({ vista: "inicio", params: {} });
    expect(coincidir("#/segunda")).toEqual({ vista: "casos", params: {} });
    expect(coincidir("#/segunda/")).toEqual({ vista: "casos", params: {} });
  });

  it("resuelve las secciones de configuración sobre Inicio, también desde las rutas antiguas", () => {
    expect(coincidir("#/configuracion/formato")).toEqual({ vista: "inicio", params: {}, configuracion: "formato" });
    expect(coincidir("#/configuracion/ia")).toEqual({ vista: "inicio", params: {}, configuracion: "ia" });
    expect(coincidir("#/configuracion/extension")).toEqual({ vista: "inicio", params: {}, configuracion: "extension" });
    expect(coincidir("#/configuracion")).toEqual({ vista: "inicio", params: {}, configuracion: "formato" });
    expect(coincidir("#/configuracion/")).toEqual({ vista: "inicio", params: {}, configuracion: "formato" });
    expect(coincidir("#/formato")).toEqual({ vista: "inicio", params: {}, configuracion: "formato" });
    expect(coincidir("#/ia")).toEqual({ vista: "inicio", params: {}, configuracion: "ia" });
  });

  it("arma el hash de cada ruta de página", () => {
    expect(hashDe(coincidir("#/"))).toBe("#/");
    expect(hashDe(coincidir("#/segunda/"))).toBe("#/segunda");
    expect(hashDe(coincidir("#/segunda/a%20b/fallo"))).toBe("#/segunda/a%20b/fallo");
  });

  it.each(["documentos", "proceso", "borrador", "decision", "fallo"])("resuelve la etapa %s de un caso", (etapa) => {
    expect(coincidir(`#/segunda/caso-1/${etapa}`)).toEqual({ vista: etapa, params: { caso: "caso-1" } });
  });

  it("decodifica el caso y tolera codificaciones inválidas", () => {
    expect(coincidir("#/segunda/a%20b/fallo").params.caso).toBe("a b");
    expect(coincidir("#/segunda/%E0%A4%A/fallo").params.caso).toBe("%E0%A4%A");
  });

  it.each(["#/nada", "#/segunda/caso-1", "#/segunda/caso-1/otra", "#/segunda/caso-1/fallo/extra", "#/formato/x", "#//", "#/configuracion/otra", "#/configuracion/ia/x", "#/constructor", "#/extension"])(
    "vuelve al inicio con %s",
    (hash) => {
      expect(coincidir(hash)).toEqual({ vista: "inicio", params: {} });
    },
  );
});

const cambioDeHash = () => new Promise((r) => addEventListener("hashchange", r, { once: true }));

const irA = async (hash: string) => {
  const cambio = cambioDeHash();
  location.hash = hash;
  await cambio;
};

describe("navegación", () => {
  beforeEach(() => {
    history.replaceState(null, "", "/");
    ruta.value = coincidir("");
    configuracion.value = null;
  });

  it("actualiza la ruta al cambiar el hash", async () => {
    const cambio = cambioDeHash();
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

describe("configuración", () => {
  beforeEach(() => {
    history.replaceState(null, "", "/");
    ruta.value = coincidir("");
    configuracion.value = null;
  });

  it("abre la sección sin cambiar la página de fondo y la conserva al cambiar de sección", async () => {
    await irA("#/segunda");
    const fondo = ruta.value;
    expect(fondo).toEqual({ vista: "casos", params: {} });

    await irA("#/configuracion/ia");
    expect(configuracion.value).toBe("ia");
    expect(ruta.value).toBe(fondo);

    await irA("#/configuracion/formato");
    expect(configuracion.value).toBe("formato");
    expect(ruta.value).toBe(fondo);

    await irA("#/segunda");
    expect(configuracion.value).toBeNull();
    expect(ruta.value).toBe(fondo);
  });

  it("con enlace directo o recarga deja Inicio de fondo", () => {
    ruta.value = coincidir("#/segunda/c1/fallo");
    history.replaceState(null, "", "#/configuracion/ia");
    ruta.value = coincidir("");
    sincronizar();
    expect(configuracion.value).toBe("ia");
    expect(ruta.value).toEqual({ vista: "inicio", params: {} });
  });

  it.each([
    ["#/formato", "#/configuracion/formato", "formato"],
    ["#/ia", "#/configuracion/ia", "ia"],
    ["#/configuracion", "#/configuracion/formato", "formato"],
  ])("%s redirige a %s reemplazando la entrada del historial", async (vieja, nueva, seccion) => {
    const antes = history.length;
    await irA(vieja);
    expect(location.hash).toBe(nueva);
    expect(configuracion.value).toBe(seccion);
    expect(history.length).toBe(antes + 1);
  });

  it("con la configuración abierta, navegar cambia la página de fondo sin cerrar el panel ni consultar las guardias", async () => {
    await irA("#/segunda");
    await irA("#/configuracion/ia");
    const pedidos: string[] = [];
    const soltar = protegerSalida((destino) => {
      pedidos.push(destino);
      return true;
    });

    navegar("#/segunda/c1/documentos");
    expect(location.hash).toBe("#/configuracion/ia");
    expect(configuracion.value).toBe("ia");
    expect(ruta.value).toEqual({ vista: "documentos", params: { caso: "c1" } });
    expect(pedidos).toEqual([]);

    soltar();
    navegarDirecto(hashDe(ruta.value));
    await vi.waitFor(() => expect(location.hash).toBe("#/segunda/c1/documentos"));
    expect(configuracion.value).toBeNull();
    expect(ruta.value).toEqual({ vista: "documentos", params: { caso: "c1" } });
  });

  it("con la configuración abierta, navegar a otra sección sí cambia el hash", async () => {
    await irA("#/configuracion/ia");
    const cambio = cambioDeHash();
    navegar("#/configuracion/formato");
    await cambio;
    expect(configuracion.value).toBe("formato");
  });

  it("el botón Atrás cierra la configuración y vuelve a la página de fondo", async () => {
    await irA("#/segunda/c1/borrador");
    const fondo = ruta.value;
    await irA("#/configuracion/ia");
    expect(configuracion.value).toBe("ia");

    const atras = cambioDeHash();
    history.back();
    await atras;
    expect(location.hash).toBe("#/segunda/c1/borrador");
    expect(configuracion.value).toBeNull();
    expect(ruta.value).toBe(fondo);
  });
});

describe("guardias de salida", () => {
  beforeEach(() => {
    history.replaceState(null, "", "/");
    ruta.value = coincidir("");
  });

  it("una guardia puede detener navegar y, al soltarla, la navegación sigue", async () => {
    const pedidos: string[] = [];
    const soltar = protegerSalida((destino) => {
      pedidos.push(destino);
      return true;
    });
    navegar("#/segunda");
    expect(pedidos).toEqual(["#/segunda"]);
    expect(location.hash).toBe("");

    soltar();
    const cambio = cambioDeHash();
    navegar("#/segunda");
    await cambio;
    expect(ruta.value).toEqual({ vista: "casos", params: {} });
    expect(pedidos).toHaveLength(1);
  });
});
