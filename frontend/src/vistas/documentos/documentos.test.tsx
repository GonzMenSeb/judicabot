import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { estadoServidor } from "../../estado";
import Documentos from "./index";
import type { DocResumen, EstadoCaso, ResumenIngesta } from "./tipos";

interface Llamada {
  metodo: string;
  ruta: string;
  cuerpo: unknown;
}

type Salida = { estado: number; cuerpo: unknown };
type Manejador = (cuerpo: unknown) => Salida;

const ok = (cuerpo: unknown): Salida => ({ estado: 200, cuerpo });
const fallo = (estado: number, detail: string): Salida => ({ estado, cuerpo: { detail } });

function instalar(rutas: Record<string, Manejador>) {
  const llamadas: Llamada[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (ruta: string, init?: RequestInit) => {
      const metodo = init?.method ?? "GET";
      const cuerpo = init?.body ? JSON.parse(String(init.body)) : undefined;
      llamadas.push({ metodo, ruta, cuerpo });
      const manejador = rutas[`${metodo} ${ruta.split("?")[0]}`];
      const salida = manejador ? manejador(cuerpo) : fallo(404, `sin ruta ${metodo} ${ruta}`);
      return { ok: salida.estado < 400, status: salida.estado, json: async () => salida.cuerpo };
    }),
  );
  return llamadas;
}

function doc(n: number, rol: DocResumen["rol"], extra: Partial<DocResumen> = {}): DocResumen {
  const nombre = `${String(n).padStart(3, "0")}.pdf`;
  return {
    doc_id: `d${n}`,
    ruta: `01PrimeraInstancia/C01Principal/${nombre}`,
    nombre,
    rol,
    rol_origen: "contenido",
    evidencia: `Evidencia del documento ${n}`,
    paginas: 2,
    paginas_sin_texto: 0,
    ruido: false,
    ajeno: false,
    jev_rol: rol,
    jev_confianza: 0.97,
    jev_umbral: 0.9,
    ...extra,
  };
}

function ingesta(documentos: DocResumen[], extra: Partial<ResumenIngesta> = {}): ResumenIngesta {
  return {
    n_documentos: documentos.length,
    documentos,
    faltantes: [],
    esperados_faltantes: [],
    alertas: [],
    docs_ajenos: [],
    auto: { fecha: "2026-10-22", fecha_reparto: "2026-10-21", accionante: "MARTA QUINTERO", accionada: "EPS HORIZONTE" },
    ...extra,
  };
}

const DOCS = [
  doc(1, "escrito_tutela", { jev_confianza: 0.98 }),
  doc(2, "fallo_a_quo"),
  doc(3, "impugnacion"),
  doc(4, "otro", { jev_rol: "memorial", jev_confianza: 0.94, paginas_sin_texto: 1 }),
];

const estadoRevision = (res: ResumenIngesta = ingesta(DOCS)): EstadoCaso => ({
  ok: true,
  estado: res.faltantes.length ? "incompleto" : "revision",
  salidas: ["02SegundaInstancia/C01Principal/002AutoAsumeSegunda1.docx", "trabajo/previo.docx"],
  resumen: res,
  error: null,
  job_activo: null,
});

const resumenCaso = (n_insumos = 4) => ({
  id: "c1",
  nombre: "Quintero c. EPS",
  radicado: "05001408800920260041200",
  accionante: null,
  accionadas: [],
  juzgado_a_quo: "Juzgado 9 Penal Municipal",
  estado: "revision",
  etapa: 0,
  siguiente_paso: "",
  n_insumos,
  n_alertas: 0,
  job_activo: null,
  actualizado: "2026-11-03T10:00:00Z",
});

const servidor = { api_key: true, jev_key: false, modelo: "claude-sonnet-5-5", modelos: ["claude-sonnet-5-5"] };

function base(estado: EstadoCaso, extra: Record<string, Manejador> = {}) {
  return instalar({
    "GET /api/casos/c1/estado": () => ok(estado),
    "GET /api/casos/c1/resumen": () => ok(resumenCaso()),
    "GET /api/casos/c1/config": () => ok({ llm: { proveedor: "anthropic" } }),
    "GET /api/estado-servidor": () => ok(servidor),
    ...extra,
  });
}

beforeEach(() => {
  location.hash = "#/segunda/c1/documentos";
  estadoServidor.value = servidor;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Documentos", () => {
  it("muestra los documentos con rol, confianza de Jev y evidencia", async () => {
    base(estadoRevision());
    render(<Documentos caso="c1" />);

    expect(await screen.findByRole("heading", { name: "Quintero c. EPS", level: 1 })).toBeTruthy();
    expect((screen.getByLabelText("Rol de 001.pdf") as HTMLSelectElement).value).toBe("escrito_tutela");
    expect(screen.getByText(/98\s%\sde confianza/)).toBeTruthy();
    expect(document.querySelector(".docs-jev.discrepa")?.textContent).toMatch(/Jev propone Memorial, 94\s%\sde confianza/);
    expect(screen.getByText("Están las piezas obligatorias")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Descargar Auto que asume el conocimiento/ }).getAttribute("href")).toBe(
      "/api/casos/c1/salidas/02SegundaInstancia/C01Principal/002AutoAsumeSegunda1.docx",
    );
    expect(screen.queryByText("Evidencia del documento 1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Evidencia de 001\.pdf/ }));
    expect(screen.getByText("Evidencia del documento 1")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Evidencia de 001\.pdf/ }).getAttribute("aria-expanded")).toBe("true");
  });

  it("indica Reglas del código cuando Jev no opinó y muestra faltantes y esperados", async () => {
    const sinJev = { jev_rol: null, jev_confianza: null, jev_umbral: null };
    base(
      estadoRevision(
        ingesta([doc(1, "escrito_tutela", sinJev), doc(2, "impugnacion", sinJev)], {
          faltantes: ["fallo_a_quo"],
          esperados_faltantes: ["auto_admisorio"],
        }),
      ),
    );
    render(<Documentos caso="c1" />);

    expect(await screen.findAllByText("Reglas del código")).toHaveLength(2);
    expect(screen.getByText("Faltan piezas obligatorias")).toBeTruthy();
    expect(screen.getByText("No se encontró (se continúa sin ello)").parentElement?.textContent).toContain("Auto admisorio.");
    expect((screen.getByRole("button", { name: "Iniciar redacción" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("muestra el error de la API y permite reintentar", async () => {
    let intento = 0;
    base(estadoRevision(), {
      "GET /api/casos/c1/estado": () => (++intento === 1 ? fallo(500, "No se pudo leer el estado del caso: boom") : ok(estadoRevision())),
    });
    render(<Documentos caso="c1" />);

    expect((await screen.findByRole("alert")).textContent).toContain("No se pudo leer el estado del caso: boom");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByLabelText("Rol de 001.pdf")).toBeTruthy();
  });

  it("si no hay conexión muestra un mensaje claro y no el error técnico del navegador", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<Documentos caso="c1" />);

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("No se pudo conectar con el servidor. Revise su conexión e intente de nuevo.");
    expect(alerta.textContent).not.toContain("Failed to fetch");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeTruthy();
  });

  it("pide solo el resumen de este caso, no la lista completa", async () => {
    const llamadas = base(estadoRevision());
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 001.pdf");
    const rutas = llamadas.map((l) => l.ruta);
    expect(rutas).toContain("/api/casos/c1/resumen");
    expect(rutas).not.toContain("/api/casos");
    expect(screen.getByText("Radicado 05001408800920260041200")).toBeTruthy();
  });

  it("sigue mostrando los documentos si el resumen falla", async () => {
    base(estadoRevision(), { "GET /api/casos/c1/resumen": () => fallo(500, "boom") });
    render(<Documentos caso="c1" />);

    expect(await screen.findByLabelText("Rol de 001.pdf")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "c1", level: 1 })).toBeTruthy();
  });

  it("si el caso no existe lo dice y vuelve a la lista, sin ofrecer reintentar", async () => {
    base(estadoRevision(), { "GET /api/casos/c1/estado": () => fallo(404, "Caso no encontrado.") });
    render(<Documentos caso="c1" />);

    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(screen.queryByLabelText("Rol de 001.pdf")).toBeNull();
  });

  it("acepta la propuesta de Jev, guarda los roles y la bandeja inicia la redacción", async () => {
    const llamadas = base(estadoRevision(), {
      "PUT /api/casos/c1/revision": () => ok({ ...estadoRevision(), error: null }),
      "POST /api/casos/c1/run": () => ok({ job_id: "j1" }),
    });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 004.pdf");
    fireEvent.click(screen.getByRole("button", { name: /Aceptar Memorial como rol de 004\.pdf/ }));
    expect((screen.getByLabelText("Rol de 004.pdf") as HTMLSelectElement).value).toBe("memorial");
    expect(screen.getByText(/1 rol cambiado/)).toBeTruthy();

    fireEvent.input(screen.getByLabelText("Accionante"), { target: { value: "ANA PÉREZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));

    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.cuerpo).toEqual({ roles: { d4: "memorial" }, auto: { accionante: "ANA PÉREZ" } });
    expect(llamadas.find((l) => l.metodo === "POST" && l.ruta === "/api/casos/c1/run")?.cuerpo).toEqual({ cmd: "iniciar" });
  });

  it("no inicia si el cambio de roles deja el caso incompleto", async () => {
    const llamadas = base(estadoRevision(), {
      "PUT /api/casos/c1/revision": () => ok(estadoRevision(ingesta(DOCS, { faltantes: ["impugnacion"] }))),
    });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 003.pdf");
    fireEvent.change(screen.getByLabelText("Rol de 003.pdf"), { target: { value: "anexo" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));

    expect((await screen.findByText(/Faltan piezas obligatorias: Impugnación/)).textContent).toContain("Corrija los roles");
    expect(llamadas.some((l) => l.ruta.endsWith("/run"))).toBe(false);
    expect(location.hash).toBe("#/segunda/c1/documentos");
  });

  it("pide la clave de la API antes de iniciar cuando falta", async () => {
    let clave = false;
    const llamadas = base(estadoRevision(), {
      "GET /api/estado-servidor": () => ok({ ...servidor, api_key: clave }),
      "POST /api/api-key": () => {
        clave = true;
        return ok({ api_key: true });
      },
      "POST /api/casos/c1/run": () => ok({ job_id: "j2" }),
    });
    estadoServidor.value = { ...servidor, api_key: false };
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 001.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));
    const campo = await screen.findByLabelText("Clave de la API");
    expect(llamadas.some((l) => l.ruta.endsWith("/run"))).toBe(false);

    fireEvent.input(campo, { target: { value: "sk-ant-prueba" } });
    fireEvent.click(within(document.querySelector("dialog") as HTMLElement).getByRole("button", { name: "Guardar y continuar" }));

    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    expect(llamadas.find((l) => l.ruta === "/api/api-key")?.cuerpo).toEqual({ key: "sk-ant-prueba" });
  });

  it("al cerrar con Escape el diálogo de la clave devuelve el foco a «Iniciar redacción»", async () => {
    base(estadoRevision(), { "GET /api/estado-servidor": () => ok({ ...servidor, api_key: false }) });
    estadoServidor.value = { ...servidor, api_key: false };
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 001.pdf");
    const iniciar = screen.getByRole("button", { name: "Iniciar redacción" }) as HTMLButtonElement;
    new MutationObserver(() => {
      if (!iniciar.disabled || document.activeElement !== iniciar) return;
      iniciar.disabled = false;
      iniciar.blur();
      iniciar.disabled = true;
    }).observe(iniciar, { attributes: true, attributeFilter: ["disabled"] });

    iniciar.focus();
    fireEvent.click(iniciar);
    const campo = await screen.findByLabelText("Clave de la API");
    await waitFor(() => expect(document.activeElement).toBe(campo));

    fireEvent.keyDown(campo, { key: "Escape" });
    await waitFor(() => expect(document.querySelector("dialog")?.hasAttribute("open")).toBe(false));
    expect(document.activeElement).toBe(iniciar);
  });

  it("avisa cuando ya hay una ejecución en curso (409)", async () => {
    base(estadoRevision(), { "POST /api/casos/c1/run": () => fallo(409, "Ya hay una ejecución en curso para este caso.") });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 001.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));

    expect(await screen.findByText("Ya hay una ejecución en curso para este caso.")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Ver el proceso" })[0]?.getAttribute("href")).toBe("#/segunda/c1/proceso");
    expect(location.hash).toBe("#/segunda/c1/documentos");
  });

  it("ofrece procesar un caso sin iniciar y muestra los documentos al terminar", async () => {
    let leido = false;
    const llamadas = base(
      { ok: true, estado: "sin_iniciar", salidas: [], resumen: {}, error: null, job_activo: null },
      {
        "GET /api/casos/c1/estado": () => ok(leido ? estadoRevision() : { ok: true, estado: "sin_iniciar", salidas: [], resumen: {}, error: null, job_activo: null }),
        "POST /api/casos/c1/run": () => ok({ job_id: "j3" }),
        "GET /api/jobs/j3": () => {
          leido = true;
          return ok({ id: "j3", caso: "c1", cmd: "nuevo", estado: "terminado", error: null });
        },
      },
    );
    render(<Documentos caso="c1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Procesar los documentos" }));
    expect(await screen.findByLabelText("Rol de 001.pdf")).toBeTruthy();
    expect(llamadas.find((l) => l.metodo === "POST")?.cuerpo).toEqual({ cmd: "nuevo" });
  });

  it("deja la clasificación en solo lectura cuando la redacción ya inició", async () => {
    base({ ...estadoRevision(), estado: "esperando_decision", ingesta: ingesta(DOCS), resumen: { alertas: [] } as EstadoCaso["resumen"] });
    render(<Documentos caso="c1" />);

    const rol = (await screen.findByLabelText("Rol de 001.pdf")) as HTMLSelectElement;
    expect(rol.disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Ver el borrador" }).getAttribute("href")).toBe("#/segunda/c1/borrador");
    expect(screen.queryByRole("button", { name: "Iniciar redacción" })).toBeNull();
  });
});
