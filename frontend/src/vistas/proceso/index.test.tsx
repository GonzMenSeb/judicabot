import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Evento } from "../../api/contrato";
import { casoActual, jobActual, toasts } from "../../estado";
import Proceso from "./index";

class FuenteSimulada {
  static instancias: FuenteSimulada[] = [];
  readonly url: string;
  cerrada = false;
  private oyentes = new Map<string, Array<(ev: Event) => void>>();

  constructor(url: string) {
    this.url = url;
    FuenteSimulada.instancias.push(this);
  }

  addEventListener(tipo: string, oyente: (ev: Event) => void) {
    this.oyentes.set(tipo, [...(this.oyentes.get(tipo) ?? []), oyente]);
  }

  close() {
    this.cerrada = true;
  }

  emitir(tipo: string, datos?: unknown) {
    const ev = datos === undefined ? new Event(tipo) : new MessageEvent(tipo, { data: JSON.stringify(datos) });
    this.oyentes.get(tipo)?.forEach((o) => o(ev));
  }
}

const evento = (n: number, etapa: Evento["etapa"], tipo: Evento["tipo"] = "lee", texto = `paso ${n}`): Evento => ({
  n,
  t: new Date(Date.UTC(2026, 10, 3, 12, 0, n * 5)).toISOString(),
  etapa,
  tipo,
  texto,
  datos: null,
});

interface Servidor {
  estado: Record<string, unknown>;
  estadoStatus: number;
  resumen: Record<string, unknown>;
  llamadas: string[];
  jobs: Record<string, { caso: string; cmd: string }>;
  nuevoJob: string;
  runs: unknown[];
}

let servidor: Servidor;

const json = (cuerpo: unknown, status = 200) => new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } });

function instalarFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (ruta: string, init?: RequestInit) => {
      const metodo = init?.method ?? "GET";
      servidor.llamadas.push(ruta);
      if (/^\/api\/casos\/c1\/resumen$/.test(ruta)) return json(servidor.resumen);
      if (/^\/api\/casos\/c1\/estado$/.test(ruta)) return json(servidor.estado, servidor.estadoStatus);
      if (metodo === "POST" && ruta === "/api/casos/c1/run") {
        servidor.runs.push(JSON.parse(String(init?.body)));
        return json({ job_id: servidor.nuevoJob });
      }
      const job = /^\/api\/jobs\/([^/]+)$/.exec(ruta)?.[1];
      if (job) {
        const datos = servidor.jobs[job];
        return datos ? json({ id: job, estado: "corriendo", error: null, ...datos }) : json({ detail: "Job no encontrado." }, 404);
      }
      return json({ detail: "no mockeado" }, 404);
    }),
  );
}

const ultima = () => FuenteSimulada.instancias[FuenteSimulada.instancias.length - 1]!;
const emitir = (tipo: string, datos?: unknown) => act(() => ultima().emitir(tipo, datos));

async function montar(caso = "c1") {
  render(<Proceso caso={caso} />);
  await waitFor(() => expect(FuenteSimulada.instancias.length).toBeGreaterThan(0));
}

const etapa = (nombre: RegExp) => screen.getByRole("button", { name: nombre });

beforeEach(() => {
  FuenteSimulada.instancias = [];
  servidor = {
    estado: { ok: true, estado: "revision", error: null, job_activo: "j1", resumen: {} },
    estadoStatus: 200,
    resumen: { id: "c1", nombre: "Quintero c. EPS", radicado: "05001408800920260041200", juzgado_a_quo: "Juzgado 9 Penal Municipal", etapa: 1 },
    llamadas: [],
    jobs: { j1: { caso: "c1", cmd: "iniciar" } },
    nuevoJob: "j2",
    runs: [],
  };
  jobActual.value = null;
  casoActual.value = null;
  toasts.value = [];
  instalarFetch();
  vi.stubGlobal("EventSource", FuenteSimulada);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("proceso en vivo", () => {
  it("agrupa los eventos por etapa y sigue la etapa activa", async () => {
    await montar();
    expect(ultima().url).toBe("/api/jobs/j1/eventos");
    emitir("open");
    emitir("evento", evento(1, "ingesta", "lee", "Abro la carpeta"));
    emitir("evento", evento(2, "ingesta", "verifica", "OCR listo"));
    emitir("evento", evento(3, "apertura", "escribe", "Redacto los antecedentes"));

    expect(await screen.findByRole("heading", { level: 2, name: "Apertura" })).toBeTruthy();
    expect(etapa(/Lectura del expediente/).textContent).toContain("2 pasos");
    expect(etapa(/^Apertura/).textContent).toContain("1 paso");
    expect(etapa(/^Apertura/).textContent).toContain("(en curso)");
    expect(etapa(/Lectura del expediente/).textContent).toContain("(completada)");
    expect(etapa(/Verificación de citas/).textContent).toContain("(pendiente)");
    expect(screen.getByText("Redacto los antecedentes")).toBeTruthy();
    expect(screen.queryByText("Abro la carpeta")).toBeNull();
    expect(screen.getByText("Conectado · Apertura")).toBeTruthy();
  });

  it("permite fijar una etapa y volver a seguir lo que ocurre", async () => {
    await montar();
    emitir("evento", evento(1, "ingesta", "lee", "Abro la carpeta"));
    emitir("evento", evento(2, "apertura", "lee", "Entrego los documentos"));

    fireEvent.click(etapa(/Lectura del expediente/));
    expect(screen.getByRole("heading", { level: 2, name: "Lectura del expediente" })).toBeTruthy();
    expect(screen.getByText("Abro la carpeta")).toBeTruthy();
    expect(etapa(/Lectura del expediente/).getAttribute("aria-pressed")).toBe("true");

    emitir("evento", evento(3, "apertura", "escribe", "Redacto"));
    expect(screen.getByRole("heading", { level: 2, name: "Lectura del expediente" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Volver a lo que ocurre ahora" }));
    expect(screen.getByRole("heading", { level: 2, name: "Apertura" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Volver a lo que ocurre ahora" })).toBeNull();
  });

  it("muestra «Razona» solo si llegan eventos de ese tipo", async () => {
    await montar();
    emitir("evento", evento(1, "ingesta", "lee", "Abro la carpeta"));
    expect(screen.queryByText("Razona")).toBeNull();
    expect(screen.getByText(/Pasos registrados por el sistema/)).toBeTruthy();

    emitir("evento", evento(2, "ingesta", "razona", "El fallo dice NIEGA"));
    expect(screen.getByText("Razona")).toBeTruthy();
    expect(screen.getByText(/Resumen del razonamiento del modelo/)).toBeTruthy();
  });

  it("pinta el texto del expediente como texto, nunca como HTML", async () => {
    await montar();
    const peligroso = '<img src="x" onerror="alert(1)"><b>negrita</b>';
    emitir("evento", evento(1, "ingesta", "lee", peligroso));
    expect(screen.getByText(peligroso)).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector(".tz-x b")).toBeNull();
  });

  it("al terminar con el borrador listo ofrece «Ver el borrador»", async () => {
    servidor.estado = { ok: true, estado: "esperando_decision", error: null, job_activo: "j1", resumen: {} };
    await montar();
    emitir("evento", evento(1, "verificacion", "verifica"));
    emitir("fin", { estado: "terminado", error: null });

    const enlace = await screen.findByRole("link", { name: "Ver el borrador" });
    expect(enlace.getAttribute("href")).toBe("#/segunda/c1/borrador");
    expect(screen.getByText("Ejecución terminada")).toBeTruthy();
    expect(ultima().cerrada).toBe(true);
  });

  it("al terminar con el fallo listo ofrece «Ver el fallo»", async () => {
    servidor.estado = { ok: true, estado: "terminado", error: null, job_activo: "j1", resumen: {} };
    await montar();
    emitir("evento", evento(1, "documentos", "escribe"));
    emitir("fin", { estado: "terminado", error: null });
    const enlace = await screen.findByRole("link", { name: "Ver el fallo" });
    expect(enlace.getAttribute("href")).toBe("#/segunda/c1/fallo");
  });

  it("en error muestra el mensaje y «Continuar» abre una nueva conexión", async () => {
    await montar();
    emitir("evento", evento(1, "consideraciones", "error", "El modelo respondió mal"));
    emitir("fin", { estado: "error", error: "No se pudo validar la respuesta del modelo." });

    const alerta = await screen.findByRole("alert");
    expect(within(alerta).getByText("No se pudo validar la respuesta del modelo.")).toBeTruthy();
    expect(within(alerta).getByRole("link", { name: "Volver a documentos" }).getAttribute("href")).toBe("#/segunda/c1/documentos");
    expect(etapa(/Consideraciones/).textContent).toContain("(con error)");

    const primera = ultima();
    fireEvent.click(within(alerta).getByRole("button", { name: "Continuar" }));
    await waitFor(() => expect(FuenteSimulada.instancias).toHaveLength(2));
    expect(servidor.runs).toEqual([{ cmd: "continuar" }]);
    expect(ultima().url).toBe("/api/jobs/j2/eventos");
    expect(primera.cerrada).toBe(true);
    expect(jobActual.value).toBe("j2");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("si el error ocurrió al decidir, «Volver» lleva a la decisión", async () => {
    servidor.jobs.j1 = { caso: "c1", cmd: "decidir" };
    await montar();
    emitir("fin", { estado: "error", error: null });
    const alerta = await screen.findByRole("alert");
    expect(within(alerta).getByRole("link", { name: "Volver a la decisión" }).getAttribute("href")).toBe("#/segunda/c1/decision");
    expect(within(alerta).getByText("La ejecución se detuvo antes de terminar.")).toBeTruthy();
  });

  it("reconecta con el cursor y muestra el estado de la conexión", async () => {
    await montar();
    emitir("open");
    emitir("evento", evento(1, "ingesta"));
    emitir("evento", evento(2, "ingesta"));
    expect(screen.getByText(/^Conectado/)).toBeTruthy();

    vi.useFakeTimers();
    const primera = ultima();
    emitir("error");
    expect(primera.cerrada).toBe(true);
    expect(screen.getByText("Reconectando…")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(FuenteSimulada.instancias).toHaveLength(2);
    expect(ultima().url).toBe("/api/jobs/j1/eventos?desde=2");
    emitir("open");
    emitir("evento", evento(3, "ingesta"));
    expect(screen.getByText(/^Conectado/)).toBeTruthy();
    expect(screen.getByText("paso 3")).toBeTruthy();
    expect(screen.getAllByText("paso 2")).toHaveLength(1);
  });

  it("declara la pérdida de conexión y permite reintentar", async () => {
    await montar();
    emitir("evento", evento(1, "ingesta"));
    vi.useFakeTimers();
    for (let i = 0; i < 9; i++) {
      emitir("error");
      act(() => {
        vi.advanceTimersByTime(5000);
      });
    }
    vi.useRealTimers();
    expect(screen.getByText("Sin conexión con el servidor")).toBeTruthy();
    const aviso = await screen.findByText("Se perdió la conexión con el servidor");
    expect(aviso).toBeTruthy();

    const antes = FuenteSimulada.instancias.length;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(FuenteSimulada.instancias.length).toBe(antes + 1));
    expect(ultima().url).toBe("/api/jobs/j1/eventos");
    expect(screen.queryByText("Se perdió la conexión con el servidor")).toBeNull();
  });

  it("cierra la conexión al desmontar", async () => {
    const { unmount } = render(<Proceso caso="c1" />);
    await waitFor(() => expect(FuenteSimulada.instancias).toHaveLength(1));
    const fuente = ultima();
    expect(fuente.cerrada).toBe(false);
    unmount();
    expect(fuente.cerrada).toBe(true);
  });

  it("pausa el autoscroll si el usuario sube y lo retoma con el botón", async () => {
    await montar();
    emitir("evento", evento(1, "ingesta"));
    const panel = document.querySelector<HTMLElement>(".tz-der")!;
    Object.defineProperty(panel, "scrollHeight", { configurable: true, get: () => 1000 });
    Object.defineProperty(panel, "clientHeight", { configurable: true, value: 400 });

    emitir("evento", evento(2, "ingesta"));
    expect(panel.scrollTop).toBe(1000);

    panel.scrollTop = 100;
    fireEvent.scroll(panel);
    const ir = await screen.findByRole("button", { name: "Ir al último paso" });
    emitir("evento", evento(3, "ingesta"));
    expect(panel.scrollTop).toBe(100);

    fireEvent.click(ir);
    expect(panel.scrollTop).toBe(1000);
    expect(screen.queryByRole("button", { name: "Ir al último paso" })).toBeNull();
    emitir("evento", evento(4, "ingesta"));
    expect(panel.scrollTop).toBe(1000);
  });
});

describe("sin ejecución activa", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", FuenteSimulada);
  });

  it("ofrece el borrador si ya está listo", async () => {
    servidor.estado = { ok: true, estado: "esperando_decision", error: null, job_activo: null, resumen: {} };
    render(<Proceso caso="c1" />);
    const enlace = await screen.findByRole("link", { name: "Ver el borrador" });
    expect(enlace.getAttribute("href")).toBe("#/segunda/c1/borrador");
    expect(FuenteSimulada.instancias).toHaveLength(0);
  });

  it("ofrece el fallo si el caso terminó", async () => {
    servidor.estado = { ok: true, estado: "terminado", error: null, job_activo: null, resumen: {} };
    render(<Proceso caso="c1" />);
    expect((await screen.findByRole("link", { name: "Ver el fallo" })).getAttribute("href")).toBe("#/segunda/c1/fallo");
  });

  it("lleva a documentos si la redacción no se ha iniciado", async () => {
    servidor.estado = { ok: true, estado: "revision", error: null, job_activo: null, resumen: {} };
    render(<Proceso caso="c1" />);
    const enlace = await screen.findByRole("link", { name: "Ir a documentos" });
    expect(enlace.getAttribute("href")).toBe("#/segunda/c1/documentos");
  });

  it("ofrece continuar si el caso quedó a medias", async () => {
    servidor.estado = { ok: false, estado: "error", error: "Quedó a medias en apertura.", job_activo: null, resumen: {} };
    render(<Proceso caso="c1" />);
    const alerta = await screen.findByRole("alert");
    expect(within(alerta).getByText("Quedó a medias en apertura.")).toBeTruthy();
    fireEvent.click(within(alerta).getByRole("button", { name: "Continuar" }));
    await waitFor(() => expect(FuenteSimulada.instancias).toHaveLength(1));
    expect(ultima().url).toBe("/api/jobs/j2/eventos");
  });

  it("ignora un job recordado que pertenece a otro caso", async () => {
    servidor.estado = { ok: true, estado: "revision", error: null, job_activo: null, resumen: {} };
    servidor.jobs.jx = { caso: "otro", cmd: "iniciar" };
    jobActual.value = "jx";
    render(<Proceso caso="c1" />);
    await screen.findByRole("link", { name: "Ir a documentos" });
    expect(FuenteSimulada.instancias).toHaveLength(0);
  });

  it("usa el job recordado cuando pertenece al caso", async () => {
    servidor.estado = { ok: true, estado: "revision", error: null, job_activo: null, resumen: {} };
    servidor.jobs.jy = { caso: "c1", cmd: "iniciar" };
    jobActual.value = "jy";
    render(<Proceso caso="c1" />);
    await waitFor(() => expect(FuenteSimulada.instancias).toHaveLength(1));
    expect(ultima().url).toBe("/api/jobs/jy/eventos");
  });
});

describe("errores de la API", () => {
  it("muestra el error al consultar el estado y permite reintentar", async () => {
    servidor.estadoStatus = 500;
    servidor.estado = { detail: "Fallo interno del servidor." };
    render(<Proceso caso="c1" />);
    const alerta = await screen.findByRole("alert");
    expect(within(alerta).getByText("No se pudo consultar el caso")).toBeTruthy();
    expect(within(alerta).getByText("Fallo interno del servidor.")).toBeTruthy();

    servidor.estadoStatus = 200;
    servidor.estado = { ok: true, estado: "revision", error: null, job_activo: "j1", resumen: {} };
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(FuenteSimulada.instancias).toHaveLength(1));
  });

  it("si el caso no existe lo dice y no ofrece reintentar", async () => {
    servidor.estadoStatus = 404;
    servidor.estado = { detail: "Caso no encontrado." };
    render(<Proceso caso="c1" />);
    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(FuenteSimulada.instancias).toHaveLength(0);
  });

  it("pide solo el resumen de este caso y lo muestra en la cabecera", async () => {
    await montar();
    expect(await screen.findByRole("heading", { level: 1, name: "Quintero c. EPS" })).toBeTruthy();
    expect(screen.getByText("Radicado 05001408800920260041200")).toBeTruthy();
    expect(servidor.llamadas).toContain("/api/casos/c1/resumen");
    expect(servidor.llamadas).not.toContain("/api/casos");
  });

  it("si «Continuar» responde 409 avisa y se conecta al job en curso", async () => {
    await montar();
    emitir("fin", { estado: "error", error: "Falló." });
    const alerta = await screen.findByRole("alert");

    servidor.estado = { ok: true, estado: "revision", error: null, job_activo: "j9", resumen: {} };
    servidor.jobs.j9 = { caso: "c1", cmd: "continuar" };
    const base = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (ruta: string, init?: RequestInit) =>
        init?.method === "POST" ? json({ detail: "Ya hay una ejecución en curso para este caso." }, 409) : base(ruta, init),
      ),
    );
    fireEvent.click(within(alerta).getByRole("button", { name: "Continuar" }));
    await waitFor(() => expect(ultima().url).toBe("/api/jobs/j9/eventos"));
    expect(toasts.value.some((t) => t.texto.includes("Ya hay una ejecución en curso"))).toBe(true);
  });
});
