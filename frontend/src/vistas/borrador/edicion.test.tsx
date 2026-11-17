import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Bloque, ConflictoEdicion, EdicionesRespuesta, Vista } from "../../api/contrato";
import { jobActual, toasts } from "../../estado";
import { claveRevisados } from "./datos";
import { Documento, type EdicionDocumento } from "./Documento";
import Borrador from "./index";
import { CASO_MOCK_BORRADOR, crearEdicionesMock, ESTADO_BORRADOR, VISTA_BORRADOR } from "./mock";

const CASO = CASO_MOCK_BORRADOR;
const BASE = `/api/casos/${CASO}`;
const HECHOS = "apertura.antecedentes_hechos";
const CONTESTACION = "apertura.contestaciones.0.texto";

class Falla {
  constructor(
    readonly estado: number,
    readonly detail: string | unknown[],
  ) {}
}

type Respuesta = object | string | number | null | Falla | ((n: number) => unknown);

interface Red {
  vista?: Respuesta;
  estado?: Respuesta;
  ediciones?: Respuesta;
  put?: Respuesta;
  eliminar?: Respuesta;
  resolver?: Respuesta;
}

interface Llamada {
  url: string;
  metodo: string;
  cuerpo: unknown;
}

const json = (cuerpo: unknown, estado = 200) => new Response(JSON.stringify(cuerpo), { status: estado, headers: { "Content-Type": "application/json" } });

async function convertir(respuesta: Respuesta, n: number): Promise<Response> {
  const valor = typeof respuesta === "function" ? await (respuesta as (n: number) => unknown)(n) : respuesta;
  return valor instanceof Falla ? json({ detail: valor.detail }, valor.estado) : json(valor);
}

const NO_ENCONTRADO = new Falla(404, "No encontrado");

function simularRed({
  vista = VISTA_BORRADOR,
  estado = ESTADO_BORRADOR,
  ediciones = NO_ENCONTRADO,
  put = NO_ENCONTRADO,
  eliminar = NO_ENCONTRADO,
  resolver = NO_ENCONTRADO,
}: Red = {}) {
  const llamadas: Llamada[] = [];
  const conteo = new Map<string, number>();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const metodo = init?.method ?? "GET";
      llamadas.push({ url, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : undefined });
      let clave: string | null = null;
      let respuesta: Respuesta = NO_ENCONTRADO;
      if (metodo === "GET" && url.endsWith("/vista/borrador")) [clave, respuesta] = ["vista", vista];
      else if (metodo === "GET" && url.endsWith("/estado")) [clave, respuesta] = ["estado", estado];
      else if (metodo === "GET" && url.endsWith("/ediciones")) [clave, respuesta] = ["ediciones", ediciones];
      else if (metodo === "PUT" && /\/ediciones\/[^/]+$/.test(url)) [clave, respuesta] = ["put", put];
      else if (metodo === "DELETE" && /\/ediciones\/[^/]+$/.test(url)) [clave, respuesta] = ["eliminar", eliminar];
      else if (metodo === "POST" && url.endsWith("/resolver")) [clave, respuesta] = ["resolver", resolver];
      else if (metodo === "POST" && url.endsWith("/run")) return json({ job_id: "j-1" });
      const n = clave ? (conteo.get(clave) ?? 0) : 0;
      if (clave) conteo.set(clave, n + 1);
      return convertir(respuesta, n);
    }),
  );
  const veces = (metodo: string, fin: string) => llamadas.filter((l) => l.metodo === metodo && l.url.endsWith(fin)).length;
  return { llamadas, veces };
}

const ED: EdicionesRespuesta = crearEdicionesMock().respuesta();
const conEdiciones = (extra: Partial<EdicionesRespuesta> = {}): EdicionesRespuesta => ({ ...structuredClone(ED), ...extra });
const piezaConEdicion = (pieza: string, editados: number[], avisos: string[] = []): EdicionesRespuesta => {
  const copia = conEdiciones();
  const datos = copia.piezas[pieza];
  if (datos) copia.piezas[pieza] = { ...datos, editados, modificada: editados.length > 0, avisos };
  return copia;
};

const piezaSinParrafos = (pieza: string): EdicionesRespuesta => {
  const copia = conEdiciones();
  const datos = copia.piezas[pieza];
  if (datos) copia.piezas[pieza] = { ...datos, modificada: true };
  return copia;
};

const CONFLICTO: ConflictoEdicion = {
  pieza: HECHOS,
  etiqueta: "Antecedentes: hechos",
  huerfana: false,
  trozos: [
    { tipo: "ok", parrafos: ["Contexto previo al choque."] },
    { tipo: "conflicto", mio: ["Mi texto A."], nuevo: ["Texto de la corrección A."], mio_permitido: true },
    { tipo: "ok", parrafos: ["Contexto intermedio."] },
    { tipo: "conflicto", mio: ["Mi texto B con ⟦cita c9 · T-1 de 2020⟧."], nuevo: ["Texto de la corrección B."], mio_permitido: false },
  ],
};
const HUERFANA: ConflictoEdicion = { pieza: CONTESTACION, etiqueta: "Antecedentes: contestación de EPS Horizonte", huerfana: true, trozos: [] };

const hoja = () => screen.getByRole("article", { name: /Borrador del fallo/ });
const panel = () => document.getElementById("bor-panel") as HTMLElement;
const botones = () => screen.queryAllByRole("button", { name: "Editar párrafo" }) as HTMLButtonElement[];
const unidadDe = (texto: RegExp) => within(hoja()).getByText(texto).closest<HTMLElement>(".bor-unidad") as HTMLElement;
const botonDe = (texto: RegExp) => within(unidadDe(texto)).getByRole("button", { name: "Editar párrafo" });
const parrafoMock = (pieza: string, k: number): string => ED.piezas[pieza]?.parrafos[k] ?? "";

async function abrir() {
  const vista = render(<Borrador caso={CASO} />);
  await screen.findByRole("heading", { level: 3, name: /ASUNTO/ });
  return vista;
}

async function abrirEditando(red: Red = {}) {
  const salida = simularRed({ ediciones: ED, ...red });
  await abrir();
  fireEvent.click(await screen.findByRole("switch", { name: "Editar texto" }));
  return salida;
}

async function abrirConflictos(red: Red = {}) {
  const salida = simularRed({ ediciones: conEdiciones({ conflictos: [CONFLICTO] }), ...red });
  await abrir();
  fireEvent.click(await screen.findByRole("button", { name: "Resolver" }));
  const titulo = await screen.findByRole("heading", { name: "Resolver conflictos de edición" });
  return { ...salida, dialogo: titulo.closest("dialog") as HTMLElement };
}

const RELATO = /Relató que padece/;

beforeEach(() => {
  location.hash = "";
  jobActual.value = null;
  toasts.value = [];
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Interruptor Editar texto", () => {
  it("no aparece si /ediciones falla y el borrador sigue funcionando", async () => {
    simularRed();
    await abrir();
    expect(screen.queryByRole("switch", { name: "Editar texto" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Marcar texto de plantilla" })).toBeTruthy();
    expect(botones()).toHaveLength(0);
    expect(screen.getByText("Quedan 7 puntos por revisar")).toBeTruthy();
  });

  it("no aparece si el servidor dice que no se puede editar", async () => {
    simularRed({ ediciones: { editable: false, motivo: "Hay una redacción en curso para este caso.", piezas: {}, conflictos: [] } });
    await abrir();
    await screen.findByText("Quedan 7 puntos por revisar");
    expect(screen.queryByRole("switch", { name: "Editar texto" })).toBeNull();
    expect(botones()).toHaveLength(0);
  });

  it("aparece apagado y sin botones hasta que se enciende", async () => {
    simularRed({ ediciones: ED });
    await abrir();
    const control = await screen.findByRole("switch", { name: "Editar texto" });
    expect((control as HTMLInputElement).checked).toBe(false);
    expect(botones()).toHaveLength(0);
    fireEvent.click(control);
    expect((control as HTMLInputElement).checked).toBe(true);
    expect(botones()).toHaveLength(15);
    fireEvent.click(control);
    expect(botones()).toHaveLength(0);
  });

  it("con el modo apagado el documento queda idéntico al de solo lectura", async () => {
    simularRed();
    const primera = await abrir();
    const solo = hoja().innerHTML;
    primera.unmount();
    simularRed({ ediciones: ED });
    await abrir();
    await screen.findByRole("switch", { name: "Editar texto" });
    expect(hoja().innerHTML).toBe(solo);
    expect(hoja().querySelectorAll(".bor-unidad").length).toBe(0);
  });

  it("solo los bloques con fuente tienen botón, uno por unidad, y la plantilla no", async () => {
    await abrirEditando();
    expect(hoja().querySelectorAll(".bor-unidad").length).toBe(15);
    expect(unidadDe(RELATO).querySelectorAll("button").length).toBe(1);
    const plantilla = within(hoja()).getByText(/Este Despacho es competente/);
    expect(plantilla.closest(".bor-unidad")).toBeNull();
    expect(within(hoja()).getByText(/Procede el Despacho a resolver/).closest(".bor-unidad")).toBeNull();
    expect(within(hoja()).getByText(/una vez iniciado un tratamiento/).closest(".bor-unidad")).toBeNull();
  });

  it("se apaga solo si el servidor deja de permitir la edición", async () => {
    const { veces } = simularRed({
      ediciones: (n) => (n === 0 ? ED : { editable: false, motivo: "Hay una redacción en curso para este caso.", piezas: {}, conflictos: [] }),
      put: new Falla(409, "Hay una redacción en curso para este caso."),
    });
    await abrir();
    fireEvent.click(await screen.findByRole("switch", { name: "Editar texto" }));
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.keyDown(campo, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(veces("GET", "/ediciones")).toBe(2));
    await waitFor(() => expect(screen.queryByRole("switch", { name: "Editar texto" })).toBeNull());
    expect(botones()).toHaveLength(0);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("Editor de párrafo", () => {
  it("abre con el texto editable, enfocado, y reemplaza solo ese párrafo", async () => {
    await abrirEditando();
    fireEvent.click(botonDe(RELATO));
    const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
    expect(campo.tagName).toBe("TEXTAREA");
    expect(campo.value).toBe(parrafoMock(HECHOS, 1));
    await waitFor(() => expect(document.activeElement).toBe(campo));
    expect(within(hoja()).queryByText(RELATO)).toBeNull();
    expect(within(hoja()).getByText(/presentó acción de tutela el catorce/)).toBeTruthy();
    expect(screen.getByText("Deje una línea en blanco entre párrafos. Las fichas ⟦…⟧ son citas e imágenes: no se pueden cambiar.")).toBeTruthy();
    expect(campo.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restaurar el texto de la IA" })).toBeNull();
  });

  it("los títulos se editan en una línea", async () => {
    await abrirEditando();
    fireEvent.click(botonDe(/La salud y la continuidad del tratamiento/));
    const campo = (await screen.findByRole("textbox", { name: "Título del bloque" })) as HTMLInputElement;
    expect(campo.tagName).toBe("INPUT");
    expect(campo.value).toBe("La salud y la continuidad del tratamiento");
    expect(screen.getByText("El título ocupa una sola línea.")).toBeTruthy();
  });

  it("Ctrl+Enter envía PUT con parrafo, original y texto y recarga sin pasar por «Cargando»", async () => {
    let soltar: (v: unknown) => void = () => undefined;
    const pendiente = new Promise((r) => (soltar = r));
    const nueva: Vista = structuredClone(VISTA_BORRADOR);
    nueva.sha256 = "2".repeat(64);
    const bloque = nueva.paginas[0]?.bloques.find((b) => b.id === "antecedentes-del-caso-2") as Bloque;
    bloque.segmentos = [{ texto: "Relato corregido por el despacho." }];
    const { llamadas, veces } = await abrirEditando({
      vista: (n) => (n === 0 ? VISTA_BORRADOR : pendiente),
      put: piezaConEdicion(HECHOS, [1]),
      ediciones: (n) => (n === 0 ? ED : piezaConEdicion(HECHOS, [1])),
    });
    fireEvent.click(botonDe(RELATO));
    const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
    const original = campo.value;
    fireEvent.input(campo, { target: { value: "Relato corregido por el despacho." } });
    expect(fireEvent.keyDown(campo, { key: "Enter", ctrlKey: true })).toBe(false);
    await waitFor(() => expect(veces("GET", "/vista/borrador")).toBe(2));
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.url).toBe(`${BASE}/ediciones/${HECHOS}`);
    expect(put?.cuerpo).toEqual({ parrafo: 1, original, texto: "Relato corregido por el despacho." });
    expect(veces("GET", "/ediciones")).toBe(2);
    expect(veces("GET", "/estado")).toBe(2);
    expect(screen.queryByText("Cargando el borrador…")).toBeNull();
    expect(hoja().isConnected).toBe(true);
    expect(screen.getByRole("textbox", { name: "Texto del párrafo" })).toBeTruthy();
    soltar(nueva);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(screen.queryByText("Cargando el borrador…")).toBeNull();
    expect(within(hoja()).getByText("Relato corregido por el despacho.")).toBeTruthy();
    const boton = botonDe(/Relato corregido por el despacho/);
    await waitFor(() => expect(document.activeElement).toBe(boton));
    expect(within(unidadDe(/Relato corregido/)).getByText("Editado")).toBeTruthy();
  });

  it("Cmd+Enter también guarda y Guardar envía el formulario", async () => {
    const { llamadas } = await abrirEditando({ put: ED });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.keyDown(campo, { key: "Enter", metaKey: true });
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(2));
  });

  it("Enter solo no guarda y el botón se deshabilita mientras guarda", async () => {
    let soltar: (v: unknown) => void = () => undefined;
    const pendiente = new Promise((r) => (soltar = r));
    const { llamadas } = await abrirEditando({ put: () => pendiente });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.keyDown(campo, { key: "Enter" });
    expect(llamadas.some((l) => l.metodo === "PUT")).toBe(false);
    fireEvent.keyDown(campo, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect((screen.getByRole("button", { name: "Guardar" }) as HTMLButtonElement).disabled).toBe(true));
    expect((screen.getByRole("button", { name: "Cancelar" }) as HTMLButtonElement).disabled).toBe(true);
    expect((campo as HTMLTextAreaElement).readOnly).toBe(true);
    fireEvent.keyDown(campo, { key: "Enter", ctrlKey: true });
    expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(1);
    soltar(ED);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });

  it("Escape cancela, devuelve el foco al botón y no cierra el panel abierto", async () => {
    await abrirEditando();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    expect(panel().classList.contains("abierto")).toBe(true);
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(campo, { target: { value: "Cambio que se descarta" } });
    expect(fireEvent.keyDown(campo, { key: "Escape" })).toBe(false);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(panel().classList.contains("abierto")).toBe(true);
    await waitFor(() => expect(document.activeElement).toBe(botonDe(RELATO)));
    expect(within(hoja()).getByText(RELATO)).toBeTruthy();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(panel().classList.contains("abierto")).toBe(false);
  });

  it("Cancelar descarta el cambio sin llamar a la API", async () => {
    const { llamadas } = await abrirEditando();
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(campo, { target: { value: "Otro" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(llamadas.some((l) => l.metodo !== "GET")).toBe(false);
    fireEvent.click(botonDe(RELATO));
    expect(((await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement).value).toBe(parrafoMock(HECHOS, 1));
  });

  it("muestra el 422 en línea y conserva lo escrito", async () => {
    await abrirEditando({ put: new Falla(422, "Las citas no coinciden con las de la IA: falta ⟦cita c1 · T-760 de 2008⟧.") });
    fireEvent.click(botonDe(RELATO));
    const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
    fireEvent.input(campo, { target: { value: "Sin la cita" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toBe("Las citas no coinciden con las de la IA: falta ⟦cita c1 · T-760 de 2008⟧.");
    expect(campo.value).toBe("Sin la cita");
    expect((screen.getByRole("button", { name: "Guardar" }) as HTMLButtonElement).disabled).toBe(false);
    expect(campo.readOnly).toBe(false);
  });

  it("un 422 de validación con lista de errores muestra un mensaje general", async () => {
    await abrirEditando({ put: new Falla(422, [{ loc: ["body", "parrafo"], msg: "Input should be greater than or equal to 0" }]) });
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect((await screen.findByRole("alert")).textContent).toBe("El texto no es válido.");
  });

  it("un 409 avisa de que el texto cambió y recarga la vista", async () => {
    const { veces } = await abrirEditando({ put: new Falla(409, "El texto cambió; recargue el borrador.") });
    fireEvent.click(botonDe(RELATO));
    const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
    fireEvent.input(campo, { target: { value: "Mi cambio" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("El texto cambió");
    await waitFor(() => expect(veces("GET", "/vista/borrador")).toBe(2));
    expect(veces("GET", "/ediciones")).toBe(2);
    expect(screen.queryByText("Cargando el borrador…")).toBeNull();
    expect(campo.value).toBe("Mi cambio");
  });

  it("tras un 409 el reintento sigue enviando el original con el que se abrió", async () => {
    const { llamadas } = await abrirEditando({
      put: new Falla(409, "El texto cambió; recargue el borrador."),
      ediciones: (n) => (n === 0 ? ED : conEdiciones({ piezas: { ...ED.piezas, [HECHOS]: { parrafos: ["otro", "texto", "distinto"], editados: [], modificada: false, avisos: [] } } })),
    });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    const original = (campo as HTMLTextAreaElement).value;
    fireEvent.input(campo, { target: { value: "Mi cambio" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "GET" && l.url.endsWith("/ediciones"))).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(2));
    expect(llamadas.filter((l) => l.metodo === "PUT").map((l) => (l.cuerpo as { original: string }).original)).toEqual([original, original]);
  });

  describe("tras un 409 con el párrafo cambiado en el servidor", () => {
    const ACTUAL = "Texto que otra sesión dejó en este párrafo.";
    const recargadas = () =>
      conEdiciones({ piezas: { ...ED.piezas, [HECHOS]: { parrafos: [parrafoMock(HECHOS, 0), ACTUAL, parrafoMock(HECHOS, 2)], editados: [], modificada: false, avisos: [] } } });

    async function conDesfase(put: Respuesta) {
      const red = await abrirEditando({ put, ediciones: (n) => (n === 0 ? ED : recargadas()) });
      fireEvent.click(botonDe(RELATO));
      const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
      fireEvent.input(campo, { target: { value: "Mi cambio" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
      await screen.findByRole("alert");
      return { ...red, campo };
    }

    it("muestra la versión actual y conserva lo escrito sin ofrecer cancelar y reabrir", async () => {
      const { campo } = await conDesfase(new Falla(409, "El texto cambió; recargue el borrador."));
      const actual = await screen.findByText(ACTUAL);
      expect(actual.className).toBe("bor-editor-actual");
      expect(screen.getByText("Este párrafo cambió mientras lo editaba. Ahora dice:")).toBeTruthy();
      expect(screen.getByRole("alert").textContent).not.toMatch(/cancele y vuelva a abrir/);
      expect(campo.value).toBe("Mi cambio");
    });

    it("«Guardar sobre la versión actual» envía lo escrito con la versión actual como original y cierra al guardar", async () => {
      const { llamadas } = await conDesfase((n) => (n === 0 ? new Falla(409, "El texto cambió; recargue el borrador.") : ED));
      fireEvent.click(await screen.findByRole("button", { name: "Guardar sobre la versión actual" }));
      await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(2));
      const [primero, segundo] = llamadas.filter((l) => l.metodo === "PUT").map((l) => l.cuerpo as { parrafo: number; original: string; texto: string });
      expect(primero?.original).toBe(parrafoMock(HECHOS, 1));
      expect(segundo).toEqual({ parrafo: 1, original: ACTUAL, texto: "Mi cambio" });
      await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    });

    it("«Guardar» sigue enviando el original con el que se abrió", async () => {
      const { llamadas } = await conDesfase(new Falla(409, "El texto cambió; recargue el borrador."));
      await screen.findByText(ACTUAL);
      fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
      await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PUT")).toHaveLength(2));
      expect(llamadas.filter((l) => l.metodo === "PUT").map((l) => (l.cuerpo as { original: string }).original)).toEqual([parrafoMock(HECHOS, 1), parrafoMock(HECHOS, 1)]);
    });
  });

  it("un 409 con el párrafo igual tras recargar no ofrece guardar sobre otra versión", async () => {
    await abrirEditando({ put: new Falla(409, "Hay una redacción en curso para este caso.") });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(campo, { target: { value: "Mi cambio" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Hay una redacción en curso");
    expect(screen.queryByRole("button", { name: "Guardar sobre la versión actual" })).toBeNull();
    expect(screen.queryByText(/cambió mientras lo editaba/)).toBeNull();
  });

  describe("tras un 409 la recarga puede cambiar los ids de los bloques o la página", () => {
    const bloqueDe = (vista: Vista, id: string): Bloque => vista.paginas[0]?.bloques.find((b) => b.id === id) as Bloque;
    const hechos2 = (vista: Vista): Bloque => bloqueDe(vista, "antecedentes-del-caso-2");
    const marcar = (vista: Vista): Vista => {
      bloqueDe(vista, "antecedentes-del-caso-3").segmentos = [{ texto: "Párrafo ya recargado." }];
      return vista;
    };

    async function conRecarga(recargada: Vista) {
      await abrirEditando({ put: new Falla(409, "El texto cambió; recargue el borrador."), vista: (n) => (n === 0 ? VISTA_BORRADOR : recargada) });
      fireEvent.click(botonDe(RELATO));
      const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
      fireEvent.input(campo, { target: { value: "Mi cambio" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
      await screen.findByRole("alert");
    }

    const intacto = async () => {
      await screen.findByText("Párrafo ya recargado.");
      expect(screen.getByRole("textbox", { name: "Texto del párrafo" })).toBeTruthy();
      expect((screen.getByRole("textbox", { name: "Texto del párrafo" }) as HTMLTextAreaElement).value).toBe("Mi cambio");
      expect(screen.getByRole("alert").textContent).toContain("El texto cambió");
      expect(screen.queryByText("Cargando el borrador…")).toBeNull();
    };

    it("el bloque cambia de id", async () => {
      const recargada = marcar(structuredClone(VISTA_BORRADOR));
      hechos2(recargada).id = "renombrado-2";
      await conRecarga(recargada);
      await intacto();
    });

    it("el bloque pasa a la página siguiente", async () => {
      const recargada = marcar(structuredClone(VISTA_BORRADOR));
      const bloque = hechos2(recargada);
      recargada.paginas[0]?.bloques.splice(recargada.paginas[0].bloques.indexOf(bloque), 1);
      recargada.paginas[1]?.bloques.unshift(bloque);
      await conRecarga(recargada);
      await intacto();
    });
  });

  it("un error de red se muestra en línea", async () => {
    await abrirEditando({
      put: () => {
        throw new TypeError("fetch failed");
      },
    });
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect((await screen.findByRole("alert")).textContent).toBe("No se pudo conectar con el servidor. Revise su conexión e intente de nuevo.");
  });

  it("solo ofrece restaurar si la pieza tiene ediciones y avisa de que restaura todo el texto", async () => {
    const { llamadas, veces } = await abrirEditando({ ediciones: piezaConEdicion(HECHOS, [0]), eliminar: ED });
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    const restaurar = screen.getByRole("button", { name: "Restaurar el texto de la IA" });
    expect(restaurar.getAttribute("title")).toMatch(/todos los párrafos/);
    const nota = document.getElementById(restaurar.getAttribute("aria-describedby") ?? "");
    expect(nota?.textContent).toMatch(/todos los párrafos de este texto/);
    fireEvent.click(restaurar);
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "DELETE")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "DELETE")?.url).toBe(`${BASE}/ediciones/${HECHOS}`);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(veces("GET", "/vista/borrador")).toBe(2);
    fireEvent.click(botonDe(/La salud y la continuidad/));
    await screen.findByRole("textbox", { name: "Título del bloque" });
    expect(screen.queryByRole("button", { name: "Restaurar el texto de la IA" })).toBeNull();
  });
});

describe("Texto sin guardar", () => {
  const AVISO = /Si continúa, pierde lo que escribió/;
  const interruptor = () => screen.getByRole("switch", { name: "Editar texto" }) as HTMLInputElement;

  async function escribirBorrador(texto = "Texto a medias") {
    const salida = await abrirEditando();
    fireEvent.click(botonDe(RELATO));
    const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
    fireEvent.input(campo, { target: { value: texto } });
    return { ...salida, campo };
  }

  it("apagar el modo con lo escrito pide confirmar y «Seguir editando» conserva el borrador", async () => {
    const { campo } = await escribirBorrador();
    fireEvent.click(interruptor());
    const dialogo = await screen.findByRole("dialog", { name: "Hay texto sin guardar", hidden: true });
    expect(within(dialogo).getByText(AVISO)).toBeTruthy();
    expect(interruptor().checked).toBe(true);
    fireEvent.click(within(dialogo).getByRole("button", { name: "Seguir editando", hidden: true }));
    await waitFor(() => expect(screen.queryByText(AVISO)).toBeNull());
    expect(interruptor().checked).toBe(true);
    expect(screen.getByRole("textbox", { name: "Texto del párrafo" })).toBe(campo);
    expect(campo.value).toBe("Texto a medias");
  });

  it("«Descartar el texto» apaga el modo y cierra el editor sin llamar a la API", async () => {
    const { llamadas } = await escribirBorrador();
    fireEvent.click(interruptor());
    fireEvent.click(await screen.findByRole("button", { name: "Descartar el texto", hidden: true }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(interruptor().checked).toBe(false);
    expect(botones()).toHaveLength(0);
    expect(llamadas.some((l) => l.metodo === "PUT")).toBe(false);
    fireEvent.click(interruptor());
    fireEvent.click(botonDe(RELATO));
    expect((screen.getByRole("textbox", { name: "Texto del párrafo" }) as HTMLTextAreaElement).value).toBe(parrafoMock(HECHOS, 1));
  });

  it("sin escribir, o con el texto igual al original, apaga el modo sin preguntar", async () => {
    await abrirEditando();
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(interruptor());
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(screen.queryByText(AVISO)).toBeNull();
    expect(interruptor().checked).toBe(false);
    expect(campo.isConnected).toBe(false);

    fireEvent.click(interruptor());
    fireEvent.click(botonDe(RELATO));
    const otro = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(otro, { target: { value: "Algo" } });
    fireEvent.input(otro, { target: { value: parrafoMock(HECHOS, 1) } });
    fireEvent.click(interruptor());
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(screen.queryByText(AVISO)).toBeNull();
  });

  it("tras guardar o cancelar deja de proteger el texto", async () => {
    await escribirBorrador();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    fireEvent.click(interruptor());
    await waitFor(() => expect(interruptor().checked).toBe(false));
    expect(screen.queryByText(AVISO)).toBeNull();
  });

  it("seguir un enlace con lo escrito pide confirmar antes de salir", async () => {
    await escribirBorrador();
    const enlace = document.createElement("a");
    enlace.href = "#/segunda";
    enlace.textContent = "Ir a los casos";
    document.body.append(enlace);
    try {
      fireEvent.click(enlace);
      expect(location.hash).toBe("");
      const dialogo = await screen.findByRole("dialog", { name: "Hay texto sin guardar", hidden: true });
      expect(within(dialogo).getByText(AVISO)).toBeTruthy();
      fireEvent.click(within(dialogo).getByRole("button", { name: "Seguir editando", hidden: true }));
      await waitFor(() => expect(screen.queryByText(AVISO)).toBeNull());
      expect(location.hash).toBe("");
      fireEvent.click(enlace);
      fireEvent.click(await screen.findByRole("button", { name: "Descartar el texto", hidden: true }));
      await waitFor(() => expect(location.hash).toBe("#/segunda"));
    } finally {
      enlace.remove();
    }
  });

  it("un enlace sin texto escrito navega sin preguntar", async () => {
    await abrirEditando();
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    const enlace = document.createElement("a");
    enlace.href = "#/segunda";
    document.body.append(enlace);
    try {
      fireEvent.click(enlace);
      await waitFor(() => expect(location.hash).toBe("#/segunda"));
      expect(screen.queryByText(AVISO)).toBeNull();
    } finally {
      enlace.remove();
    }
  });
});

describe("Párrafo abierto que desaparece tras recargar", () => {
  const AVISO = "El párrafo que estaba editando ya no existe en el borrador actualizado; su cambio no se guardó.";
  const sinParrafos = (): { vista: Vista; ediciones: EdicionesRespuesta } => {
    const vista = structuredClone(VISTA_BORRADOR);
    for (const pagina of vista.paginas) pagina.bloques = pagina.bloques.filter((b) => !(b.fuente?.pieza === HECHOS && b.fuente.parrafo >= 1));
    const ediciones = conEdiciones();
    const datos = ediciones.piezas[HECHOS];
    if (datos) ediciones.piezas[HECHOS] = { ...datos, parrafos: datos.parrafos.slice(0, 1) };
    return { vista, ediciones };
  };
  const habilitados = () => botones().filter((b) => !b.disabled);

  it("tras un 409 cierra el editor, avisa de que no se guardó y deja editar los demás párrafos", async () => {
    const reducida = sinParrafos();
    await abrirEditando({
      put: new Falla(409, "El texto cambió; recargue el borrador."),
      vista: (n) => (n === 0 ? VISTA_BORRADOR : reducida.vista),
      ediciones: (n) => (n === 0 ? ED : reducida.ediciones),
    });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(campo, { target: { value: "Mi cambio" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(within(hoja()).queryByText(RELATO)).toBeNull();
    await waitFor(() => expect(toasts.value.map((t) => [t.texto, t.tipo])).toEqual([[AVISO, "error"]]));
    expect(botones().length).toBeGreaterThan(0);
    expect(habilitados()).toHaveLength(botones().length);
    expect(habilitados()[0]?.title).toBe("");
    fireEvent.click(habilitados()[0] as HTMLElement);
    expect(await screen.findByRole("textbox")).toBeTruthy();
  });

  it("un párrafo borrado al guardarlo con éxito no avisa de nada y deja editar los demás", async () => {
    const reducida = sinParrafos();
    await abrirEditando({
      put: reducida.ediciones,
      vista: (n) => (n === 0 ? VISTA_BORRADOR : reducida.vista),
      ediciones: (n) => (n === 0 ? ED : reducida.ediciones),
    });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.input(campo, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    await waitFor(() => expect(within(hoja()).queryByText(RELATO)).toBeNull());
    await waitFor(() => expect(habilitados()).toHaveLength(botones().length));
    expect(botones().length).toBeGreaterThan(0);
    await new Promise((r) => setTimeout(r, 200));
    expect(toasts.value).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("si la unidad vuelve a existir, se abre con el texto actual y no con lo tecleado antes", async () => {
    const sin = sinParrafos();
    const edicion = (piezas: EdicionesRespuesta["piezas"]): EdicionDocumento => ({
      caso: CASO,
      activa: true,
      piezas,
      conflictos: [],
      recargar: vi.fn(async () => undefined),
    });
    const props = { citas: new Map(), apoderados: new Map(), seleccionada: null, plantilla: false, alCita: vi.fn(), alApoderado: vi.fn() };
    const { rerender } = render(<Documento vista={VISTA_BORRADOR} {...props} edicion={edicion(ED.piezas)} />);
    fireEvent.click(botonDe(RELATO));
    fireEvent.input(screen.getByRole("textbox", { name: "Texto del párrafo" }), { target: { value: "Tecleado y perdido" } });
    rerender(<Documento vista={sin.vista} {...props} edicion={edicion(sin.ediciones.piezas)} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(habilitados()).toHaveLength(botones().length);
    rerender(<Documento vista={VISTA_BORRADOR} {...props} edicion={edicion(ED.piezas)} />);
    fireEvent.click(botonDe(RELATO));
    expect((screen.getByRole("textbox", { name: "Texto del párrafo" }) as HTMLTextAreaElement).value).toBe(parrafoMock(HECHOS, 1));
  });
});

describe("Foco tras un guardado fallido", () => {
  it("el editor devuelve el foco al campo si se guardó con el botón", async () => {
    await abrirEditando({
      put: () => {
        (document.activeElement as HTMLElement | null)?.blur();
        return new Falla(422, "Las citas no coinciden con las de la IA.");
      },
    });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    const guardar = screen.getByRole("button", { name: "Guardar" });
    guardar.focus();
    fireEvent.click(guardar);
    await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(campo));
    expect(fireEvent.keyDown(campo, { key: "Escape" })).toBe(false);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("el editor no pierde el foco ni con un error de red al restaurar", async () => {
    await abrirEditando({
      ediciones: piezaConEdicion(HECHOS, [0]),
      eliminar: () => {
        (document.activeElement as HTMLElement | null)?.blur();
        throw new TypeError("fetch failed");
      },
    });
    fireEvent.click(botonDe(RELATO));
    const campo = await screen.findByRole("textbox", { name: "Texto del párrafo" });
    const restaurar = screen.getByRole("button", { name: "Restaurar el texto de la IA" });
    restaurar.focus();
    fireEvent.click(restaurar);
    await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(campo));
  });

  it("Aplicar devuelve el foco al botón tras un error", async () => {
    const { dialogo } = await abrirConflictos({
      resolver: () => {
        (document.activeElement as HTMLElement | null)?.blur();
        return new Falla(422, "En el conflicto 2 no puede conservar su versión.");
      },
    });
    const d = within(dialogo);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[0] as HTMLElement);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[1] as HTMLElement);
    const aplicar = d.getByRole("button", { name: "Aplicar" });
    aplicar.focus();
    fireEvent.click(aplicar);
    await d.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(d.getByRole("button", { name: "Aplicar" })));
  });

  it("Descartar mi edición devuelve el foco al botón tras un error", async () => {
    simularRed({
      ediciones: conEdiciones({ conflictos: [HUERFANA] }),
      eliminar: () => {
        (document.activeElement as HTMLElement | null)?.blur();
        return new Falla(404, "La pieza no existe.");
      },
    });
    await abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Resolver" }));
    const dialogo = (await screen.findByRole("heading", { name: "Resolver conflictos de edición" })).closest("dialog") as HTMLElement;
    const d = within(dialogo);
    const descartar = d.getByRole("button", { name: "Descartar mi edición" });
    descartar.focus();
    fireEvent.click(descartar);
    await d.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(d.getByRole("button", { name: "Descartar mi edición" })));
  });

  it("si el foco ya está en otro control durante la espera, no se le quita", async () => {
    let soltar: (v: unknown) => void = () => undefined;
    const pendiente = new Promise((r) => (soltar = r));
    const { dialogo } = await abrirConflictos({ resolver: () => pendiente });
    const d = within(dialogo);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[0] as HTMLElement);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[1] as HTMLElement);
    const aplicar = d.getByRole("button", { name: "Aplicar" });
    aplicar.focus();
    fireEvent.click(aplicar);
    const cerrar = d.getByRole("button", { name: "Cerrar" });
    cerrar.focus();
    soltar(new Falla(422, "Error."));
    await d.findByRole("alert");
    expect(document.activeElement).toBe(cerrar);
  });
});

describe("Marca Editado y avisos", () => {
  it("marca la unidad editada aunque el modo de edición esté apagado", async () => {
    simularRed({ ediciones: piezaConEdicion(HECHOS, [1]) });
    await abrir();
    await waitFor(() => expect(hoja().querySelectorAll(".bor-editado").length).toBe(1));
    expect(within(unidadDe(RELATO)).getByText("Editado")).toBeTruthy();
    expect(screen.getByText("Editado").closest(".bor-unidad")?.querySelectorAll("button").length).toBe(0);
    expect(botones()).toHaveLength(0);
  });

  it("marca una sola vez, en el primer párrafo, la pieza a la que solo se le quitaron párrafos", async () => {
    simularRed({ ediciones: piezaSinParrafos(HECHOS) });
    await abrir();
    await waitFor(() => expect(hoja().querySelectorAll(".bor-editado").length).toBe(1));
    const marca = screen.getByText("Con párrafos quitados");
    expect(marca.getAttribute("title")).toMatch(/restaurarlo/);
    expect(marca.closest(".bor-unidad")).toBe(unidadDe(new RegExp(parrafoMock(HECHOS, 0).slice(0, 30))));
    expect(marca.closest(".bor-unidad")?.classList.contains("editada")).toBe(false);
    expect(screen.queryByText("Editado", { exact: true })).toBeNull();
  });

  it("una pieza sin cambios no lleva marca de párrafos quitados", async () => {
    simularRed({ ediciones: ED });
    await abrir();
    await screen.findByRole("switch", { name: "Editar texto" });
    expect(screen.queryByText("Con párrafos quitados")).toBeNull();
  });

  it("al abrir cualquier párrafo de una pieza con párrafos quitados se puede restaurar el texto de la IA", async () => {
    const { llamadas } = await abrirEditando({ ediciones: piezaSinParrafos(HECHOS), eliminar: ED });
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(screen.getByRole("button", { name: "Restaurar el texto de la IA" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "DELETE")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "DELETE")?.url).toBe(`${BASE}/ediciones/${HECHOS}`);
  });

  it("muestra los avisos de la pieza después de su última unidad solo en modo de edición", async () => {
    simularRed({ ediciones: piezaConEdicion(HECHOS, [1], ["ALERTA: el texto dice «hace poco» sin fecha."]) });
    await abrir();
    await screen.findByRole("switch", { name: "Editar texto" });
    expect(screen.queryByText(/hace poco/)).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Editar texto" }));
    const aviso = screen.getByText(/hace poco/).closest(".bor-avisos-pieza") as HTMLElement;
    expect(aviso).toBeTruthy();
    expect(aviso.previousElementSibling).toBe(unidadDe(/Con fundamento en lo anterior, solicitó/));
    expect(hoja().querySelectorAll(".bor-avisos-pieza").length).toBe(1);
  });
});

describe("Documento con unidades de edición", () => {
  const bloque = (id: string, tipo: Bloque["tipo"], texto: string, fuente?: Bloque["fuente"]): Bloque => ({
    id,
    tipo,
    origen: "modelo",
    seccion: null,
    segmentos: [{ texto }],
    fuente: fuente ?? null,
  });
  const P = "apertura.impugnacion";
  const VISTA: Vista = {
    tipo: "borrador",
    sha256: "x",
    citas: [],
    indice: [],
    paginas: [
      {
        bloques: [
          bloque("p0a", "parrafo", "Antes de la imagen.", { pieza: P, parrafo: 0 }),
          bloque("q0", "cita_bloque", "“Fragmento citado literal.”"),
          bloque("p0b", "parrafo", "⟦INSERTAR IMAGEN: croquis⟧", { pieza: P, parrafo: 0 }),
        ],
      },
      {
        bloques: [
          bloque("p0c", "parrafo", "Después de la imagen.", { pieza: P, parrafo: 0 }),
          bloque("p1", "parrafo", "Segundo párrafo.", { pieza: P, parrafo: 1 }),
          bloque("t", "parrafo", "Texto de plantilla sin fuente."),
        ],
      },
    ],
  };
  const piezas = { [P]: { parrafos: ["Antes de la imagen. ⟦imagen · croquis⟧ Después de la imagen.", "Segundo párrafo."], editados: [], modificada: false, avisos: [] } };

  function documento(extra: Partial<EdicionDocumento> = {}) {
    const recargar = vi.fn(async () => undefined);
    const edicion: EdicionDocumento = { caso: CASO, activa: true, piezas, conflictos: [], recargar, ...extra };
    const salida = render(<Documento vista={VISTA} citas={new Map()} apoderados={new Map()} seleccionada={null} plantilla={false} alCita={vi.fn()} alApoderado={vi.fn()} edicion={edicion} />);
    return { recargar, ...salida };
  }

  it("un párrafo cortado por una imagen, con su cita en bloque, es una sola unidad con un botón", () => {
    documento();
    expect(screen.getAllByRole("button", { name: "Editar párrafo" })).toHaveLength(2);
    const primera = screen.getByText("Antes de la imagen.").closest(".bor-unidad") as HTMLElement;
    expect(primera.querySelectorAll("button").length).toBe(1);
    expect(screen.getByText("Texto de plantilla sin fuente.").closest(".bor-unidad")).toBeNull();
  });

  it("abrirla reemplaza toda la unidad, también la parte de la otra página, y deja el resto", () => {
    documento();
    fireEvent.click(screen.getAllByRole("button", { name: "Editar párrafo" })[0] as HTMLElement);
    const campo = screen.getByRole("textbox", { name: "Texto del párrafo" }) as HTMLTextAreaElement;
    expect(campo.value).toBe(piezas[P].parrafos[0]);
    for (const texto of ["Antes de la imagen.", "Fragmento citado literal", "INSERTAR IMAGEN", "Después de la imagen."]) {
      expect(screen.queryByText(new RegExp(texto))).toBeNull();
    }
    expect(screen.getByText("Segundo párrafo.")).toBeTruthy();
    expect(screen.getByText("Texto de plantilla sin fuente.")).toBeTruthy();
  });

  it("con una unidad abierta, las demás no se pueden abrir", () => {
    documento();
    fireEvent.click(screen.getAllByRole("button", { name: "Editar párrafo" })[0] as HTMLElement);
    const otra = screen.getByRole("button", { name: "Editar párrafo" }) as HTMLButtonElement;
    expect(otra.disabled).toBe(true);
    expect(otra.title).toMatch(/Guarde o cancele/);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect((screen.getAllByRole("button", { name: "Editar párrafo" })[1] as HTMLButtonElement).disabled).toBe(false);
  });

  it("la pieza en conflicto no se puede editar", () => {
    documento({ conflictos: [P] });
    for (const boton of screen.getAllByRole("button", { name: "Editar párrafo" })) {
      expect((boton as HTMLButtonElement).disabled).toBe(true);
      expect(boton.getAttribute("title")).toMatch(/Resuelva el conflicto/);
    }
  });

  it("sin modo de edición no hay botones y la unidad editada solo lleva la marca", () => {
    documento({ activa: false, piezas: { [P]: { ...(piezas[P] as object), editados: [1] } as (typeof piezas)[typeof P] } });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getAllByText("Editado")).toHaveLength(1);
    expect(screen.getByText("Segundo párrafo.").closest(".bor-unidad")?.contains(screen.getByText("Editado"))).toBe(true);
  });

  it("sin datos de la pieza no hay botón", () => {
    documento({ piezas: {} });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("apagar el modo cierra el editor abierto", () => {
    const { rerender, recargar } = documento();
    fireEvent.click(screen.getAllByRole("button", { name: "Editar párrafo" })[0] as HTMLElement);
    expect(screen.getByRole("textbox")).toBeTruthy();
    const edicion: EdicionDocumento = { caso: CASO, activa: false, piezas, conflictos: [], recargar };
    rerender(<Documento vista={VISTA} citas={new Map()} apoderados={new Map()} seleccionada={null} plantilla={false} alCita={vi.fn()} alApoderado={vi.fn()} edicion={edicion} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Antes de la imagen.")).toBeTruthy();
  });
});

describe("Conflictos de edición", () => {
  it("avisa sobre el documento cuántos conflictos hay y ofrece resolver", async () => {
    simularRed({ ediciones: conEdiciones({ conflictos: [CONFLICTO, HUERFANA] }) });
    await abrir();
    const aviso = await screen.findByText("Hay 2 conflictos entre sus ediciones y la corrección de la IA");
    expect(within(aviso.closest(".aviso") as HTMLElement).getByRole("button", { name: "Resolver" })).toBeTruthy();
    cleanup();
    simularRed({ ediciones: conEdiciones({ conflictos: [CONFLICTO] }) });
    await abrir();
    expect(await screen.findByText("Hay 1 conflicto entre sus ediciones y la corrección de la IA")).toBeTruthy();
  });

  it("sin conflictos no hay aviso", async () => {
    simularRed({ ediciones: ED });
    await abrir();
    await screen.findByRole("switch", { name: "Editar texto" });
    expect(screen.queryByRole("button", { name: "Resolver" })).toBeNull();
    expect(screen.queryByText(/conflicto/)).toBeNull();
  });

  it("muestra cada conflicto con su etiqueta, el contexto atenuado y las dos versiones con radios", async () => {
    const { dialogo } = await abrirConflictos();
    const d = within(dialogo);
    expect(d.getByRole("heading", { name: "Antecedentes: hechos", level: 3 })).toBeTruthy();
    expect(d.getByText("Contexto previo al choque.").closest(".bor-conf-ok")).toBeTruthy();
    expect(d.getByText("Contexto intermedio.").closest(".bor-conf-ok")).toBeTruthy();
    expect(d.getAllByRole("radio", { name: "Su versión" })).toHaveLength(2);
    expect(d.getAllByRole("radio", { name: "Versión de la corrección" })).toHaveLength(2);
    expect(d.getByText("Mi texto A.")).toBeTruthy();
    expect(d.getByText("Texto de la corrección A.")).toBeTruthy();
    expect(d.getByText("⟦cita c9 · T-1 de 2020⟧").classList.contains("bor-ficha")).toBe(true);
    expect((d.getByRole("button", { name: "Aplicar" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("desactiva «Su versión» y explica por qué cuando mio_permitido es falso", async () => {
    const { dialogo } = await abrirConflictos();
    const [primera, segunda] = within(dialogo).getAllByRole("radio", { name: "Su versión" }) as HTMLInputElement[];
    expect(primera?.disabled).toBe(false);
    expect(segunda?.disabled).toBe(true);
    const explicacion = within(dialogo).getAllByText(
      "Su versión cambia las citas respecto de la corrección —los números de cita pueden haberse reasignado—; elija la versión de la corrección.",
    );
    expect(explicacion).toHaveLength(1);
    expect(segunda?.getAttribute("aria-describedby")).toContain(explicacion[0]?.id);
  });

  it("Aplicar envía una elección por trozo en conflicto, en orden, recarga y cierra al resolver todo", async () => {
    const { dialogo, llamadas } = await abrirConflictos({
      resolver: conEdiciones(),
      ediciones: (n) => (n === 0 ? conEdiciones({ conflictos: [CONFLICTO] }) : ED),
    });
    const d = within(dialogo);
    fireEvent.click(d.getAllByRole("radio", { name: "Su versión" })[0] as HTMLElement);
    expect((d.getByRole("button", { name: "Aplicar" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[1] as HTMLElement);
    const aplicar = d.getByRole("button", { name: "Aplicar" }) as HTMLButtonElement;
    expect(aplicar.disabled).toBe(false);
    fireEvent.click(aplicar);
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "POST" && l.url.endsWith("/resolver"))).toBe(true));
    const envio = llamadas.find((l) => l.url.endsWith("/resolver"));
    expect(envio?.url).toBe(`${BASE}/ediciones/${HECHOS}/resolver`);
    expect(envio?.cuerpo).toEqual({ elecciones: ["mio", "nuevo"] });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Resolver conflictos de edición" })).toBeNull());
    expect(screen.queryByText(/conflicto entre sus ediciones/)).toBeNull();
    expect(llamadas.filter((l) => l.metodo === "GET" && l.url.endsWith("/vista/borrador"))).toHaveLength(2);
  });

  it("muestra el 422 del servidor dentro del conflicto y deja elegir de nuevo", async () => {
    const { dialogo } = await abrirConflictos({ resolver: new Falla(422, "En el conflicto 2 no puede conservar su versión: cambia las citas o imágenes del texto.") });
    const d = within(dialogo);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[0] as HTMLElement);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[1] as HTMLElement);
    fireEvent.click(d.getByRole("button", { name: "Aplicar" }));
    const alerta = await d.findByRole("alert");
    expect(alerta.textContent).toBe("En el conflicto 2 no puede conservar su versión: cambia las citas o imágenes del texto.");
    expect((d.getByRole("button", { name: "Aplicar" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("un 409 al resolver recarga el borrador", async () => {
    const { dialogo, veces } = await abrirConflictos({ resolver: new Falla(409, "La pieza no tiene un conflicto pendiente.") });
    const d = within(dialogo);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[0] as HTMLElement);
    fireEvent.click(d.getAllByRole("radio", { name: "Versión de la corrección" })[1] as HTMLElement);
    fireEvent.click(d.getByRole("button", { name: "Aplicar" }));
    expect((await d.findByRole("alert")).textContent).toBe("La pieza no tiene un conflicto pendiente.");
    await waitFor(() => expect(veces("GET", "/ediciones")).toBe(2));
  });

  it("una pieza huérfana solo ofrece descartar la edición", async () => {
    const { llamadas } = simularRed({
      ediciones: (n) => (n === 0 ? conEdiciones({ conflictos: [HUERFANA] }) : ED),
      eliminar: ED,
    });
    await abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Resolver" }));
    const dialogo = (await screen.findByRole("heading", { name: "Resolver conflictos de edición" })).closest("dialog") as HTMLElement;
    const d = within(dialogo);
    expect(d.getByRole("heading", { name: "Antecedentes: contestación de EPS Horizonte", level: 3 })).toBeTruthy();
    expect(d.queryByRole("radio")).toBeNull();
    expect(d.queryByRole("button", { name: "Aplicar" })).toBeNull();
    fireEvent.click(d.getByRole("button", { name: "Descartar mi edición" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "DELETE")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "DELETE")?.url).toBe(`${BASE}/ediciones/${CONTESTACION}`);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Resolver conflictos de edición" })).toBeNull());
  });

  it("una pieza huérfana muestra el texto del usuario para copiarlo antes de descartarlo", async () => {
    const huerfana: ConflictoEdicion = {
      ...HUERFANA,
      pieza: "consideraciones.bloques.1.texto",
      etiqueta: "Consideraciones: bloque «Continuidad del servicio»",
      trozos: [{ tipo: "ok", parrafos: ["Mi primer párrafo huérfano.", "Mi segundo párrafo huérfano."] }],
    };
    simularRed({ ediciones: conEdiciones({ conflictos: [huerfana] }) });
    await abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Resolver" }));
    const dialogo = (await screen.findByRole("heading", { name: "Resolver conflictos de edición" })).closest("dialog") as HTMLElement;
    const d = within(dialogo);
    expect(d.getByRole("heading", { name: "Consideraciones: bloque «Continuidad del servicio»", level: 3 })).toBeTruthy();
    expect(d.getByText("Su texto, por si quiere copiarlo antes de descartarlo:")).toBeTruthy();
    expect(d.getByText("Mi primer párrafo huérfano.")).toBeTruthy();
    expect(d.getByText("Mi segundo párrafo huérfano.")).toBeTruthy();
    expect(d.queryByRole("radio")).toBeNull();
    expect(d.getByRole("button", { name: "Descartar mi edición" })).toBeTruthy();
  });

  it("una pieza huérfana sin texto no muestra el bloque de texto", async () => {
    simularRed({ ediciones: conEdiciones({ conflictos: [HUERFANA] }) });
    await abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Resolver" }));
    const dialogo = (await screen.findByRole("heading", { name: "Resolver conflictos de edición" })).closest("dialog") as HTMLElement;
    expect(within(dialogo).queryByText("Su texto, por si quiere copiarlo antes de descartarlo:")).toBeNull();
  });

  it("Cerrar deja el aviso y los conflictos pendientes", async () => {
    await abrirConflictos();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("heading", { name: "Resolver conflictos de edición" })).toBeNull();
    expect(screen.getByText("Hay 1 conflicto entre sus ediciones y la corrección de la IA")).toBeTruthy();
  });

  it("no se muestran conflictos si el servidor dice que no se puede editar", async () => {
    simularRed({ ediciones: { editable: false, motivo: "Hay una redacción en curso para este caso.", piezas: {}, conflictos: [CONFLICTO] } });
    await abrir();
    await screen.findByText("Quedan 7 puntos por revisar");
    expect(screen.queryByRole("button", { name: "Resolver" })).toBeNull();
  });
});

describe("Barra inferior con conflictos", () => {
  it("desactiva Pedir correcciones y Pasar a la decisión y da el motivo", async () => {
    simularRed({ ediciones: conEdiciones({ conflictos: [CONFLICTO] }) });
    await abrir();
    await screen.findByRole("button", { name: "Resolver" });
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Pasar a la decisión").closest("a")?.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("Pasar a la decisión").closest("a")?.hasAttribute("href")).toBe(false);
    expect(screen.getByText("Resuelva los conflictos de edición antes de seguir.")).toBeTruthy();
    expect(screen.getByText("Hay 1 conflicto de edición", { selector: "b" })).toBeTruthy();
  });

  it("sin conflictos siguen activos", async () => {
    simularRed({ ediciones: ED });
    await abrir();
    await waitFor(() => expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByText("Pasar a la decisión").closest("a")?.getAttribute("href")).toBe(`#/segunda/${CASO}/decision`);
    expect(screen.queryByText("Resuelva los conflictos de edición antes de seguir.")).toBeNull();
  });
});

describe("Pedir correcciones con ediciones", () => {
  it("avisa de que las ediciones se conservan", async () => {
    simularRed({ ediciones: ED });
    await abrir();
    await waitFor(() => expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Pedir correcciones" }));
    await screen.findByRole("heading", { name: "Pedir correcciones al borrador" });
    expect(screen.getByText("Sus ediciones se conservan; si la corrección cambia los mismos párrafos, se le pedirá elegir.")).toBeTruthy();
  });
});

describe("Revisados al editar", () => {
  it("lo revisado sobrevive a la recarga con otro sha tras guardar una edición", async () => {
    const nueva: Vista = structuredClone(VISTA_BORRADOR);
    nueva.sha256 = "3".repeat(64);
    await abrirEditando({
      put: ED,
      vista: (n) => (n === 0 ? VISTA_BORRADOR : nueva),
    });
    const marca = within(panel()).getByRole("button", { name: "Revisado: Sentencia T-999 de 2019" });
    fireEvent.click(marca);
    expect(screen.getByText("Quedan 6 puntos por revisar")).toBeTruthy();
    fireEvent.click(botonDe(RELATO));
    await screen.findByRole("textbox", { name: "Texto del párrafo" });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(within(panel()).getByRole("button", { name: "Revisado: Sentencia T-999 de 2019" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Quedan 6 puntos por revisar")).toBeTruthy();
    expect(JSON.parse(localStorage.getItem(claveRevisados(CASO)) ?? "null")).toEqual(["cita-c3-rechazada-sentencia T-999 de 2019"]);
  });

  it("al volver a leer las alertas se descartan las claves que ya no existen", async () => {
    localStorage.setItem(claveRevisados(CASO), JSON.stringify(["cita-c3-rechazada-sentencia T-999 de 2019", "cita-c9-verificada", "alerta-apertura-ya no existe"]));
    simularRed();
    await abrir();
    await screen.findByText("Quedan 6 puntos por revisar");
    fireEvent.click(within(panel()).getByRole("button", { name: "Revisado: Sentencia SU-508 de 2020" }));
    expect(JSON.parse(localStorage.getItem(claveRevisados(CASO)) ?? "null").sort()).toEqual(["cita-c2-revisar-sentencia SU-508 de 2020", "cita-c3-rechazada-sentencia T-999 de 2019"]);
  });

  it("sin poder leer /estado no se pierden las claves de alertas al marcar una cita", async () => {
    const alerta = "alerta-apertura-ALERTA: antecedentes: tiene 1202 palabras, por encima del máximo esperado (510 a 1140).";
    localStorage.setItem(claveRevisados(CASO), JSON.stringify([alerta]));
    simularRed({ estado: new Falla(500, "Falla") });
    await abrir();
    await waitFor(() => expect(screen.getByText("No se pudieron leer las alertas del caso; se muestran solo las citas.")).toBeTruthy());
    fireEvent.click(within(panel()).getByRole("button", { name: "Revisado: Sentencia T-999 de 2019" }));
    expect(JSON.parse(localStorage.getItem(claveRevisados(CASO)) ?? "null").sort()).toEqual([alerta, "cita-c3-rechazada-sentencia T-999 de 2019"].sort());
  });

  it("si /estado llega sin resumen no se pierden las claves de alertas al marcar una cita", async () => {
    const alerta = "alerta-apertura-ALERTA: antecedentes: tiene 1202 palabras, por encima del máximo esperado (510 a 1140).";
    localStorage.setItem(claveRevisados(CASO), JSON.stringify([alerta]));
    simularRed({ estado: { ...ESTADO_BORRADOR, resumen: null } });
    await abrir();
    await waitFor(() => expect(screen.getByText("Quedan 2 puntos por revisar")).toBeTruthy());
    fireEvent.click(within(panel()).getByRole("button", { name: "Revisado: Sentencia T-999 de 2019" }));
    expect(JSON.parse(localStorage.getItem(claveRevisados(CASO)) ?? "null").sort()).toEqual([alerta, "cita-c3-rechazada-sentencia T-999 de 2019"].sort());
  });

  it("si /estado tarda no se pierden las claves de alertas al marcar una cita antes de que llegue", async () => {
    const alerta = "alerta-apertura-ALERTA: antecedentes: tiene 1202 palabras, por encima del máximo esperado (510 a 1140).";
    localStorage.setItem(claveRevisados(CASO), JSON.stringify([alerta]));
    let soltar: (v: unknown) => void = () => undefined;
    const pendiente = new Promise((r) => (soltar = r));
    simularRed({ estado: () => pendiente });
    await abrir();
    fireEvent.click(within(panel()).getByRole("button", { name: "Revisado: Sentencia T-999 de 2019" }));
    soltar(ESTADO_BORRADOR);
    await screen.findByText("Los antecedentes son más largos de lo esperado");
    expect(within(panel()).getByRole("button", { name: "Revisado: Los antecedentes son más largos de lo esperado" }).getAttribute("aria-pressed")).toBe("true");
    expect(JSON.parse(localStorage.getItem(claveRevisados(CASO)) ?? "null").sort()).toEqual([alerta, "cita-c3-rechazada-sentencia T-999 de 2019"].sort());
  });
});

describe("estilos.css: barra del documento en pantallas angostas", () => {
  const css = readFileSync(join(import.meta.dirname, "estilos.css"), "utf8");
  const bloque = (consulta: string): string => {
    const inicio = css.indexOf(`@media ${consulta} {`);
    if (inicio < 0) return "";
    const abre = css.indexOf("{", inicio);
    let nivel = 0;
    for (let i = abre; i < css.length; i++) {
      if (css[i] === "{") nivel++;
      else if (css[i] === "}" && --nivel === 0) return css.slice(abre + 1, i);
    }
    return "";
  };
  const rem = (texto: string): number => Number(/scroll-padding-top:\s*([\d.]+)rem/.exec(texto)?.[1] ?? 0);

  it("la barra se parte en dos filas, así que el margen de desplazamiento cubre su alto de dos filas", () => {
    expect(css).toMatch(/\.bor-doc-barra\s*\{[^}]*flex-wrap:\s*wrap/);
    const barra = 3.5 + 2 * 3.1;
    expect(rem(bloque("(max-width: 560px)"))).toBeGreaterThan(barra);
  });

  it("el margen de una sola fila de escritorio sigue cubriendo la barra de una fila", () => {
    expect(rem(css)).toBeGreaterThan(3.5 + 3.1);
  });
});
