import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorApi } from "../../api";
import { archivoDe, XhrFalso } from "./utilesPrueba";
import { cuerpoCaso, MENSAJE_RED, mensajeError, subirCaso } from "./subida";

beforeEach(() => {
  XhrFalso.ultimo = null;
  vi.stubGlobal("XMLHttpRequest", XhrFalso);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const lista = [
  { archivo: archivoDe("c/01/a.pdf"), ruta: "c/01/a.pdf" },
  { archivo: archivoDe("c/b.pdf"), ruta: "c/b.pdf" },
];

describe("cuerpoCaso", () => {
  it("manda cada archivo en el campo files con su ruta relativa como nombre", () => {
    const datos = cuerpoCaso(lista, "");
    expect((datos.getAll("files") as File[]).map((f) => f.name)).toEqual(["c/01/a.pdf", "c/b.pdf"]);
    expect(datos.has("nombre")).toBe(false);
  });

  it("incluye el nombre recortado cuando se escribe", () => {
    expect(cuerpoCaso(lista, "  Tutela 7  ").get("nombre")).toBe("Tutela 7");
  });
});

describe("subirCaso", () => {
  it("informa el progreso real y resuelve con la respuesta", async () => {
    const progreso = vi.fn();
    const promesa = subirCaso(cuerpoCaso(lista, ""), progreso);
    const xhr = XhrFalso.ultimo!;
    expect([xhr.metodo, xhr.url]).toEqual(["POST", "/api/casos"]);
    xhr.progreso(25, 100);
    xhr.progreso(100, 100);
    xhr.responder(200, { id: "c-1", n_insumos: 2 });
    await expect(promesa).resolves.toEqual({ id: "c-1", n_insumos: 2 });
    expect(progreso.mock.calls.map((c) => c[0])).toEqual([0.25, 1, 1]);
  });

  it("rechaza con ErrorApi y el detalle del servidor", async () => {
    const promesa = subirCaso(cuerpoCaso(lista, ""), vi.fn());
    XhrFalso.ultimo!.responder(422, { detail: [{ msg: "Campo requerido" }] });
    const error = await promesa.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ErrorApi);
    expect((error as ErrorApi).estado).toBe(422);
    expect(mensajeError(error, "x")).toBe("Campo requerido");
  });

  it("rechaza con estado 0 ante un fallo de red", async () => {
    const promesa = subirCaso(cuerpoCaso(lista, ""), vi.fn());
    XhrFalso.ultimo!.fallarRed();
    const error = (await promesa.catch((e: unknown) => e)) as ErrorApi;
    expect(error.estado).toBe(0);
    expect(mensajeError(error, "x")).toBe(MENSAJE_RED);
  });

  it("aborta el XHR con la señal y rechaza con AbortError", async () => {
    const control = new AbortController();
    const promesa = subirCaso(cuerpoCaso(lista, ""), vi.fn(), control.signal);
    control.abort();
    expect(XhrFalso.ultimo!.abortado).toBe(true);
    await expect(promesa).rejects.toMatchObject({ name: "AbortError" });
  });

  it("no envía nada si la señal ya estaba abortada", async () => {
    const control = new AbortController();
    control.abort();
    await expect(subirCaso(cuerpoCaso(lista, ""), vi.fn(), control.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(XhrFalso.ultimo).toBeNull();
  });

  it("trata una respuesta 2xx sin id como error", async () => {
    const promesa = subirCaso(cuerpoCaso(lista, ""), vi.fn());
    XhrFalso.ultimo!.responder(200, "no es json");
    await expect(promesa).rejects.toBeInstanceOf(ErrorApi);
  });
});

describe("mensajeError", () => {
  it("lee detalles de texto, de lista y de {errores}", () => {
    expect(mensajeError(new ErrorApi(409, "Ya existe", "Ya existe"), "x")).toBe("Ya existe");
    expect(mensajeError(new ErrorApi(422, { errores: [{ campo: "a", mensaje: "Uno" }, { campo: "b", mensaje: "Dos" }] }, "Error 422"), "x")).toBe("Uno Dos");
  });

  it("tiene mensajes de respaldo por estado", () => {
    expect(mensajeError(new ErrorApi(409, null, "Error 409"), "x")).toMatch(/en curso/);
    expect(mensajeError(new ErrorApi(422, null, "Error 422"), "x")).toMatch(/no aceptó/);
    expect(mensajeError(new ErrorApi(500, null, "Error 500"), "x")).toMatch(/problema/);
  });

  it("trata TypeError como fallo de red y lo demás con el texto por defecto", () => {
    expect(mensajeError(new TypeError("Failed to fetch"), "x")).toBe(MENSAJE_RED);
    expect(mensajeError(new Error("raro"), "por defecto")).toBe("por defecto");
  });
});
