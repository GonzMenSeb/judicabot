import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Bloque, Vista } from "../../api/contrato";
import type { EstadoCaso } from "./tipos";

const get = vi.hoisted(() => vi.fn());

vi.mock("../../api", async (importar) => {
  const real = await importar<typeof import("../../api")>();
  return { ...real, api: { ...real.api, get: (...args: unknown[]) => get(...args) } };
});

import { ErrorApi } from "../../api";
import Fallo from "./index";

const P = "02SegundaInstancia/C01Principal";
const ARCHIVOS = [
  `${P}/001ActaRepartoSegunda.pdf`,
  `${P}/003FalloSegunda202600412.docx`,
  `${P}/fallo.vista.json`,
  "por_radicar/OficioRemiteCorteConstitucional.docx",
  "trabajo/declaracion_ia.docx",
];

const b = (id: string, tipo: Bloque["tipo"], ...segmentos: Bloque["segmentos"]): Bloque => ({ id, tipo, origen: "modelo", seccion: id === "t1" ? "s" : null, segmentos });
const pie = (n: number): Bloque => b(`pie-${n}`, "pie", { texto: "Pie del juzgado" });

const VISTA: Vista = {
  tipo: "fallo",
  sha256: "abc",
  paginas: [
    { bloques: [b("e1", "parrafo", { texto: "JUZGADO DE PRUEBA", negrita: true }), b("t1", "titulo", { texto: "I. ASUNTO" }), b("p1", "parrafo", { texto: "<img src=x onerror=alert(1)> Texto del asunto" }), pie(1)] },
    { bloques: [b("p2", "parrafo", { texto: "Según " }, { texto: "(sentencia SU-508 de 2020)", cita_id: "c2" }), pie(2)] },
    { bloques: [b("p3", "resuelve_numeral", { texto: "PRIMERO: REVOCAR", negrita: true }), pie(3)] },
  ],
  citas: [{ id: "c2", texto: "x", fuente: "sentencia SU-508 de 2020", cobertura: 0.7, estado: "revisar", detalle: "Cobertura baja" }],
  indice: [{ id: "t1", titulo: "I. ASUNTO" }],
};

const ESTADO: EstadoCaso = {
  estado: "terminado",
  salidas: ARCHIVOS,
  resumen: { alertas: { ingesta: ["Una página no tiene texto."] }, citas: [] },
  job_activo: null,
};

const RESUMEN = { id: "caso-1", nombre: "Quintero c. EPS", radicado: "05001408800920260041200", juzgado_a_quo: "Juzgado 9 Penal Municipal", etapa: 4 };

function responder(parcial: { vista?: unknown; salidas?: unknown; estado?: unknown; resumen?: unknown } = {}) {
  const respuestas = { vista: VISTA, salidas: { archivos: ARCHIVOS }, estado: ESTADO, resumen: RESUMEN, ...parcial };
  get.mockImplementation((ruta: string) => {
    const clave = ruta.endsWith("/vista/fallo") ? "vista" : ruta.endsWith("/salidas") ? "salidas" : ruta.endsWith("/estado") ? "estado" : ruta.endsWith("/resumen") ? "resumen" : null;
    if (!clave) return Promise.reject(new ErrorApi(404, "sin ruta", "sin ruta"));
    const valor = respuestas[clave];
    return valor instanceof Error ? Promise.reject(valor) : Promise.resolve(valor);
  });
}

beforeEach(() => {
  get.mockReset();
});

describe("Fallo", () => {
  it("muestra las páginas, las descargas y los avisos con datos reales", async () => {
    responder();
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByRole("heading", { name: "Vista previa del fallo" })).toBeTruthy();
    expect(screen.getAllByRole("region", { name: /^Página \d de 3$/ })).toHaveLength(3);
    expect(screen.getByText("JUZGADO DE PRUEBA").tagName).toBe("STRONG");
    expect(screen.getAllByText("Pie del juzgado")).toHaveLength(3);

    const fallo = screen.getByRole("link", { name: "Descargar fallo" });
    expect(fallo.getAttribute("href")).toBe(`/api/casos/caso-1/salidas/${P}/003FalloSegunda202600412.docx`);
    expect(fallo.getAttribute("download")).toBe("003FalloSegunda202600412.docx");
    expect(screen.getByRole("link", { name: "Descargar todo (.zip)" }).getAttribute("href")).toBe("/api/casos/caso-1/zip");
    expect(screen.getByRole("link", { name: "Descargar Acta de reparto de la impugnación" })).toBeTruthy();
    expect(screen.queryByText("fallo.vista.json")).toBeNull();
    expect(screen.getByRole("heading", { name: "Por radicar" })).toBeTruthy();
    expect(screen.getByText("Fallo generado")).toBeTruthy();

    const aside = screen.getByRole("complementary", { name: "Descargas" });
    expect(within(aside).getByText(/Quedó una cita con alerta \(sentencia SU-508 de 2020\)/)).toBeTruthy();
    expect(within(aside).getByText(/El proceso registró 1 alerta/)).toBeTruthy();
    expect(within(aside).getByText(/declaración de uso de IA/)).toBeTruthy();
    expect(within(aside).getByText("Quedó por radicar: Oficio a la Corte Constitucional.")).toBeTruthy();
  });

  it("pinta el texto del expediente como texto, nunca como HTML", async () => {
    responder();
    const { container } = render(<Fallo caso="caso-1" />);
    await screen.findByText(/Texto del asunto/);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy();
  });

  it("marca las citas con alerta y las anuncia a lectores de pantalla", async () => {
    responder();
    const { container } = render(<Fallo caso="caso-1" />);
    await screen.findByText("(sentencia SU-508 de 2020)");
    const cita = container.querySelector(".cita.revisar");
    expect(cita?.getAttribute("title")).toBe("Cobertura baja");
    expect(cita?.textContent).toContain("cita con alerta");
  });

  it("cambia de página con las flechas y con las miniaturas", async () => {
    responder();
    const { container } = render(<Fallo caso="caso-1" />);
    await screen.findByRole("heading", { name: "Vista previa del fallo" });
    const grupo = container.querySelector<HTMLElement>(".visor")!;
    const actual = () => screen.getByRole("button", { current: "page" }).getAttribute("aria-label");
    expect(actual()).toBe("Ir a la página 1");
    fireEvent.keyDown(grupo, { key: "ArrowRight" });
    expect(actual()).toBe("Ir a la página 2");
    expect(screen.getByRole("status", { name: "" }).textContent).toBeTruthy();
    fireEvent.keyDown(grupo, { key: "ArrowRight" });
    fireEvent.keyDown(grupo, { key: "ArrowRight" });
    expect(actual()).toBe("Ir a la página 3");
    fireEvent.keyDown(grupo, { key: "ArrowLeft" });
    expect(actual()).toBe("Ir a la página 2");
    fireEvent.click(screen.getByRole("button", { name: "Ir a la página 1" }));
    expect(actual()).toBe("Ir a la página 1");
    expect((screen.getByRole("button", { name: "Página anterior" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("avisa que el fallo aún no existe (404) y enlaza a la etapa correcta", async () => {
    responder({
      vista: new ErrorApi(404, "El fallo aún no existe.", "El fallo aún no existe."),
      salidas: { archivos: [`${P}/001ActaRepartoSegunda.pdf`] },
      estado: { estado: "esperando_decision", salidas: [], resumen: {}, job_activo: null },
    });
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByText("Aún no hay fallo para este caso")).toBeTruthy();
    const enlace = screen.getByRole("link", { name: "Ir a la decisión" });
    expect(enlace.getAttribute("href")).toBe("#/segunda/caso-1/decision");
    expect(screen.queryByRole("link", { name: "Descargar fallo" })).toBeNull();
  });

  it("si el fallo existe sin vista previa, ofrece la descarga y lo explica", async () => {
    responder({ vista: new ErrorApi(404, "sin vista", "sin vista") });
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByText("El fallo no tiene vista previa")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Descargar fallo" })).toBeTruthy();
  });

  it("muestra el estado real cuando el caso no está terminado", async () => {
    responder({ estado: { ...ESTADO, estado: "error", error: "x" } });
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByText("Proceso con error")).toBeTruthy();
  });

  it("muestra un error de API y permite reintentar", async () => {
    responder({ vista: new ErrorApi(500, "Fallo interno", "Fallo interno") });
    render(<Fallo caso="caso-1" />);
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("No se pudo cargar el fallo");
    expect(alerta.textContent).toContain("Fallo interno");
    responder();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("heading", { name: "Vista previa del fallo" })).toBeTruthy();
  });

  it("pide solo el resumen de este caso y lo usa en la cabecera", async () => {
    responder();
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Quintero c. EPS" })).toBeTruthy();
    expect(screen.getByText("Radicado 05001408800920260041200")).toBeTruthy();
    const rutas = get.mock.calls.map((c) => c[0]);
    expect(rutas).toContain("/api/casos/caso-1/resumen");
    expect(rutas).not.toContain("/api/casos");
  });

  it("si el resumen falla, la cabecera sale de los metadatos del estado", async () => {
    responder({
      resumen: new ErrorApi(500, "boom", "boom"),
      estado: { ...ESTADO, resumen: { ...ESTADO.resumen, metadatos: { cui_2a: "05001-2", juzgado_a_quo: "Juzgado de metadatos" } } },
    });
    render(<Fallo caso="caso-1" />);
    expect(await screen.findByText("Radicado 05001-2")).toBeTruthy();
    expect(screen.getByText("Juzgado de metadatos")).toBeTruthy();
  });

  it("reconoce el caso inexistente por el detalle de la vista", async () => {
    responder({
      vista: new ErrorApi(404, "Caso no encontrado.", "Caso no encontrado."),
      salidas: new ErrorApi(500, "x", "x"),
      estado: new ErrorApi(500, "x", "x"),
    });
    render(<Fallo caso="x" />);
    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  it("distingue un caso inexistente", async () => {
    const noExiste = new ErrorApi(404, "Caso no encontrado.", "Caso no encontrado.");
    responder({ vista: noExiste, salidas: noExiste, estado: noExiste });
    render(<Fallo caso="x" />);
    await waitFor(() => expect(screen.getByText("No se encontró el caso")).toBeTruthy());
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
  });
});
