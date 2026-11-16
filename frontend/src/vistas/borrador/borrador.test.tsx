import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jobActual } from "../../estado";
import { claveRevisados } from "./datos";
import Borrador from "./index";
import { CASO_MOCK_BORRADOR, ESTADO_BORRADOR, VISTA_BORRADOR } from "./mock";
import type { EstadoCaso, LlamadaBitacora } from "./tipos";

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

const COMPETENCIA =
  "Este Despacho es competente para conocer y resolver el recurso de impugnación interpuesto contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de amparo. En su condición de superior funcional, le corresponde adelantar un examen integral de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina fijada por la Corte Constitucional.";

const llamada = (nodo: string, modelo_pedido: string, modelo_efectivo: string | null, extra: Partial<LlamadaBitacora> = {}): LlamadaBitacora => ({
  nodo,
  intento: 1,
  proveedor: "anthropic",
  modelo_pedido,
  modelo_efectivo,
  ...extra,
});

const conBitacora = (bitacora: LlamadaBitacora[] | null): EstadoCaso => {
  const estado = structuredClone(ESTADO_BORRADOR);
  if (estado.resumen) estado.resumen.bitacora = bitacora;
  return estado;
};

const seccionRedaccion = () => screen.getByRole("heading", { name: "Quién redactó" }).closest("section") as HTMLElement;

const CLAVE = claveRevisados(CASO, VISTA_BORRADOR.sha256);

async function abrir() {
  const vista = render(<Borrador caso={CASO} />);
  await screen.findByRole("heading", { level: 3, name: /ASUNTO/ });
  return vista;
}

const panel = () => screen.getByRole("complementary", { name: "Antes de decidir" });
const indice = () => screen.getByRole("navigation", { name: "Contenido del borrador" });
const hoja = () => screen.getByRole("article", { name: /Borrador del fallo/ });
const resumenPanel = () => panel().querySelector(".bor-panel-resumen")?.textContent ?? "";
const citaEnTexto = (nombre: RegExp) => within(hoja()).getByRole("button", { name: nombre });
const filaDe = (titulo: RegExp) => within(panel()).getByRole("button", { name: titulo, expanded: false });
const marcaRevisado = (titulo: string) => within(panel()).getByRole("button", { name: `Revisado: ${titulo}` });

async function abrirDetalleEnTexto(titulo: RegExp, popover: string) {
  fireEvent.click(filaDe(titulo));
  fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
  return await screen.findByRole("region", { name: popover });
}

beforeEach(() => {
  location.hash = "";
  jobActual.value = null;
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Borrador con datos", () => {
  it("pinta cabecera, hoja con bloques, tabla agrupada y citas por estado", async () => {
    simularRed();
    await abrir();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Marta Inés Quintero Bedoya c. EPS Horizonte Salud S.A.S.");
    expect(screen.getByText(/Radicado 05001 40 88 009 2026 00412 01/)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "II. ANTECEDENTES DEL CASO" })).toBeTruthy();
    expect(hoja().querySelectorAll("table.bor-tabla").length).toBe(2);
    expect(hoja().querySelectorAll("ul.bor-lista li").length).toBe(1);
    const t760 = within(hoja()).getByRole("button", { name: /sentencia T-760 de 2008/ });
    expect(t760.classList.contains("verificada")).toBe(true);
    expect(citaEnTexto(/SU-508/).classList.contains("revisar")).toBe(true);
    expect(citaEnTexto(/T-999/).classList.contains("rechazada")).toBe(true);
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

  it("agrupa la revisión por urgencia con citas y alertas reales y pliega lo comprobado", async () => {
    simularRed();
    await abrir();
    const lateral = within(panel());
    expect(resumenPanel()).toBe("Lleva 0 de 7 revisados. Nada de esto bloquea la decisión.");
    expect(lateral.getByRole("progressbar", { name: "Puntos revisados" }).getAttribute("aria-valuemax")).toBe("7");
    const grupo = (nombre: string) => lateral.getByRole("heading", { name: nombre }).parentElement as HTMLElement;
    expect(grupo("Corregir antes de firmar").textContent).toContain("1 de 1");
    expect(grupo("Revisar").textContent).toContain("4 de 4");
    expect(grupo("Para tener en cuenta").textContent).toContain("2 de 2");
    expect(lateral.getByText("Sentencia T-999 de 2019")).toBeTruthy();
    expect(lateral.getByText("Los antecedentes son más largos de lo esperado")).toBeTruthy();
    expect(lateral.getByText("El modelo leyó solo una parte de este documento")).toBeTruthy();
    expect(lateral.queryByText(/^ALERTA:/)).toBeNull();
    expect(lateral.queryByText(/^BLOQUEA:/)).toBeNull();
    expect(lateral.queryByText(/La cita c3 \(/)).toBeNull();
    expect(lateral.queryByText("Sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa")).toBeNull();
    const comprobado = lateral.getByRole("button", { name: /Comprobado/ });
    expect(comprobado.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(comprobado);
    expect(comprobado.getAttribute("aria-expanded")).toBe("true");
    expect(lateral.getByText("Sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa")).toBeTruthy();
    expect(lateral.getByText("Quién impugna")).toBeTruthy();
  });

  it("arma el índice con marcas de citas por revisar, anexos y subtítulos", async () => {
    simularRed();
    await abrir();
    const contenido = within(indice());
    expect(contenido.getByRole("button", { name: /V\. Consideraciones/ })).toBeTruthy();
    const minimo = contenido.getByRole("button", { name: "El mínimo vital" });
    expect(minimo.parentElement?.classList.contains("sub")).toBe(true);
    expect(within(contenido.getByRole("button", { name: /V\. Consideraciones/ })).getByText(/2 citas por revisar/)).toBeTruthy();
    expect(within(contenido.getByRole("button", { name: /La salud y la continuidad/ })).getByText(/1 cita por revisar/)).toBeTruthy();
    expect(contenido.getByRole("button", { name: "Informe de citas" }).parentElement?.classList.contains("anexo")).toBe(true);
    await waitFor(() => expect(indice().querySelectorAll("[aria-current=location]").length).toBe(1));
  });

  it("compara el borrador con Jev dentro de la fila que no coincide", async () => {
    simularRed();
    await abrir();
    expect(screen.queryByRole("heading", { name: "Segunda lectura de Jev" })).toBeNull();
    fireEvent.click(filaDe(/Sentido del fallo de primera instancia/));
    const fila = within(panel());
    expect(fila.getByText("El borrador dice")).toBeTruthy();
    expect(fila.getByText("Jev lee en el expediente")).toBeTruthy();
    expect(fila.getByText("Declaró improcedente la acción de tutela")).toBeTruthy();
    expect(fila.getByText("Niega el amparo")).toBeTruthy();
    expect(fila.getByText(/97 % de confianza/)).toBeTruthy();
    expect(fila.getByText(/Solo compara con al menos 80 % de confianza/)).toBeTruthy();
  });

  it("muestra Competencia como un solo párrafo de plantilla", async () => {
    simularRed();
    await abrir();
    const encabezado = within(hoja()).getByRole("heading", { level: 4, name: "Competencia" });
    const parrafo = encabezado.nextElementSibling as HTMLElement;
    expect(parrafo.tagName).toBe("P");
    expect(parrafo.textContent).toBe(COMPETENCIA);
    expect(parrafo.classList.contains("bor-tpl")).toBe(true);
    const siguiente = parrafo.nextElementSibling as HTMLElement;
    expect(siguiente.tagName).toBe("H4");
    expect(siguiente.textContent).toMatch(/^Presupuestos generales de procedibilidad/);
  });

  it("deja la tabla de citas con sus nueve columnas en un contenedor propio con desplazamiento", async () => {
    simularRed();
    await abrir();
    const caja = within(hoja()).getByRole("region", { name: /desplazable horizontalmente/ });
    expect(caja.classList.contains("bor-tabla-caja")).toBe(true);
    expect(caja.getAttribute("tabindex")).toBe("0");
    const tabla = caja.querySelector("table") as HTMLTableElement;
    expect(tabla.classList.contains("bor-tabla-ancha")).toBe(true);
    expect(tabla.style.getPropertyValue("--columnas")).toBe("9");
    const encabezados = Array.from(tabla.rows[0]?.cells ?? []).map((c) => c.textContent);
    expect(encabezados).toEqual(["Sentencia", "Estado", "Cobertura", "Palabras", "Sección", "M.P. (dataset)", "URL", "Texto citado", "Motivos"]);
    for (const fila of Array.from(tabla.rows)) expect(fila.cells.length).toBe(9);
    expect(hoja().querySelectorAll("table.bor-tabla-ancha").length).toBe(1);
    expect(hoja().querySelectorAll(".bor-tabla-caja[role=region]").length).toBe(1);
  });

  it("no marca como ancha la tabla de dos columnas del encabezado", async () => {
    simularRed();
    await abrir();
    const tablas = Array.from(hoja().querySelectorAll("table.bor-tabla"));
    const dos = tablas.find((t) => t.classList.contains("bor-tabla-2")) as HTMLElement;
    expect(dos.classList.contains("bor-tabla-ancha")).toBe(false);
    expect(dos.closest(".bor-tabla-caja")?.getAttribute("role")).toBeNull();
    expect(dos.closest(".bor-tabla-caja")?.hasAttribute("tabindex")).toBe(false);
  });

  it("no muestra filas de Jev si no hay lecturas", async () => {
    const estado = structuredClone(ESTADO_BORRADOR);
    if (estado.resumen) estado.resumen.jev_metadatos = null;
    simularRed({ estado });
    await abrir();
    await screen.findByText("Los antecedentes son más largos de lo esperado");
    expect(within(panel()).queryByText("Sentido del fallo de primera instancia")).toBeNull();
    expect(within(panel()).queryByText("Quién impugna")).toBeNull();
  });

  it("muestra completa una alerta de formato desconocido y las alertas en lista", async () => {
    const estado = structuredClone(ESTADO_BORRADOR);
    if (estado.resumen) {
      estado.resumen.alertas = [
        "BLOQUEA: el nodo apertura falló de un modo que nadie previó",
        "ALERTA: otra cosa que tampoco se reconoce ['A', 'B']",
      ];
    }
    simularRed({ estado });
    await abrir();
    const lateral = within(panel());
    expect(lateral.getByText("el nodo apertura falló de un modo que nadie previó")).toBeTruthy();
    expect(lateral.getByText("otra cosa que tampoco se reconoce ['A', 'B']")).toBeTruthy();
    const grupo = (nombre: string) => lateral.getByRole("heading", { name: nombre }).parentElement as HTMLElement;
    expect(grupo("Corregir antes de firmar").textContent).toContain("2 de 2");
  });
});

describe("Modelo que redactó el borrador", () => {
  it("indica el modelo de cada parte redactada por el modelo y deja fuera las lecturas de Jev", async () => {
    simularRed();
    await abrir();
    const seccion = await waitFor(() => seccionRedaccion());
    const filas = within(seccion).getAllByRole("listitem");
    expect(filas.length).toBe(2);
    expect(filas[0]?.textContent).toContain("Secciones II a IV");
    expect(filas[0]?.textContent).toContain("Sonnet 5.5");
    expect(filas[1]?.textContent).toContain("Sección V");
    expect(filas[1]?.textContent).toContain("Sonnet 5.5");
    expect(seccion.textContent).not.toContain("Se pidió");
    expect(seccion.textContent).not.toMatch(/jev/i);
  });

  it("con varios intentos usa el modelo del último y avisa si el efectivo no es el pedido", async () => {
    const estado = conBitacora([
      llamada("apertura", "claude-haiku-5-5", "claude-haiku-5-5"),
      llamada("apertura", "claude-haiku-5-5", "claude-sonnet-5-5", { intento: 2 }),
      llamada("consideraciones", "claude-opus-5-5", "claude-opus-5-5"),
      llamada("consideraciones", "claude-sonnet-5-5", "claude-sonnet-5-5", { intento: 2 }),
    ]);
    simularRed({ estado });
    await abrir();
    const filas = within(await waitFor(() => seccionRedaccion())).getAllByRole("listitem");
    expect(filas[0]?.textContent).toContain("Se pidió Haiku 5.5; respondió Sonnet 5.5.");
    expect(filas[1]?.textContent).toContain("Sonnet 5.5");
    expect(filas[1]?.textContent).not.toContain("Opus");
    expect(filas[1]?.textContent).not.toContain("Se pidió");
  });

  it("no muestra la sección si no hay bitácora o no se pudo leer /estado", async () => {
    simularRed({ estado: conBitacora([]) });
    await abrir();
    await screen.findByText("El modelo leyó solo una parte de este documento");
    expect(screen.queryByRole("heading", { name: "Quién redactó" })).toBeNull();
  });

  it("no muestra la sección si /estado falla", async () => {
    simularRed({ estado: 500 });
    await abrir();
    await screen.findByText(/No se pudieron leer las alertas del caso/);
    expect(screen.queryByRole("heading", { name: "Quién redactó" })).toBeNull();
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

  it("sigue mostrando el documento y solo las citas si falla /estado", async () => {
    simularRed({ estado: 500 });
    await abrir();
    expect(within(panel()).getByText("No se pudieron leer las alertas del caso; se muestran solo las citas.")).toBeTruthy();
    expect(resumenPanel()).toBe("Lleva 0 de 2 revisados. Nada de esto bloquea la decisión.");
    expect(within(panel()).queryByText("Sentido del fallo de primera instancia")).toBeNull();
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("No se pudo comprobar el estado del caso.")).toBeTruthy();
  });

  it("muestra una cita sin cobertura ni fuente sin romperse", async () => {
    const vista = structuredClone(VISTA_BORRADOR);
    const rechazada = vista.citas.find((c) => c.id === "c3");
    if (!rechazada) throw new Error("falta la cita");
    rechazada.cobertura = null;
    rechazada.fuente = "";
    simularRed({ vista });
    await abrir();
    fireEvent.click(citaEnTexto(/T-999/));
    const popover = await screen.findByRole("region", { name: "c3" });
    expect(within(popover).getByText("—")).toBeTruthy();
  });
});

describe("Revisión y panel", () => {
  it("marca como revisado, actualiza el resumen y la barra inferior y lo guarda por caso y borrador", async () => {
    simularRed();
    await abrir();
    expect(screen.getByText("Quedan 7 puntos por revisar")).toBeTruthy();
    expect(screen.getByText("Lleva 0 de 7. No bloquean la decisión.")).toBeTruthy();
    const marca = marcaRevisado("Sentencia T-999 de 2019");
    expect(marca.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(marca);
    expect(marca.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Quedan 6 puntos por revisar")).toBeTruthy();
    expect(screen.getByText("Lleva 1 de 7. No bloquean la decisión.")).toBeTruthy();
    expect(within(panel()).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
    expect(JSON.parse(localStorage.getItem(CLAVE) ?? "null")).toEqual(["cita-c3"]);
    fireEvent.click(marca);
    expect(marca.getAttribute("aria-pressed")).toBe("false");
    expect(JSON.parse(localStorage.getItem(CLAVE) ?? "null")).toEqual([]);
  });

  it("recupera lo revisado al volver y lo reinicia si el borrador cambió", async () => {
    localStorage.setItem(CLAVE, JSON.stringify(["cita-c3", "cita-c2"]));
    simularRed();
    const primera = await abrir();
    expect(marcaRevisado("Sentencia T-999 de 2019").getAttribute("aria-pressed")).toBe("true");
    expect(marcaRevisado("Sentencia SU-508 de 2020").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Quedan 5 puntos por revisar")).toBeTruthy();
    primera.unmount();

    const otra = structuredClone(VISTA_BORRADOR);
    otra.sha256 = "1".repeat(64);
    simularRed({ vista: otra });
    await abrir();
    expect(marcaRevisado("Sentencia T-999 de 2019").getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("Quedan 7 puntos por revisar")).toBeTruthy();
  });

  it("revisar todo lo pendiente deja la barra lista para pasar a la decisión", async () => {
    simularRed();
    await abrir();
    const pendientes = within(panel()).getAllByRole("button", { name: /^Revisado:/ });
    expect(pendientes.length).toBe(7);
    for (const p of pendientes) fireEvent.click(p);
    expect(screen.getByText("Revisó los 7 puntos")).toBeTruthy();
    expect(screen.getByText("Puede pasar a la decisión.")).toBeTruthy();
    expect(resumenPanel()).toContain("Lleva 7 de 7 revisados");
  });

  it("funciona con localStorage bloqueado o con JSON corrupto", async () => {
    localStorage.setItem(CLAVE, "{no es json");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bloqueado", "SecurityError");
    });
    simularRed();
    await abrir();
    const marca = marcaRevisado("Sentencia T-999 de 2019");
    expect(marca.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(marca);
    expect(marca.getAttribute("aria-pressed")).toBe("true");
    vi.restoreAllMocks();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bloqueado", "SecurityError");
    });
    simularRed();
    cleanup();
    await abrir();
    expect(marcaRevisado("Sentencia T-999 de 2019").getAttribute("aria-pressed")).toBe("false");
  });

  it("expande la fila de un archivo con su nombre completo y la nota", async () => {
    simularRed();
    await abrir();
    fireEvent.click(filaDe(/El modelo leyó solo una parte de este documento/));
    const lateral = within(panel());
    expect(lateral.getByText("007_007RespuestaEPSHorizonteSaludSAS_ContestacionTutela_Radicado2026-00412_Anexos.pdf", { selector: "code" })).toBeTruthy();
    expect(lateral.getByText(/Se le entregaron los primeros 120\.000 caracteres/)).toBeTruthy();
  });

  it("separa en viñetas las dos lecturas de un campo de metadatos", async () => {
    simularRed();
    await abrir();
    fireEvent.click(filaDe(/Accionadas: dos lecturas distintas/));
    const lateral = within(panel());
    expect(lateral.getByText("Extraído del expediente · se conservó")).toBeTruthy();
    expect(lateral.getByText("Leído por el modelo")).toBeTruthy();
    expect(lateral.getByText("SUPERINTENDENCIA NACIONAL DE SALUD")).toBeTruthy();
    expect(lateral.getByText("Superintendencia Nacional de Salud – Supersalud")).toBeTruthy();
  });
});

describe("Borrador interacción", () => {
  it("abre el detalle de una cita, enfoca su título y devuelve el foco al cerrar", async () => {
    simularRed();
    await abrir();
    const cita = citaEnTexto(/SU-508/);
    cita.focus();
    fireEvent.click(cita);
    const popover = await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    expect(within(popover).getByText("Con alerta", { selector: ".chip" })).toBeTruthy();
    expect(within(popover).getAllByText(/71\s*%/).length).toBeGreaterThan(0);
    expect(within(popover).getByRole("listitem").textContent).toMatch(/Compare con la relatoría/);
    expect(cita.getAttribute("aria-pressed")).toBe("true");
    expect(cita.getAttribute("aria-controls")).toBe("bor-detalle");
    await waitFor(() => expect(document.activeElement).toBe(within(popover).getByRole("heading")));
    fireEvent.click(within(popover).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();
    expect(document.activeElement).toBe(cita);
  });

  it("Escape cierra el detalle y devuelve el foco a la cita; Enter y Espacio lo abren", async () => {
    simularRed();
    await abrir();
    const cita = citaEnTexto(/SU-508/);
    cita.focus();
    fireEvent.keyDown(cita, { key: "Enter" });
    const popover = await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    await waitFor(() => expect(document.activeElement).toBe(within(popover).getByRole("heading")));
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();
    expect(document.activeElement).toBe(cita);
    fireEvent.keyDown(cita, { key: " " });
    expect(await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeTruthy();
    fireEvent.keyDown(cita, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();
  });

  it("volver a pulsar la cita o hacer clic fuera cierra el detalle", async () => {
    simularRed();
    await abrir();
    const cita = citaEnTexto(/SU-508/);
    fireEvent.click(cita);
    await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    fireEvent.click(cita);
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();

    fireEvent.click(cita);
    await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    fireEvent.click(screen.getByRole("heading", { level: 3, name: /ASUNTO/ }));
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();
  });

  it("enlaza a la relatoría solo cuando la cita verificada trae URL", async () => {
    simularRed();
    await abrir();
    fireEvent.click(citaEnTexto(/sentencia T-760 de 2008/));
    const popover = await screen.findByRole("region", { name: /Sentencia T-760 de 2008/ });
    const enlace = within(popover).getByRole("link", { name: /Abrir en la relatoría.*pestaña nueva/ });
    expect(enlace.getAttribute("href")).toBe("https://www.corteconstitucional.gov.co/relatoria/2008/T-760-08.htm");
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
    fireEvent.click(within(popover).getByRole("button", { name: "Cerrar" }));

    fireEvent.click(citaEnTexto(/SU-508/));
    const otro = await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    expect(within(otro).queryByRole("link")).toBeNull();
  });

  it("enlaza a la relatoría desde la fila comprobada", async () => {
    simularRed();
    await abrir();
    fireEvent.click(within(panel()).getByRole("button", { name: /Comprobado/ }));
    fireEvent.click(filaDe(/Sentencia T-760 de 2008/));
    const enlace = within(panel()).getByRole("link", { name: /Abrir en la relatoría/ });
    expect(enlace.getAttribute("href")).toBe("https://www.corteconstitucional.gov.co/relatoria/2008/T-760-08.htm");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("selecciona la cita desde la lista de revisión y abre su detalle", async () => {
    simularRed();
    await abrir();
    const popover = await abrirDetalleEnTexto(/Sentencia T-999 de 2019/, "Sentencia T-999 de 2019");
    expect(popover).toBeTruthy();
    expect(citaEnTexto(/T-999/).getAttribute("aria-pressed")).toBe("true");
    expect(citaEnTexto(/T-999/).classList.contains("destello")).toBe(true);
  });

  it("al pulsar una cita del texto marca su fila en el panel", async () => {
    simularRed();
    await abrir();
    expect(panel().querySelector(".bor-fila-activa")).toBeNull();
    fireEvent.click(citaEnTexto(/SU-508/));
    const activa = panel().querySelector(".bor-fila-activa");
    expect(activa?.textContent).toContain("Sentencia SU-508 de 2020");
    fireEvent.click(citaEnTexto(/SU-508/));
    expect(panel().querySelector(".bor-fila-activa")).toBeNull();
  });

  it("el interruptor de plantilla empieza encendido y quita la marca del texto fijo", async () => {
    simularRed();
    await abrir();
    const interruptor = screen.getByRole("switch", { name: "Marcar texto de plantilla" }) as HTMLInputElement;
    expect(interruptor.checked).toBe(true);
    expect(hoja().classList.contains("bor-con-plantilla")).toBe(true);
    expect(hoja().querySelectorAll(".bor-tpl").length).toBeGreaterThan(0);
    fireEvent.click(interruptor);
    expect(interruptor.checked).toBe(false);
    expect(hoja().classList.contains("bor-con-plantilla")).toBe(false);
    fireEvent.click(interruptor);
    expect(hoja().classList.contains("bor-con-plantilla")).toBe(true);
  });

  it("la barra del documento nombra la sección actual", async () => {
    simularRed();
    await abrir();
    await waitFor(() => expect(document.querySelector(".bor-doc-actual b")?.textContent).toBe("I. Asunto"));
  });

  it("abre el índice con el botón Contenido, lo cierra con Escape y devuelve el foco", async () => {
    simularRed();
    await abrir();
    const boton = screen.getByRole("button", { name: "Contenido" });
    expect(boton.getAttribute("aria-controls")).toBe("bor-indice");
    expect(boton.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(boton);
    expect(boton.getAttribute("aria-expanded")).toBe("true");
    expect(indice().classList.contains("abierto")).toBe(true);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(indice().classList.contains("abierto")).toBe(false);
    expect(document.activeElement).toBe(boton);
    fireEvent.click(boton);
    fireEvent.click(within(indice()).getByRole("button", { name: "El mínimo vital" }));
    expect(indice().classList.contains("abierto")).toBe(false);
    fireEvent.click(boton);
    fireEvent.click(screen.getByRole("heading", { level: 3, name: /ASUNTO/ }));
    expect(indice().classList.contains("abierto")).toBe(false);
  });

  it("abre la revisión como cajón, enfoca su cierre y Escape lo cierra devolviendo el foco", async () => {
    simularRed();
    await abrir();
    const boton = screen.getByRole("button", { name: /^Revisión/ });
    expect(boton.textContent).toContain("7");
    expect(boton.getAttribute("aria-controls")).toBe("bor-panel");
    const velo = document.querySelector(".bor-velo") as HTMLElement;
    expect(velo.hidden).toBe(true);
    fireEvent.click(boton);
    expect(panel().classList.contains("abierto")).toBe(true);
    expect(velo.hidden).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(within(panel()).getByRole("button", { name: "Cerrar la revisión" })));
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(panel().classList.contains("abierto")).toBe(false);
    expect(velo.hidden).toBe(true);
    expect(document.activeElement).toBe(boton);
    fireEvent.click(boton);
    fireEvent.click(velo);
    expect(panel().classList.contains("abierto")).toBe(false);
  });

  it("Escape cierra primero el detalle y luego el cajón; con el índice abierto, primero el índice", async () => {
    simularRed();
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    fireEvent.click(citaEnTexto(/SU-508/));
    await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Sentencia SU-508 de 2020" })).toBeNull();
    expect(panel().classList.contains("abierto")).toBe(true);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(panel().classList.contains("abierto")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    fireEvent.click(screen.getByRole("button", { name: "Contenido" }));
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(indice().classList.contains("abierto")).toBe(false);
    expect(panel().classList.contains("abierto")).toBe(true);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(panel().classList.contains("abierto")).toBe(false);
  });

  it("«Ver en el texto» cierra el cajón", async () => {
    simularRed();
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    expect(panel().classList.contains("abierto")).toBe(true);
    fireEvent.click(filaDe(/Sentencia SU-508 de 2020/));
    fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
    expect(panel().classList.contains("abierto")).toBe(false);
    await screen.findByRole("region", { name: "Sentencia SU-508 de 2020" });
  });

  it("enlaza a la decisión desde la barra inferior", async () => {
    simularRed();
    await abrir();
    expect(screen.getByRole("link", { name: "Pasar a la decisión" }).getAttribute("href")).toBe(`#/segunda/${CASO}/decision`);
  });

  it("dice que todo salió bien cuando no hay nada que revisar", async () => {
    const vista = structuredClone(VISTA_BORRADOR);
    vista.citas = vista.citas.filter((c) => c.estado === "verificada");
    const estado = structuredClone(ESTADO_BORRADOR);
    if (estado.resumen) {
      estado.resumen.alertas = {};
      estado.resumen.jev_metadatos = null;
    }
    simularRed({ vista, estado });
    await abrir();
    expect(within(panel()).getByText("Nada pendiente en lo que el sistema pudo comprobar.")).toBeTruthy();
    expect(screen.getByText("El borrador está listo para su decisión")).toBeTruthy();
    expect(screen.getByText("Todas las comprobaciones salieron bien.")).toBeTruthy();
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
    expect(screen.getByText("Hay una redacción en curso", { selector: "b" })).toBeTruthy();
    expect(screen.getByText("Podrá decidir cuando termine.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Pasar a la decisión" })).toBeNull();
    expect(screen.getByText("Pasar a la decisión").closest("a")?.getAttribute("aria-disabled")).toBe("true");
  });
});
