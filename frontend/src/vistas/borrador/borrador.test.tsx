import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApoderadosRespuesta, ApoderadoVista, ConflictoEdicion, EdicionesRespuesta } from "../../api/contrato";
import { estadoServidor, jobActual, toasts } from "../../estado";
import { conRevision } from "./apoderados";
import { claveRevisados } from "./datos";
import Borrador from "./index";
import { APODERADOS_BORRADOR, CASO_MOCK_BORRADOR, crearEdicionesMock, ESTADO_BORRADOR, paginaMock, VISTA_BORRADOR } from "./mock";
import type { EstadoCaso, LlamadaBitacora } from "./tipos";

const CASO = CASO_MOCK_BORRADOR;

interface Respuestas {
  vista?: unknown | number | (() => unknown);
  estado?: unknown | number;
  run?: unknown | number;
  apoderados?: unknown | number;
  revision?: (cuerpo: { revisado: boolean; nota: string }) => unknown;
  subida?: (cuerpo: FormData) => unknown;
  ajuste?: (cuerpo: Record<string, unknown>, url: string) => unknown;
  consultar?: (cuerpo: Record<string, unknown>) => unknown;
  identificar?: () => unknown;
  ediciones?: unknown | number | (() => unknown);
  editar?: (cuerpo: unknown, url: string) => unknown;
  servidor?: { api_key: boolean; gemini_key?: boolean };
}

const SIN_IDENTIFICACION: ApoderadosRespuesta = {
  identificacion: "no_disponible",
  apoderados: [],
  sin_apoderado: [],
  alertas: [],
  consulta: { activa: false, extension: "no_conectada", modo: "extension", pausa_hasta: null },
  bloquea_decision: false,
  editable: true,
};

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

function simularRed({
  vista = VISTA_BORRADOR,
  estado = ESTADO_BORRADOR,
  run = { job_id: "j-1" },
  apoderados = SIN_IDENTIFICACION,
  revision,
  subida,
  ajuste,
  consultar,
  identificar,
  ediciones = 404,
  editar,
  servidor,
}: Respuestas = {}) {
  const llamadas: { url: string; metodo: string; cuerpo: unknown }[] = [];
  const falso = vi.fn(async (url: string, init?: RequestInit) => {
    const metodo = init?.method ?? "GET";
    const cuerpo: unknown = init?.body instanceof FormData ? init.body : init?.body ? JSON.parse(String(init.body)) : undefined;
    llamadas.push({ url, metodo, cuerpo });
    if (url === "/api/estado-servidor" && servidor) {
      return responder({ proveedor: "anthropic", gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [], modelos_gemini: [], festivos: [], ...servidor });
    }
    if (url.endsWith("/vista/borrador")) return responder(typeof vista === "function" ? vista() : vista);
    if (metodo === "GET" && url.endsWith("/ediciones")) return responder(typeof ediciones === "function" ? ediciones() : ediciones);
    if (metodo === "PUT" && /\/ediciones\/[^/]+$/.test(url) && editar) return responder(editar(cuerpo, url));
    if (url.endsWith("/estado")) return responder(estado);
    if (url.endsWith("/run")) return responder(run);
    if (url.endsWith("/apoderados")) return responder(apoderados);
    if (metodo === "PUT" && url.endsWith("/revision") && revision) return responder(revision(cuerpo as { revisado: boolean; nota: string }));
    if (metodo === "PUT" && url.endsWith("/certificado") && subida) return responder(subida(cuerpo as FormData));
    if (metodo === "PUT" && url.endsWith("/ajustes") && ajuste) return responder(ajuste(cuerpo as Record<string, unknown>, url));
    if (metodo === "POST" && url.endsWith("/apoderados/consultar") && consultar) return responder(consultar(cuerpo as Record<string, unknown>));
    if (metodo === "POST" && url.endsWith("/apoderados/identificar") && identificar) return responder(identificar());
    const pagina = /\/expediente\/([^/]+)\/paginas\/(\d+)$/.exec(url);
    if (pagina) return responder(paginaMock(pagina[1] ?? "", Number(pagina[2])));
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

const CLAVE = claveRevisados(CASO);

async function abrir() {
  const vista = render(<Borrador caso={CASO} />);
  await screen.findByRole("heading", { level: 3, name: /ASUNTO/ });
  return vista;
}

const panel = () => document.getElementById("bor-panel") as HTMLElement;
const indice = () => screen.getByRole("navigation", { name: "Contenido del borrador" });
const hoja = () => screen.getByRole("article", { name: /Borrador del fallo/ });
const resumenPanel = () => panel().querySelector(".bor-panel-resumen")?.textContent ?? "";
const citaEnTexto = (nombre: RegExp) => within(hoja()).getByRole("button", { name: nombre });
const filaDe = (titulo: RegExp) => within(panel()).getByRole("button", { name: titulo, expanded: false });
const marcaRevisado = (titulo: string) => within(panel()).getByRole("button", { name: `Revisado: ${titulo}` });

async function abrirDetalleEnTexto(titulo: RegExp, popover: string) {
  fireEvent.click(filaDe(titulo));
  fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
  return await screen.findByRole("dialog", { name: popover });
}

beforeEach(() => {
  location.hash = "";
  estadoServidor.value = null;
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
    const popover = await screen.findByRole("dialog", { name: "c3" });
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
    expect(JSON.parse(localStorage.getItem(CLAVE) ?? "null")).toEqual(["cita-c3-rechazada-sentencia T-999 de 2019"]);
    fireEvent.click(marca);
    expect(marca.getAttribute("aria-pressed")).toBe("false");
    expect(JSON.parse(localStorage.getItem(CLAVE) ?? "null")).toEqual([]);
  });

  it("recupera lo revisado al volver y lo conserva si el borrador cambió por una edición", async () => {
    localStorage.setItem(CLAVE, JSON.stringify(["cita-c3-rechazada-sentencia T-999 de 2019", "cita-c2-revisar-sentencia SU-508 de 2020"]));
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
    expect(marcaRevisado("Sentencia T-999 de 2019").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Quedan 5 puntos por revisar")).toBeTruthy();
  });

  it("lo revisado de una cita deja de valer si cambia su estado", async () => {
    localStorage.setItem(CLAVE, JSON.stringify(["cita-c3-revisar-sentencia T-999 de 2019", "cita-c2-revisar-sentencia SU-508 de 2020"]));
    simularRed();
    await abrir();
    expect(marcaRevisado("Sentencia T-999 de 2019").getAttribute("aria-pressed")).toBe("false");
    expect(marcaRevisado("Sentencia SU-508 de 2020").getAttribute("aria-pressed")).toBe("true");
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
    const popover = await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
    expect(within(popover).getByText("Con alerta", { selector: ".chip" })).toBeTruthy();
    expect(within(popover).getAllByText(/71\s*%/).length).toBeGreaterThan(0);
    expect(within(popover).getByRole("listitem").textContent).toMatch(/Compare con la relatoría/);
    expect(cita.getAttribute("aria-pressed")).toBe("true");
    expect(cita.getAttribute("aria-controls")).toBe("bor-detalle");
    await waitFor(() => expect(document.activeElement).toBe(within(popover).getByRole("heading")));
    fireEvent.click(within(popover).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();
    expect(document.activeElement).toBe(cita);
  });

  it("Escape cierra el detalle y devuelve el foco a la cita; Enter y Espacio lo abren", async () => {
    simularRed();
    await abrir();
    const cita = citaEnTexto(/SU-508/);
    cita.focus();
    fireEvent.keyDown(cita, { key: "Enter" });
    const popover = await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
    await waitFor(() => expect(document.activeElement).toBe(within(popover).getByRole("heading")));
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();
    expect(document.activeElement).toBe(cita);
    fireEvent.keyDown(cita, { key: " " });
    expect(await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeTruthy();
    fireEvent.keyDown(cita, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();
  });

  it("volver a pulsar la cita o hacer clic fuera cierra el detalle", async () => {
    simularRed();
    await abrir();
    const cita = citaEnTexto(/SU-508/);
    fireEvent.click(cita);
    await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
    fireEvent.click(cita);
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();

    fireEvent.click(cita);
    await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
    fireEvent.click(screen.getByRole("heading", { level: 3, name: /ASUNTO/ }));
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();
  });

  it("enlaza a la relatoría solo cuando la cita verificada trae URL", async () => {
    simularRed();
    await abrir();
    fireEvent.click(citaEnTexto(/sentencia T-760 de 2008/));
    const popover = await screen.findByRole("dialog", { name: /Sentencia T-760 de 2008/ });
    const enlace = within(popover).getByRole("link", { name: /Abrir en la relatoría.*pestaña nueva/ });
    expect(enlace.getAttribute("href")).toBe("https://www.corteconstitucional.gov.co/relatoria/2008/T-760-08.htm");
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
    fireEvent.click(within(popover).getByRole("button", { name: "Cerrar" }));

    fireEvent.click(citaEnTexto(/SU-508/));
    const otro = await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
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
    await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Sentencia SU-508 de 2020" })).toBeNull();
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

  it("el cajón abierto es un diálogo modal que contiene el foco con Tab", async () => {
    simularRed();
    await abrir();
    expect(panel().getAttribute("role")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    expect(panel().getAttribute("role")).toBe("dialog");
    expect(panel().getAttribute("aria-modal")).toBe("true");
    const cerrar = within(panel()).getByRole("button", { name: "Cerrar la revisión" });
    await waitFor(() => expect(document.activeElement).toBe(cerrar));
    fireEvent.keyDown(cerrar, { key: "Tab", shiftKey: true });
    const foco = Array.from(panel().querySelectorAll<HTMLElement>("button:not([disabled]), a[href]"));
    expect(document.activeElement).toBe(foco[foco.length - 1]);
    fireEvent.keyDown(document.activeElement as Element, { key: "Tab" });
    expect(document.activeElement).toBe(foco[0]);
  });

  it("el índice móvil recibe el foco al abrirse y lo devuelve al botón al elegir", async () => {
    simularRed();
    await abrir();
    const boton = screen.getByRole("button", { name: "Contenido" });
    fireEvent.click(boton);
    await waitFor(() => expect(indice().contains(document.activeElement)).toBe(true));
    fireEvent.click(document.activeElement as Element);
    expect(document.activeElement).toBe(boton);
  });

  it("«Ver en el texto» cierra el cajón", async () => {
    simularRed();
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    expect(panel().classList.contains("abierto")).toBe(true);
    fireEvent.click(filaDe(/Sentencia SU-508 de 2020/));
    fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
    expect(panel().classList.contains("abierto")).toBe(false);
    await screen.findByRole("dialog", { name: "Sentencia SU-508 de 2020" });
  });

  it("«Ver en el texto» desde el cajón deja el foco en la cita, no en el cuerpo", async () => {
    simularRed();
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    fireEvent.click(filaDe(/Sentencia SU-508 de 2020/));
    fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
    expect(document.activeElement).toBe(citaEnTexto(/SU-508/));
  });

  it("al ensanchar la ventana con el cajón abierto el foco queda en el panel", async () => {
    simularRed();
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: /^Revisión/ }));
    await waitFor(() => expect(document.activeElement).toBe(within(panel()).getByRole("button", { name: "Cerrar la revisión" })));
    vi.stubGlobal("innerWidth", 1200);
    fireEvent(window, new Event("resize"));
    expect(panel().classList.contains("abierto")).toBe(false);
    expect(document.activeElement?.id).toBe("bor-panel-titulo");
    vi.unstubAllGlobals();
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
    expect(await screen.findByText("El borrador está listo para su decisión")).toBeTruthy();
    expect(within(panel()).getByText("Nada pendiente en lo que el sistema pudo comprobar.")).toBeTruthy();
    expect(within(panel()).getByText("Todo salió bien")).toBeTruthy();
    expect(screen.getByText("Todas las comprobaciones salieron bien.")).toBeTruthy();
  });

  it("si /estado falla no afirma que todo salió bien ni que está listo", async () => {
    const vista = structuredClone(VISTA_BORRADOR);
    vista.citas = vista.citas.filter((c) => c.estado === "verificada");
    simularRed({ vista, estado: 500 });
    await abrir();
    await screen.findByText(/No se pudieron leer las alertas del caso/);
    expect(within(panel()).queryByText("Todo salió bien")).toBeNull();
    expect(screen.queryByText(/Jev coincide con el borrador/)).toBeNull();
    expect(screen.queryByText("El borrador está listo para su decisión")).toBeNull();
    expect(screen.getByText("No se pudieron leer las alertas")).toBeTruthy();
  });

  it("mientras /estado carga no afirma que todo salió bien", async () => {
    const vista = structuredClone(VISTA_BORRADOR);
    vista.citas = vista.citas.filter((c) => c.estado === "verificada");
    let liberar: (r: Response) => void = () => {};
    const lento = new Promise<Response>((resolver) => {
      liberar = resolver;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (url.endsWith("/vista/borrador") ? responder(vista) : url.endsWith("/estado") ? lento : responder(404))),
    );
    await abrir();
    expect(within(panel()).queryByText("Todo salió bien")).toBeNull();
    expect(screen.queryByText("El borrador está listo para su decisión")).toBeNull();
    expect(screen.getByText("Comprobando el borrador")).toBeTruthy();
    liberar(responder(conEstado("esperando_decision", { resumen: { alertas: {}, jev_metadatos: null } })));
    expect(await screen.findByText("El borrador está listo para su decisión")).toBeTruthy();
  });
});

describe("Apoderados en el borrador", () => {
  const ID_ROJO = "ap-c47d19e6a8";
  const ID_AMBAR = "ap-81be04c5f2";
  const rojo = (): ApoderadoVista => structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === ID_ROJO) as ApoderadoVista);
  const pestanaApoderados = () => within(panel()).getByRole("tab", { name: /^Apoderados/ });
  const pasarADecision = () => screen.getByText("Pasar a la decisión").closest("a") as HTMLElement;

  it("un apoderado no verificado bloquea «Pasar a la decisión» hasta marcarlo revisado en el servidor", async () => {
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, revision: (c) => conRevision(rojo(), c.revisado) });
    await abrir();
    expect(await screen.findByText("Revise los apoderados no verificados")).toBeTruthy();
    expect(screen.getByText(/^CARLOS EDUARDO PINEDA RUIZ no pudo verificarse\. Márquelo como revisado/)).toBeTruthy();
    expect(pasarADecision().getAttribute("aria-disabled")).toBe("true");
    expect(pasarADecision().hasAttribute("href")).toBe(false);
    expect(within(panel()).getByRole("alert").textContent).toContain("Un apoderado no pudo verificarse.");
    expect(resumenPanel()).toBe("Lleva 0 de 7 revisados.");

    fireEvent.click(pestanaApoderados());
    const marca = marcaRevisado("CARLOS EDUARDO PINEDA RUIZ");
    marca.focus();
    fireEvent.click(marca);
    expect(marca.getAttribute("aria-pressed")).toBe("true");
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.url).toBe(`/api/casos/${CASO}/apoderados/${ID_ROJO}/revision`);
    expect(put?.cuerpo).toEqual({ revisado: true, nota: "", huella: rojo().huella });
    expect((await screen.findByRole("link", { name: "Pasar a la decisión" })).getAttribute("href")).toBe(`#/segunda/${CASO}/decision`);
    await waitFor(() => expect(within(panel()).queryByRole("alert")).toBeNull());
    expect(document.activeElement).toBe(marca);
    expect(localStorage.getItem(CLAVE)).toBeNull();
  });

  it("con nombres de abogados marcados, la barra del documento explica los tres trazos", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    const leyenda = await screen.findByRole("note", { name: "Leyenda de apoderados" });
    expect(leyenda.closest(".bor-doc-barra")?.classList.contains("con-leyenda")).toBe(true);
    expect([...leyenda.children].map((c) => c.textContent)).toEqual(["Abogado verificado", "Abogado por revisar", "Abogado no verificado"]);
    expect([...leyenda.querySelectorAll(".bor-ley-m")].map((m) => m.className)).toEqual(["bor-ley-m v", "bor-ley-m a", "bor-ley-m m"]);
  });

  it("sin nombres marcados (no hay identificación, o el texto no nombra a ningún abogado) no hay leyenda", async () => {
    simularRed();
    await abrir();
    await screen.findByRole("tab", { name: /^Apoderados/ });
    expect(screen.queryByRole("note", { name: "Leyenda de apoderados" })).toBeNull();
    expect(document.querySelector(".bor-doc-barra")?.classList.contains("con-leyenda")).toBe(false);
  });

  it("si el servidor rechaza la revisión la desmarca, vuelve a bloquear y explica por qué", async () => {
    const motivo = "El caso no está esperando la decisión: la revisión de los apoderados no se puede cambiar ahora.";
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, revision: () => new Falla(409, motivo) });
    await abrir();
    await screen.findByText("Revise los apoderados no verificados");
    fireEvent.click(pestanaApoderados());
    const marca = marcaRevisado("CARLOS EDUARDO PINEDA RUIZ");
    fireEvent.click(marca);
    expect(await within(panel()).findByText(motivo)).toBeTruthy();
    expect(marca.getAttribute("aria-pressed")).toBe("false");
    expect(pasarADecision().getAttribute("aria-disabled")).toBe("true");
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "GET" && l.url.endsWith("/apoderados")).length).toBe(2));
  });

  it("cuenta a los apoderados pendientes en la barra inferior con lo revisado en el servidor", async () => {
    const apoderados = structuredClone(APODERADOS_BORRADOR);
    apoderados.apoderados = apoderados.apoderados.map((a) => (a.id === ID_ROJO ? conRevision(a, true) : a));
    apoderados.bloquea_decision = false;
    simularRed({ apoderados });
    await abrir();
    expect(await screen.findByText("Quedan 8 puntos por revisar")).toBeTruthy();
    expect(screen.getByText("Lleva 1 de 9. No bloquean la decisión.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Revisión/ }).textContent).toContain("8");
    expect(screen.getByRole("link", { name: "Pasar a la decisión" })).toBeTruthy();
    expect(resumenPanel()).toBe("Lleva 0 de 7 revisados. Nada de esto bloquea la decisión.");
    fireEvent.click(pestanaApoderados());
    expect(marcaRevisado("CARLOS EDUARDO PINEDA RUIZ").getAttribute("aria-pressed")).toBe("true");
    expect(resumenPanel()).toBe("3 apoderados · 1 verificado · 1 por revisar · 1 no verificado");
  });

  it("las alertas del nodo de apoderados se revisan en su pestaña y se guardan en el navegador", async () => {
    const estado = structuredClone(ESTADO_BORRADOR);
    const alerta = "ALERTA: En 1a-011 (011.pdf), p. 3, consta la tarjeta profesional 12345, que no corresponde a ningún apoderado identificado; revise si actúa un abogado que no se identificó.";
    if (estado.resumen?.alertas && !Array.isArray(estado.resumen.alertas)) estado.resumen.alertas["apoderados"] = [alerta];
    simularRed({ estado, apoderados: APODERADOS_BORRADOR });
    await abrir();
    const texto = alerta.replace(/^ALERTA: /, "");
    await screen.findByText("Revise los apoderados no verificados");
    expect(within(panel()).queryByText(texto)).toBeNull();
    fireEvent.click(pestanaApoderados());
    const grupo = within(panel()).getByRole("heading", { name: "Avisos de la identificación" }).closest("section") as HTMLElement;
    expect(within(grupo).getByText(texto)).toBeTruthy();
    expect(within(grupo).getByText("Apoderados")).toBeTruthy();
    fireEvent.click(within(grupo).getByRole("button", { name: /^Revisado: En 1a-011/ }));
    expect(JSON.parse(localStorage.getItem(CLAVE) ?? "null")).toEqual([`alerta-apoderados-${alerta}`]);
  });

  it("un caso sin identificación no bloquea y la pestaña lo explica", async () => {
    simularRed();
    await abrir();
    await screen.findByText("Quedan 7 puntos por revisar");
    expect(screen.getByRole("link", { name: "Pasar a la decisión" })).toBeTruthy();
    fireEvent.click(pestanaApoderados());
    expect(within(panel()).getByText("Identificación no disponible para este caso", { selector: "b" })).toBeTruthy();
    expect(resumenPanel()).toBe("Identificación no disponible para este caso.");
  });

  it("si /apoderados falla no bloquea la decisión y ofrece reintentar en la pestaña", async () => {
    const llamadas = simularRed({ apoderados: 500 });
    await abrir();
    fireEvent.click(pestanaApoderados());
    expect(await within(panel()).findByText("No se pudo leer el estado de los apoderados", { selector: "b" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Pasar a la decisión" })).toBeTruthy();
    fireEvent.click(within(panel()).getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.url.endsWith("/apoderados")).length).toBe(2));
  });

  it("pulsar una cita en el texto vuelve a la pestaña de citas y marca su fila", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    fireEvent.click(pestanaApoderados());
    expect(pestanaApoderados().getAttribute("aria-selected")).toBe("true");
    fireEvent.click(citaEnTexto(/SU-508/));
    expect(within(panel()).getByRole("tab", { name: /^Citas/ }).getAttribute("aria-selected")).toBe("true");
    expect(panel().querySelector(".bor-fila-activa")?.textContent).toContain("Sentencia SU-508 de 2020");
  });

  const nombreEnTexto = (nombre: RegExp) => within(hoja()).findByRole("button", { name: nombre });

  it("sin /apoderados los nombres de los abogados quedan como texto", async () => {
    simularRed();
    await abrir();
    await screen.findByText("Quedan 7 puntos por revisar");
    expect(hoja().querySelector("[data-apoderado]")).toBeNull();
    expect(hoja().textContent).toContain("la doctora Andrea Paola Giraldo Montoya;");
  });

  it("pulsar el nombre de un abogado abre su detalle, cambia a la pestaña Apoderados y abre su fila", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    const nombre = await nombreEnTexto(/Andrea Paola Giraldo Montoya/);
    expect(nombre.textContent).toBe("Andrea Paola Giraldo Montoya (abogado verificado)");
    expect(nombre.classList.contains("verificada")).toBe(true);
    expect((await nombreEnTexto(/Luis Fernando Ospina Arango/)).classList.contains("revisar")).toBe(true);
    expect((await nombreEnTexto(/Carlos Eduardo Pineda Ruiz/)).classList.contains("rechazada")).toBe(true);
    nombre.focus();
    fireEvent.click(nombre);
    const detalle = await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" });
    expect(detalle.id).toBe("bor-detalle");
    expect(nombre.getAttribute("aria-pressed")).toBe("true");
    expect(nombre.getAttribute("aria-controls")).toBe("bor-detalle");
    expect(within(detalle).getByRole("heading", { level: 4, name: "Tarjeta profesional" })).toBeTruthy();
    expect(within(detalle).getByRole("heading", { level: 4, name: "Facultad para representar" })).toBeTruthy();
    expect(pestanaApoderados().getAttribute("aria-selected")).toBe("true");
    expect(panel().querySelector(".bor-fila-activa")?.textContent).toContain("ANDREA PAOLA GIRALDO MONTOYA");
    expect(within(panel()).getByRole("button", { name: /ANDREA PAOLA GIRALDO MONTOYA/, expanded: true })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(within(detalle).getByRole("heading", { level: 3 })));
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBeNull();
    expect(document.activeElement).toBe(nombre);
    expect(nombre.getAttribute("aria-pressed")).toBe("false");
  });

  it("volver a pulsar el nombre o hacer clic fuera cierra el detalle del abogado", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    const nombre = await nombreEnTexto(/Carlos Eduardo Pineda Ruiz/);
    fireEvent.click(nombre);
    await screen.findByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" });
    fireEvent.click(nombre);
    expect(screen.queryByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" })).toBeNull();
    fireEvent.keyDown(nombre, { key: "Enter" });
    await screen.findByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" });
    fireEvent.click(screen.getByRole("heading", { level: 3, name: /ASUNTO/ }));
    expect(screen.queryByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" })).toBeNull();
  });

  it("«Marcar revisado» del detalle envía la huella que vio y desbloquea la decisión", async () => {
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, revision: (c) => conRevision(rojo(), c.revisado) });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Carlos Eduardo Pineda Ruiz/));
    const detalle = await screen.findByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" });
    expect(pasarADecision().getAttribute("aria-disabled")).toBe("true");
    const boton = within(detalle).getByRole("button", { name: "Marcar revisado" });
    expect(boton.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(boton);
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.url).toBe(`/api/casos/${CASO}/apoderados/${ID_ROJO}/revision`);
    expect(put?.cuerpo).toEqual({ revisado: true, nota: "", huella: rojo().huella });
    expect(boton.getAttribute("aria-pressed")).toBe("true");
    expect((await screen.findByRole("link", { name: "Pasar a la decisión" })).getAttribute("href")).toBe(`#/segunda/${CASO}/decision`);
    expect(marcaRevisado("CARLOS EDUARDO PINEDA RUIZ").getAttribute("aria-pressed")).toBe("true");
  });

  it("sube el certificado desde el detalle como FormData sin el nombre original y el abogado queda en verde", async () => {
    const ambar = structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista);
    const verde: ApoderadoVista = {
      ...ambar,
      estado: "verificado",
      fase: "listo",
      motivos: [],
      vigencia: {
        ...ambar.vigencia,
        estado: "vigente",
        fase: "listo",
        origen: "manual",
        consultado_en: "2026-11-17T10:50:00-05:00",
        certificado_url: `/api/casos/${CASO}/apoderados/${ID_AMBAR}/certificado`,
      },
      huella: "otra-huella",
    };
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, subida: () => verde });
    await abrir();
    const nombre = await nombreEnTexto(/Luis Fernando Ospina Arango/);
    fireEvent.click(nombre);
    const detalle = await screen.findByRole("dialog", { name: "LUIS FERNANDO OSPINA ARANGO" });
    const entrada = detalle.querySelector<HTMLInputElement>("input[type=file]");
    if (!entrada) throw new Error("falta el selector de archivo");
    const archivo = new File(["%PDF-1.7 certificado"], "CV_RNA-TPA_71654320.pdf", { type: "application/pdf" });
    Object.defineProperty(entrada, "files", { configurable: true, value: [archivo] });
    fireEvent.change(entrada);
    await waitFor(() => expect(nombre.classList.contains("verificada")).toBe(true));
    const put = llamadas.find((l) => l.metodo === "PUT" && l.url.endsWith("/certificado"));
    expect(put?.url).toBe(`/api/casos/${CASO}/apoderados/${ID_AMBAR}/certificado`);
    const cuerpo = put?.cuerpo as FormData;
    expect([...cuerpo.keys()]).toEqual(["archivo"]);
    const enviado = cuerpo.get("archivo") as File;
    expect(enviado.name).toBe("certificado.pdf");
    expect(enviado.size).toBe(archivo.size);
    expect(within(detalle).getByText("Abogado verificado", { selector: ".chip" })).toBeTruthy();
    expect(within(detalle).getByRole("link", { name: /Ver certificado \(PDF\)/ }).getAttribute("href")).toBe(verde.vigencia.certificado_url);
    expect(detalle.querySelector("input[type=file]")).toBeNull();
  });

  it("si el servidor rechaza el certificado lo explica en el detalle", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR, subida: () => new Falla(422, "El certificado es de otra persona.") });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Luis Fernando Ospina Arango/));
    const detalle = await screen.findByRole("dialog", { name: "LUIS FERNANDO OSPINA ARANGO" });
    const entrada = detalle.querySelector<HTMLInputElement>("input[type=file]") as HTMLInputElement;
    Object.defineProperty(entrada, "files", { configurable: true, value: [new File(["%PDF-1.7"], "c.pdf", { type: "application/pdf" })] });
    fireEvent.change(entrada);
    expect(await within(detalle).findByText("El certificado es de otra persona.")).toBeTruthy();
  });

  it("«Ver poder» abre el visor perezoso con la página, un clic dentro no cierra el detalle y al cerrar vuelve el foco", async () => {
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Andrea Paola Giraldo Montoya/));
    const detalle = await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" });
    const ver = within(detalle).getByRole("button", { name: "Ver poder · p. 4" });
    ver.focus();
    fireEvent.click(ver);
    const visor = await screen.findByRole("dialog", { name: "Poder especial · Doc. 1a-007" });
    expect(visor.tagName).toBe("DIALOG");
    expect(within(visor).getByText("Evidencia de que ANDREA PAOLA GIRALDO MONTOYA representa a EPS HORIZONTE SALUD S.A.S.")).toBeTruthy();
    await waitFor(() => expect(visor.querySelector("mark")?.textContent?.replace(/\s+/g, " ")).toMatch(/^confiero poder especial.*conteste la acción de tutela de la referencia$/));
    expect(llamadas.some((l) => l.url === `/api/casos/${CASO}/expediente/1a-007/paginas/4`)).toBe(true);
    fireEvent.click(within(visor).getByRole("heading", { level: 3, name: "Lo que se cotejó" }));
    expect(screen.getByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBe(detalle);
    fireEvent.click(within(visor).getByRole("button", { name: "Cerrar visor" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Poder especial · Doc. 1a-007" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(ver));
    expect(screen.getByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBe(detalle);
  });

  it("el visor abierto desde la fila marca revisado al abogado en el servidor", async () => {
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, revision: (c) => conRevision(rojo(), c.revisado) });
    await abrir();
    fireEvent.click(pestanaApoderados());
    fireEvent.click(await within(panel()).findByRole("button", { name: /CARLOS EDUARDO PINEDA RUIZ/, expanded: false }));
    const abrirPoder = within(panel()).getByRole("button", { name: "Poder · p. 5" });
    fireEvent.click(abrirPoder);
    const visor = await screen.findByRole("dialog", { name: "Poder especial · Doc. 1a-011" });
    fireEvent.click(within(visor).getByRole("button", { name: "Marcar revisado" }));
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ revisado: true, nota: "", huella: rojo().huella });
    await waitFor(() => expect(within(visor).getByRole("button", { name: "Marcar revisado" }).getAttribute("aria-pressed")).toBe("true"));
    fireEvent.keyDown(within(visor).getByRole("button", { name: "Cerrar visor" }), { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(abrirPoder));
  });

  it("«Ver en el texto» de la fila de un abogado selecciona su nombre y abre su detalle", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    fireEvent.click(pestanaApoderados());
    fireEvent.click(await within(panel()).findByRole("button", { name: /CARLOS EDUARDO PINEDA RUIZ/, expanded: false }));
    fireEvent.click(within(panel()).getByRole("button", { name: /Ver en el texto/ }));
    const nombre = await nombreEnTexto(/Carlos Eduardo Pineda Ruiz/);
    expect(nombre.getAttribute("aria-pressed")).toBe("true");
    expect(await screen.findByRole("dialog", { name: "CARLOS EDUARDO PINEDA RUIZ" })).toBeTruthy();
    expect(pestanaApoderados().getAttribute("aria-selected")).toBe("true");
  });

  it("al abrir pide una vez la consulta automática de quien sigue sin consultar", async () => {
    const enCola = structuredClone(APODERADOS_BORRADOR);
    enCola.consulta = { ...enCola.consulta, activa: true, extension: "conectada" };
    const ambar = enCola.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista;
    ambar.fase = "en_cola";
    ambar.vigencia.fase = "en_cola";
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, consultar: () => enCola });
    await abrir();
    fireEvent.click(pestanaApoderados());
    const fila = await waitFor(() => {
      const li = panel().querySelector<HTMLElement>(`li[data-clave="apoderado-${ID_AMBAR}"]`);
      expect(li?.querySelector(".bor-fila-sub .chip")?.textContent).toBe("En cola");
      return li as HTMLElement;
    });
    expect(fila).toBeTruthy();
    const posts = llamadas.filter((l) => l.metodo === "POST");
    expect(posts.map((l) => [l.url, l.cuerpo])).toEqual([[`/api/casos/${CASO}/apoderados/consultar`, { forzar: false }]]);
    expect(within(panel()).getByRole("note", { name: "Consulta automática de la vigencia" }).textContent).toContain("Extensión conectada");
    expect(panel().querySelector(".bor-panel-resumen [role=status]")?.textContent).toBe("2 de 3 listos · en cola para consultar");
  });

  it("«Reintentar consulta automática» del detalle fuerza la consulta de ese abogado", async () => {
    const sinRespuesta = structuredClone(APODERADOS_BORRADOR);
    sinRespuesta.consulta.extension = "conectada";
    const ambar = sinRespuesta.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista;
    ambar.vigencia.estado = "inaccesible";
    const enCola = structuredClone(sinRespuesta);
    const enColaAmbar = enCola.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista;
    enColaAmbar.fase = "en_cola";
    enColaAmbar.vigencia.fase = "en_cola";
    enCola.consulta.activa = true;
    const llamadas = simularRed({ apoderados: sinRespuesta, consultar: () => enCola });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Luis Fernando Ospina Arango/));
    const detalle = await screen.findByRole("dialog", { name: "LUIS FERNANDO OSPINA ARANGO" });
    expect(llamadas.filter((l) => l.metodo === "POST")).toEqual([]);
    fireEvent.click(within(detalle).getByRole("button", { name: "Reintentar consulta automática" }));
    await waitFor(() => expect(within(detalle).getByText("En cola para consultar la Rama Judicial.")).toBeTruthy());
    expect(llamadas.filter((l) => l.metodo === "POST").map((l) => l.cuerpo)).toEqual([{ ids: [ID_AMBAR], forzar: true }]);
    await waitFor(() => expect(document.activeElement).toBe(within(detalle).getByRole("heading", { level: 3 })));
  });

  it("sin extensión conectada no ofrece reintentar: el aviso enlaza a instalarla", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Luis Fernando Ospina Arango/));
    const detalle = await screen.findByRole("dialog", { name: "LUIS FERNANDO OSPINA ARANGO" });
    expect(within(detalle).queryByRole("button", { name: "Reintentar consulta automática" })).toBeNull();
    expect(within(panel()).getByRole("link", { name: "Instalar la extensión" }).getAttribute("href")).toBe("#/configuracion/extension");
  });

  it("«No es correcto…» del detalle pide confirmar, descarta el poder y el abogado queda por revisar", async () => {
    const verde = structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === "ap-3f9c2a71d0") as ApoderadoVista);
    const descartado: ApoderadoVista = {
      ...verde,
      estado: "revisar",
      motivos: ["El poder se descartó en la revisión."],
      poder: { ...verde.poder, estado: "descartado", evidencia: null, cadena: null },
      huella: "descartado",
    };
    const llamadas = simularRed({ apoderados: APODERADOS_BORRADOR, ajuste: () => descartado });
    await abrir();
    const nombre = await nombreEnTexto(/Andrea Paola Giraldo Montoya/);
    fireEvent.click(nombre);
    const detalle = await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" });
    const boton = within(detalle).getByRole("button", { name: "No es correcto…" });
    boton.focus();
    fireEvent.click(boton);
    const confirmar = await screen.findByRole("dialog", { name: "¿El poder no es correcto?" });
    expect(confirmar.tagName).toBe("DIALOG");
    expect(llamadas.some((l) => l.url.endsWith("/ajustes"))).toBe(false);
    fireEvent.click(within(confirmar).getByRole("button", { name: "Descartar el poder" }));
    await waitFor(() => expect(nombre.classList.contains("revisar")).toBe(true));
    const put = llamadas.find((l) => l.url.endsWith("/ajustes"));
    expect(put).toMatchObject({ metodo: "PUT", url: `/api/casos/${CASO}/apoderados/ap-3f9c2a71d0/ajustes`, cuerpo: { poder_descartado: true, nota: "" } });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "¿El poder no es correcto?" })).toBeNull());
    expect(within(detalle).getByText("Poder descartado", { selector: ".chip" })).toBeTruthy();
    expect(within(detalle).getByRole("button", { name: "Señalar el poder a mano…" })).toBeTruthy();
    // El botón que abrió la confirmación ya no está: el foco vuelve al título del detalle.
    await waitFor(() => expect(document.activeElement).toBe(within(detalle).getByRole("heading", { level: 3 })));
  });

  it.each([
    ["hallado", "Se volvió a tomar el poder hallado."],
    ["sin_poder", "Ya no hay un poder que respalde a ANDREA PAOLA GIRALDO MONTOYA: señálelo a mano."],
  ] as const)("«Deshacer el descarte» del detalle deja el foco en el detalle y lo dice (vuelve a %s)", async (vuelve, aviso) => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const verde = datos.apoderados.find((a) => a.id === "ap-3f9c2a71d0") as ApoderadoVista;
    const original = structuredClone(verde);
    verde.estado = "revisar";
    verde.poder = { ...verde.poder, estado: "descartado", evidencia: null, cadena: null };
    const restaurado: ApoderadoVista =
      vuelve === "hallado" ? original : { ...original, estado: "revisar", poder: { ...original.poder, estado: "sin_poder", evidencia: null, cadena: null } };
    const llamadas = simularRed({ apoderados: datos, ajuste: () => restaurado });
    toasts.value = [];
    await abrir();
    fireEvent.click(await nombreEnTexto(/Andrea Paola Giraldo Montoya/));
    const detalle = await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" });
    const deshacer = within(detalle).getByRole("button", { name: "Deshacer el descarte" });
    deshacer.focus();
    fireEvent.click(deshacer);
    await waitFor(() => expect(within(detalle).queryByRole("button", { name: "Deshacer el descarte" })).toBeNull());
    expect(llamadas.find((l) => l.url.endsWith("/ajustes"))?.cuerpo).toEqual({ poder_descartado: false });
    // El botón ya no está: el foco no queda en <body>, vuelve al título del detalle.
    await waitFor(() => expect(document.activeElement).toBe(within(detalle).getByRole("heading", { level: 3 })));
    expect(toasts.value.map((t) => t.texto)).toEqual([aviso]);
  });

  it("«Señalar el poder a mano…» de la fila explica un rechazo dentro del diálogo y, aceptado, deja al abogado en verde", async () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const ambar = datos.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista;
    ambar.poder = { ...ambar.poder, estado: "sin_poder", evidencia: null };
    const manual: ApoderadoVista = {
      ...ambar,
      estado: "verificado",
      fase: "listo",
      motivos: [],
      vigencia: { ...ambar.vigencia, estado: "vigente", fase: "listo" },
      poder: { ...structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === ID_AMBAR) as ApoderadoVista).poder, estado: "manual" },
    };
    let intentos = 0;
    const llamadas = simularRed({
      apoderados: datos,
      ajuste: () => (++intentos === 1 ? new Falla(422, "El nombre del abogado no aparece en esa página.") : manual),
    });
    await abrir();
    fireEvent.click(pestanaApoderados());
    fireEvent.click(await within(panel()).findByRole("button", { name: /LUIS FERNANDO OSPINA ARANGO/, expanded: false }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Señalar el poder a mano…" }));
    const dialogo = await screen.findByRole("dialog", { name: "Señalar el poder a mano" });
    const documento = within(dialogo).getByLabelText("Documento del expediente") as HTMLSelectElement;
    // El borrador solo conoce los documentos de las evidencias; el poder de este abogado está en otro.
    expect([...documento.options].map((o) => o.value)).toEqual(["1a-007", "1a-011", ""]);
    fireEvent.change(documento, { target: { value: "" } });
    fireEvent.input(within(dialogo).getByLabelText("Número del documento"), { target: { value: "1a-002" } });
    fireEvent.input(within(dialogo).getByLabelText("Página"), { target: { value: "5" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Señalar el poder" }));
    expect(await within(dialogo).findByText("El nombre del abogado no aparece en esa página.")).toBeTruthy();
    fireEvent.input(within(dialogo).getByLabelText("Página"), { target: { value: "6" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Señalar el poder" }));
    await waitFor(() => expect(within(panel()).getByRole("region", { name: "Verificados" }).textContent).toContain("LUIS FERNANDO OSPINA ARANGO"));
    expect(llamadas.filter((l) => l.url.endsWith("/ajustes")).map((l) => l.cuerpo)).toEqual([
      { poder_manual: { doc_id: "1a-002", pagina: 5 }, nota: "" },
      { poder_manual: { doc_id: "1a-002", pagina: 6 }, nota: "" },
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Señalar el poder a mano" })).toBeNull());
  });

  it("«No es correcto…» del visor cierra el visor y pide confirmar el descarte de ese poder", async () => {
    simularRed({ apoderados: APODERADOS_BORRADOR });
    await abrir();
    fireEvent.click(await nombreEnTexto(/Andrea Paola Giraldo Montoya/));
    const detalle = await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" });
    fireEvent.click(within(detalle).getByRole("button", { name: "Ver poder · p. 4" }));
    const visor = await screen.findByRole("dialog", { name: "Poder especial · Doc. 1a-007" });
    fireEvent.click(within(visor).getByRole("button", { name: "No es correcto…" }));
    const confirmar = await screen.findByRole("dialog", { name: "¿El poder no es correcto?" });
    expect(screen.queryByRole("dialog", { name: "Poder especial · Doc. 1a-007" })).toBeNull();
    expect(confirmar.textContent).toContain("el poder del Doc. 1a-007, p. 4,");
    fireEvent.click(within(confirmar).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "¿El poder no es correcto?" })).toBeNull());
  });

  it("un caso anterior se identifica desde la pestaña y el borrador se vuelve a leer con los nombres marcados", async () => {
    const sinNombres = structuredClone(VISTA_BORRADOR);
    for (const p of sinNombres.paginas) for (const b of p.bloques) for (const s of b.segmentos) delete s.apoderado_id;
    let vistas = 0;
    let identificado = false;
    const llamadas = simularRed({ apoderados: SIN_IDENTIFICACION, identificar: () => APODERADOS_BORRADOR });
    const red = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const original = red.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
    red.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/vista/borrador")) {
        vistas += 1;
        llamadas.push({ url, metodo: "GET", cuerpo: undefined });
        return responder(identificado ? VISTA_BORRADOR : sinNombres);
      }
      if (url.endsWith("/identificar")) identificado = true;
      return original(url, init);
    });
    await abrir();
    expect(within(hoja()).queryByRole("button", { name: /Andrea Paola Giraldo Montoya/ })).toBeNull();
    fireEvent.click(pestanaApoderados());
    fireEvent.click(await within(panel()).findByRole("button", { name: "Identificar apoderados" }));
    expect(await nombreEnTexto(/Andrea Paola Giraldo Montoya/)).toBeTruthy();
    expect(vistas).toBe(2);
    expect(llamadas.filter((l) => l.metodo === "POST").map((l) => l.url)).toContain(`/api/casos/${CASO}/apoderados/identificar`);
    expect(within(panel()).getByRole("region", { name: "No verificados" }).textContent).toContain("CARLOS EDUARDO PINEDA RUIZ");
    expect(within(indice()).getByText("2 abogados por revisar")).toBeTruthy();
  });

  it("las correcciones viajan en un chunk aparte: el borrador solo las importa con import()", () => {
    const fuente = readFileSync(join(import.meta.dirname, "index.tsx"), "utf8");
    expect(fuente).toContain('import("./DialogoAjuste")');
    expect(fuente).not.toMatch(/^import (?!type )[^;]*from "\.\/DialogoAjuste";/m);
  });

  it("el visor viaja en un chunk aparte: el borrador solo lo importa con import()", () => {
    const fuente = readFileSync(join(import.meta.dirname, "index.tsx"), "utf8");
    expect(fuente).toContain('import("./VisorEvidencia")');
    expect(fuente).not.toMatch(/^import (?!type )[^;]*from "\.\/VisorEvidencia";/m);
  });

  it("el detalle del abogado y los diálogos de corregir y de conflictos viajan en chunks aparte", () => {
    const fuente = readFileSync(join(import.meta.dirname, "index.tsx"), "utf8");
    for (const modulo of ["PopoverApoderado", "DialogoCorrecciones", "DialogoConflictos"]) {
      expect(fuente).toContain(`import("./${modulo}")`);
      expect(fuente).not.toMatch(new RegExp(`^import (?!type )[^;]*from "\\./${modulo}";`, "m"));
    }
  });

  describe("con el modo de edición", () => {
    const ID_VERDE = "ap-3f9c2a71d0";
    const CONTESTO = /admitió la acción el quince/;
    const unidadDe = (texto: RegExp) => within(hoja()).getByText(texto).closest<HTMLElement>(".bor-unidad") as HTMLElement;
    const marcasDe = (raiz: HTMLElement) => [...raiz.querySelectorAll<HTMLElement>("[data-apoderado]")].map((m) => m.dataset["apoderado"]);
    const pedirCorrecciones = () => screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement;

    function conEdiciones(extra: Partial<EdicionesRespuesta> = {}) {
      const mock = crearEdicionesMock();
      return simularRed({
        apoderados: APODERADOS_BORRADOR,
        vista: () => mock.vista(),
        ediciones: () => ({ ...mock.respuesta(), ...extra }),
        editar: (cuerpo, url) => mock.editar({ metodo: "PUT", ruta: url, cuerpo }),
      });
    }

    async function abrirEditando() {
      await abrir();
      fireEvent.click(await screen.findByRole("switch", { name: "Editar texto" }));
      await screen.findAllByRole("button", { name: "Editar párrafo" });
    }

    it("pulsar o teclear sobre el nombre de un abogado abre su detalle y no el editor del párrafo", async () => {
      conEdiciones();
      await abrirEditando();
      const nombre = await nombreEnTexto(/Andrea Paola Giraldo Montoya/);
      fireEvent.click(nombre);
      expect(await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBeTruthy();
      expect(screen.queryByRole("textbox", { name: "Texto del párrafo" })).toBeNull();
      expect(pestanaApoderados().getAttribute("aria-selected")).toBe("true");
      fireEvent.click(nombre);
      for (const key of ["Enter", " "]) {
        fireEvent.keyDown(nombre, { key });
        expect(await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBeTruthy();
        expect(screen.queryByRole("textbox")).toBeNull();
        fireEvent.click(nombre);
        expect(screen.queryByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBeNull();
      }
    });

    it("al guardar un párrafo con abogados, los nombres que siguen escritos vuelven a quedar marcados", async () => {
      conEdiciones();
      await abrirEditando();
      await nombreEnTexto(/Carlos Eduardo Pineda Ruiz/);
      const unidad = unidadDe(CONTESTO);
      expect(marcasDe(unidad)).toEqual([ID_VERDE, ID_ROJO]);
      fireEvent.click(within(unidad).getByRole("button", { name: "Editar párrafo" }));
      const campo = (await screen.findByRole("textbox", { name: "Texto del párrafo" })) as HTMLTextAreaElement;
      expect(campo.value).toContain("la doctora Andrea Paola Giraldo Montoya;");
      const nuevo = campo.value
        .replace("contestó el diecisiete (17) de septiembre siguiente", "contestó el 17 de septiembre")
        .replace("intervino por medio del doctor Carlos Eduardo Pineda Ruiz, quien solicitó", "solicitó");
      expect(nuevo).not.toContain("Pineda");
      fireEvent.input(campo, { target: { value: nuevo } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
      await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
      const editada = await waitFor(() => unidadDe(/contestó el 17 de septiembre/));
      expect(within(editada).getByText("Editado")).toBeTruthy();
      expect(marcasDe(editada)).toEqual([ID_VERDE]);
      expect(marcasDe(hoja())).not.toContain(ID_ROJO);
      const andrea = within(editada).getByRole("button", { name: /Andrea Paola Giraldo Montoya/ });
      expect(andrea.classList.contains("verificada")).toBe(true);
      fireEvent.click(andrea);
      expect(await screen.findByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBeTruthy();
    });

    it("con conflictos de edición, el Dock los pide resolver antes que revisar a los apoderados", async () => {
      const conflicto: ConflictoEdicion = {
        pieza: "apertura.antecedentes_hechos",
        etiqueta: "Antecedentes: hechos",
        huerfana: false,
        trozos: [{ tipo: "conflicto", mio: ["Mi texto."], nuevo: ["Texto de la corrección."], mio_permitido: true }],
      };
      conEdiciones({ conflictos: [conflicto] });
      await abrir();
      expect(await screen.findByText("Hay 1 conflicto de edición")).toBeTruthy();
      expect(screen.getByText("Resuelva los conflictos de edición antes de seguir.")).toBeTruthy();
      expect(screen.queryByText("Revise los apoderados no verificados")).toBeNull();
      expect(pasarADecision().getAttribute("aria-disabled")).toBe("true");
      expect(pedirCorrecciones().disabled).toBe(true);
    });

    it("sin conflictos, el bloqueo de los apoderados solo desactiva «Pasar a la decisión»", async () => {
      conEdiciones();
      await abrir();
      expect(await screen.findByText("Revise los apoderados no verificados")).toBeTruthy();
      expect(pasarADecision().getAttribute("aria-disabled")).toBe("true");
      await waitFor(() => expect(pedirCorrecciones().disabled).toBe(false));
    });
  });
});

describe("Pedir correcciones", () => {
  async function abrirDialogo() {
    await abrir();
    await waitFor(() => expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Pedir correcciones" }));
    return await screen.findByRole("heading", { name: "Pedir correcciones al borrador" });
  }

  it("cada opción describe su alcance con el detalle", async () => {
    simularRed();
    await abrirDialogo();
    const radio = screen.getByRole("radio", { name: /Rehacer las consideraciones/ });
    expect(radio.getAttribute("aria-describedby")).toBe("bor-op-det-rehacer_consideraciones");
    expect(document.getElementById("bor-op-det-rehacer_consideraciones")?.textContent).toBe("Solo la sección V. La apertura se conserva.");
  });

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

  describe("clave de la API", () => {
    async function pedirRehacer() {
      await abrirDialogo();
      fireEvent.click(screen.getByRole("radio", { name: /Rehacer las consideraciones/ }));
      fireEvent.input(screen.getByLabelText("Qué debe corregir"), { target: { value: "Cite una sentencia más reciente." } });
      fireEvent.click(screen.getByRole("button", { name: "Rehacer" }));
    }
    const envios = (llamadas: { url: string; metodo: string }[]) => llamadas.filter((l) => l.metodo === "POST" && l.url.endsWith("/run"));

    it("sin la clave del proveedor no envía y enlaza a Inteligencia artificial", async () => {
      const llamadas = simularRed({ estado: conEstado("esperando_decision", { proveedor_llm: "anthropic" }), servidor: { api_key: false } });
      await pedirRehacer();

      expect(
        await screen.findByText("Falta la clave de la API de Anthropic: configúrela en Inteligencia artificial antes de pedir la corrección."),
      ).toBeTruthy();
      expect(screen.getByRole("link", { name: "Ir a Inteligencia artificial" }).getAttribute("href")).toBe("#/configuracion/ia");
      expect(envios(llamadas)).toEqual([]);
      expect(location.hash).not.toBe(`#/segunda/${CASO}/proceso`);
      expect((screen.getByRole("button", { name: "Rehacer" }) as HTMLButtonElement).disabled).toBe(false);
    });

    it("con la clave del proveedor envía la corrección", async () => {
      const llamadas = simularRed({ estado: conEstado("esperando_decision", { proveedor_llm: "anthropic" }), servidor: { api_key: true } });
      await pedirRehacer();
      await waitFor(() => expect(location.hash).toBe(`#/segunda/${CASO}/proceso`));
      expect(envios(llamadas)).toHaveLength(1);
      expect(screen.queryByRole("link", { name: "Ir a Inteligencia artificial" })).toBeNull();
    });

    it("pide la clave del proveedor del caso", async () => {
      const llamadas = simularRed({
        estado: conEstado("esperando_decision", { proveedor_llm: "gemini" }),
        servidor: { api_key: true, gemini_key: false },
      });
      await pedirRehacer();
      expect(await screen.findByText(/Falta la clave de la API de Gemini:/)).toBeTruthy();
      expect(envios(llamadas)).toEqual([]);
    });

    it("con el proveedor del caso en fake no pide clave", async () => {
      const llamadas = simularRed({ estado: conEstado("esperando_decision", { proveedor_llm: "fake" }), servidor: { api_key: false } });
      await pedirRehacer();
      await waitFor(() => expect(location.hash).toBe(`#/segunda/${CASO}/proceso`));
      expect(envios(llamadas)).toHaveLength(1);
    });

    it("el enlace solo aparece con el aviso de la clave", async () => {
      simularRed({ run: 409 });
      await pedirRehacer();
      expect(await screen.findByText("Ya hay una ejecución en curso para este caso.")).toBeTruthy();
      expect(screen.queryByRole("link", { name: "Ir a Inteligencia artificial" })).toBeNull();
    });
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
