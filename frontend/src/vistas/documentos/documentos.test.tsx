import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Evento } from "../../api/contrato";
import { estadoServidor } from "../../estado";
import Documentos from "./index";
import { Progreso } from "./Progreso";
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
    revisar: false,
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
    docs_revisar: [],
    auto: {
      fecha: "2026-10-22",
      fecha_reparto: "2026-10-21",
      accionante: "MARTA QUINTERO",
      accionada: "EPS HORIZONTE",
      firmante: null,
      cargo_firmante: null,
    },
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

const SIN_JEV = { jev_rol: null, jev_confianza: null, jev_umbral: null };
const paraRevisar = (n: number, extra: Partial<DocResumen> = {}) => doc(n, "otro", { revisar: true, evidencia: "Cartas del a quo", ...SIN_JEV, ...extra });
const conRevisar = (ids: number[] = [5]) =>
  ingesta([...DOCS, ...ids.map((n) => paraRevisar(n))], { docs_revisar: ids.map((n) => `d${n}`) });
const filaDe = (nombre: string) => screen.getByLabelText(`Rol de ${nombre}`).closest("li") as HTMLElement;
const dialogoRevisar = async () =>
  (await screen.findByRole("heading", { name: "Hay documentos para revisar" })).closest("dialog") as HTMLElement;
const CONFIRMAR = { name: "Es de este caso: confirmar" };

describe("Documentos para revisar", () => {
  it("marca «Para revisar» distinto de «Ajeno»: el documento sigue incluido, con su rol, y explica el motivo", async () => {
    const res = ingesta([...DOCS, paraRevisar(5), doc(6, "otro", { ajeno: true, ...SIN_JEV })], { docs_revisar: ["d5"], docs_ajenos: ["d6"] });
    base(estadoRevision(res));
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    const revisar = within(filaDe("005.pdf"));
    expect(revisar.getByText("Para revisar")).toBeTruthy();
    expect(revisar.queryByText("Ajeno")).toBeNull();
    expect(revisar.getByText(/encabezado es de otro radicado.*nombra a las partes.*marca/)).toBeTruthy();
    expect((screen.getByLabelText("Rol de 005.pdf") as HTMLSelectElement).disabled).toBe(false);
    expect((screen.getByLabelText("Rol de 005.pdf") as HTMLSelectElement).value).toBe("otro");
    expect(revisar.getByRole("checkbox", CONFIRMAR)).toBeTruthy();

    const ajeno = within(filaDe("006.pdf"));
    expect(ajeno.getByText("Ajeno")).toBeTruthy();
    expect(ajeno.queryByText("Para revisar")).toBeNull();
    expect(ajeno.queryByRole("checkbox", CONFIRMAR)).toBeNull();
    expect(within(filaDe("001.pdf")).queryByText("Para revisar")).toBeNull();
  });

  it("confirmar reenvía el rol del documento y, al guardar, deja de estar para revisar", async () => {
    const confirmado = ingesta([...DOCS, paraRevisar(5, { rol_origen: "usuario", revisar: false })]);
    const llamadas = base(estadoRevision(conRevisar()), { "PUT /api/casos/c1/revision": () => ok(estadoRevision(confirmado)) });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR));
    expect((within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/1 rol cambiado/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(within(filaDe("005.pdf")).queryByText("Para revisar")).toBeNull());
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ roles: { d5: "otro" } });
    expect(within(filaDe("005.pdf")).queryByRole("checkbox", CONFIRMAR)).toBeNull();
  });

  it("desmarcar la confirmación deshace el cambio", async () => {
    base(estadoRevision(conRevisar()));
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    const casilla = within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR) as HTMLInputElement;
    fireEvent.click(casilla);
    fireEvent.click(casilla);
    expect(casilla.checked).toBe(false);
    expect(screen.queryByRole("button", { name: "Guardar cambios" })).toBeNull();
  });

  it("elegir el rol que ya tenía también confirma el documento", async () => {
    base(estadoRevision(conRevisar()));
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.change(screen.getByLabelText("Rol de 005.pdf"), { target: { value: "anexo" } });
    fireEvent.change(screen.getByLabelText("Rol de 005.pdf"), { target: { value: "otro" } });
    expect((within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR) as HTMLInputElement).checked).toBe(true);
  });

  it("al iniciar con documentos sin confirmar pide confirmación, los lista y no bloquea", async () => {
    const llamadas = base(estadoRevision(conRevisar([5, 6])), { "POST /api/casos/c1/run": () => ok({ job_id: "j1" }) });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));
    const dialogo = within(await dialogoRevisar());
    expect(dialogo.getByText("005.pdf")).toBeTruthy();
    expect(dialogo.getByText("006.pdf")).toBeTruthy();
    expect(dialogo.queryByText("001.pdf")).toBeNull();
    expect(llamadas.some((l) => l.ruta.endsWith("/run"))).toBe(false);

    fireEvent.click(dialogo.getByRole("button", { name: "Continuar de todos modos" }));
    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    expect(llamadas.find((l) => l.ruta === "/api/casos/c1/run")?.cuerpo).toEqual({ cmd: "iniciar" });
    expect(llamadas.some((l) => l.metodo === "PUT")).toBe(false);
  });

  it("«Volver a revisar» cierra el diálogo sin iniciar", async () => {
    const llamadas = base(estadoRevision(conRevisar()));
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));
    const dialogo = await dialogoRevisar();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Volver a revisar" }));

    await waitFor(() => expect(dialogo.hasAttribute("open")).toBe(false));
    expect(screen.queryByRole("heading", { name: "Hay documentos para revisar" })).toBeNull();
    expect(llamadas.some((l) => l.ruta.endsWith("/run"))).toBe(false);
    expect(location.hash).toBe("#/segunda/c1/documentos");
  });

  it("solo lista los que siguen sin confirmar", async () => {
    base(estadoRevision(conRevisar([5, 6])), { "PUT /api/casos/c1/revision": () => ok(estadoRevision(conRevisar([6]))) });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR));
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));
    const dialogo = within(await dialogoRevisar());
    expect(dialogo.getByText("006.pdf")).toBeTruthy();
    expect(dialogo.queryByText("005.pdf")).toBeNull();
  });

  it("si todos los documentos para revisar están confirmados no pregunta: guarda y redacta", async () => {
    const llamadas = base(estadoRevision(conRevisar()), {
      "PUT /api/casos/c1/revision": () => ok(estadoRevision(ingesta([...DOCS, paraRevisar(5, { revisar: false, rol_origen: "usuario" })]))),
      "POST /api/casos/c1/run": () => ok({ job_id: "j1" }),
    });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(within(filaDe("005.pdf")).getByRole("checkbox", CONFIRMAR));
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));

    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    expect(screen.queryByRole("heading", { name: "Hay documentos para revisar" })).toBeNull();
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ roles: { d5: "otro" } });
  });

  it("sin documentos para revisar inicia directamente", async () => {
    const llamadas = base(estadoRevision(), { "POST /api/casos/c1/run": () => ok({ job_id: "j1" }) });
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 001.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));

    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    expect(screen.queryByRole("heading", { name: "Hay documentos para revisar" })).toBeNull();
    expect(llamadas.some((l) => l.ruta === "/api/casos/c1/run")).toBe(true);
  });

  it("tras confirmar el diálogo, la clave faltante se pide una sola vez y no se vuelve a preguntar por los documentos", async () => {
    let clave = false;
    const llamadas = base(estadoRevision(conRevisar()), {
      "GET /api/estado-servidor": () => ok({ ...servidor, api_key: clave }),
      "POST /api/api-key": () => {
        clave = true;
        return ok({ api_key: true });
      },
      "POST /api/casos/c1/run": () => ok({ job_id: "j2" }),
    });
    estadoServidor.value = { ...servidor, api_key: false };
    render(<Documentos caso="c1" />);

    await screen.findByLabelText("Rol de 005.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar redacción" }));
    fireEvent.click(within(await dialogoRevisar()).getByRole("button", { name: "Continuar de todos modos" }));
    const campo = await screen.findByLabelText("Clave de la API");
    fireEvent.input(campo, { target: { value: "sk-ant-prueba" } });
    fireEvent.click(within(campo.closest("dialog") as HTMLElement).getByRole("button", { name: "Guardar y continuar" }));

    await waitFor(() => expect(location.hash).toBe("#/segunda/c1/proceso"));
    expect(llamadas.filter((l) => l.ruta === "/api/casos/c1/run")).toHaveLength(1);
  });
});

describe("Datos del auto: firma", () => {
  it("muestra firmante y cargo del firmante, vacíos si no se fijaron, y explica el valor por defecto", async () => {
    base(estadoRevision());
    render(<Documentos caso="c1" />);

    const firmante = (await screen.findByLabelText("Firmante")) as HTMLInputElement;
    const cargo = screen.getByLabelText("Cargo del firmante") as HTMLInputElement;
    expect(firmante.value).toBe("");
    expect(cargo.value).toBe("");
    expect(firmante.disabled).toBe(false);
    expect(screen.getByText(/Si deja vacíos el firmante y su cargo/)).toBeTruthy();
  });

  it("precarga los valores guardados", async () => {
    const res = ingesta(DOCS);
    res.auto = { ...res.auto, firmante: "ANA PÉREZ", cargo_firmante: "JUEZA" };
    base(estadoRevision(res));
    render(<Documentos caso="c1" />);

    expect(((await screen.findByLabelText("Firmante")) as HTMLInputElement).value).toBe("ANA PÉREZ");
    expect((screen.getByLabelText("Cargo del firmante") as HTMLInputElement).value).toBe("JUEZA");
  });

  it("guarda firmante y cargo con la revisión del auto", async () => {
    const llamadas = base(estadoRevision(), { "PUT /api/casos/c1/revision": () => ok(estadoRevision()) });
    render(<Documentos caso="c1" />);

    fireEvent.input(await screen.findByLabelText("Firmante"), { target: { value: "  Ana Pérez  " } });
    fireEvent.input(screen.getByLabelText("Cargo del firmante"), { target: { value: "Jueza" } });
    expect(screen.getByText(/datos del auto editados/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() => expect(llamadas.some((l) => l.metodo === "PUT")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ auto: { firmante: "Ana Pérez", cargo_firmante: "Jueza" } });
  });

  it("vaciar un firmante guardado lo envía como null para volver al valor por defecto", async () => {
    const res = ingesta(DOCS);
    res.auto = { ...res.auto, firmante: "ANA PÉREZ" };
    const llamadas = base(estadoRevision(res), { "PUT /api/casos/c1/revision": () => ok(estadoRevision()) });
    render(<Documentos caso="c1" />);

    fireEvent.input(await screen.findByLabelText("Firmante"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() => expect(llamadas.some((l) => l.metodo === "PUT")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ auto: { firmante: null } });
  });

  it("en solo lectura los campos de firma están deshabilitados", async () => {
    base({ ...estadoRevision(), estado: "esperando_decision", ingesta: ingesta(DOCS), resumen: { alertas: [] } as EstadoCaso["resumen"] });
    render(<Documentos caso="c1" />);

    expect(((await screen.findByLabelText("Firmante")) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Cargo del firmante") as HTMLInputElement).disabled).toBe(true);
  });
});

class FuenteSimulada {
  static instancias: FuenteSimulada[] = [];
  private oyentes = new Map<string, Array<(ev: Event) => void>>();
  cerrada = false;

  constructor(readonly url: string) {
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

const evento = (n: number, texto: string, extra: Partial<Evento> = {}): Evento => ({
  n,
  t: new Date(Date.UTC(2026, 11, 3, 12, 0, n * 4)).toISOString(),
  etapa: "ingesta",
  tipo: "lee",
  texto,
  datos: null,
  ...extra,
});

const fuente = () => FuenteSimulada.instancias[FuenteSimulada.instancias.length - 1]!;
const emitir = (tipo: string, datos?: unknown) => act(() => fuente().emitir(tipo, datos));
const avanzar = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

async function montarProgreso(job: () => Salida = () => ok({ id: "j1", caso: "c1", cmd: "nuevo", estado: "corriendo", error: null })) {
  const alTerminar = vi.fn();
  const llamadas = instalar({ "GET /api/jobs/j1": job });
  render(<Progreso jobId="j1" onFin={alTerminar} />);
  await avanzar(0);
  return { alTerminar, llamadas };
}

describe("Progreso de la lectura", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FuenteSimulada.instancias = [];
    vi.stubGlobal("EventSource", FuenteSimulada);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("muestra la barra superior, la etapa de lectura y la línea de tiempo con los pasos", async () => {
    await montarProgreso();
    expect(fuente().url).toBe("/api/jobs/j1/eventos");

    emitir("open");
    emitir("evento", evento(1, "Se leen 3 archivos de insumos (3 PDF).", { datos: { archivos: 3 } }));
    emitir("evento", evento(2, "01PrimeraInstancia/C01Principal/009_009RespuestaEntidad.pdf: 8 páginas."));
    emitir("evento", evento(3, "Están los documentos obligatorios: escrito_tutela.", { tipo: "verifica" }));

    expect(screen.getByRole("heading", { level: 2, name: "Lectura del expediente" })).toBeTruthy();
    expect(screen.getByText("Se leen 3 archivos de insumos (3 PDF).")).toBeTruthy();
    expect(screen.getByText("01PrimeraInstancia/C01Principal/009_009RespuestaEntidad.pdf: 8 páginas.")).toBeTruthy();
    expect(screen.getByText("Están los documentos obligatorios: escrito_tutela.")).toBeTruthy();
    expect(screen.getAllByText("Lee")).toHaveLength(2);
    expect(screen.getByText("Verifica")).toBeTruthy();
    expect(screen.getByText("00:04")).toBeTruthy();

    const barra = document.querySelector(".tz-top")!;
    expect(barra.textContent).toContain("Tiempo");
    expect(barra.textContent).toContain("Modelo");
    expect(barra.textContent).toMatch(/Pasos\s*3/);
    expect(screen.getByText("Conectado · Lectura del expediente")).toBeTruthy();
    expect(screen.getByText("Esperando el siguiente paso…")).toBeTruthy();
  });

  it("lista las seis etapas: la lectura en curso y las otras cinco pendientes", async () => {
    await montarProgreso();
    emitir("evento", evento(1, "Se leen 2 archivos.", { datos: { archivos: 2 } }));

    const etapas = within(screen.getByRole("list", { name: "Etapas del proceso" })).getAllByRole("button");
    expect(etapas).toHaveLength(6);
    expect(etapas[0]!.textContent).toContain("Lectura del expediente");
    expect(etapas[0]!.textContent).toContain("(en curso)");
    const pendientes = ["Apertura", "Consideraciones", "Verificación de citas", "Caso concreto", "Documentos"];
    pendientes.forEach((titulo, i) => {
      expect(etapas[i + 1]!.textContent).toContain(titulo);
      expect(etapas[i + 1]!.textContent).toContain("(pendiente)");
    });
  });

  it("clasifica en la lectura los eventos reales de la ingesta, incluidos el aviso del sistema y la fase de OCR", async () => {
    await montarProgreso();
    emitir("evento", evento(1, "Inicio de «nuevo» en el caso c1.", { etapa: "sistema", tipo: "sistema" }));
    expect(screen.getByRole("heading", { level: 2, name: "Mensajes del sistema" })).toBeTruthy();

    emitir("evento", evento(2, "Se leen 2 archivos de insumos (2 PDF).", { datos: { archivos: 2 } }));
    emitir("evento", evento(3, "OCR: 1 documento escaneado, 5 páginas por leer.", { datos: { ocr_documentos: 1, ocr_paginas: 5, desde_cache: 0 } }));
    emitir("evento", evento(4, "OCR: 02.pdf, página 1 de 5.", { datos: { doc_id: "1a-002", archivo: "02.pdf", pagina: 1, paginas: 5, ocr: true, n_ocr_hecho: 1, n_ocr_total: 5 } }));
    emitir("evento", evento(5, "02.pdf: 5 páginas, 5 leídas con OCR.", { datos: { doc_id: "1a-002", n_hecho: 1, n_total: 2 } }));
    emitir("evento", evento(6, "Segunda opinión de Jev (modo sombra): 2 consultas.", { tipo: "verifica" }));
    emitir("evento", evento(7, "02.pdf: rol escrito_tutela (origen: contenido).", { datos: { doc_id: "1a-002", rol: "escrito_tutela" } }));

    expect(screen.getByRole("heading", { level: 2, name: "Lectura del expediente" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Lectura del expediente/ }).textContent).toContain("7 pasos");
    expect(screen.getByText("Inicio de «nuevo» en el caso c1.")).toBeTruthy();
    expect(screen.getByText("OCR: 1 documento escaneado, 5 páginas por leer.")).toBeTruthy();
    expect(screen.getByText("OCR: 02.pdf, página 1 de 5.")).toBeTruthy();
    expect(screen.getByText("Segunda opinión de Jev (modo sombra): 2 consultas.")).toBeTruthy();
  });

  it("al terminar no muestra bloques de final ni consulta el estado del caso", async () => {
    const { llamadas } = await montarProgreso();
    emitir("evento", evento(1, "Se leen 1 archivos.", { datos: { archivos: 1 } }));
    emitir("fin", { estado: "terminado", error: null });
    await avanzar(0);

    expect(screen.getByText("Ejecución terminada")).toBeTruthy();
    expect(screen.queryByText("Comprobando el estado del caso…")).toBeNull();
    expect(screen.queryByText("La ejecución terminó.")).toBeNull();
    expect(screen.queryByRole("link", { name: "Ir a documentos" })).toBeNull();
    expect(screen.queryByText(/El borrador está listo|El fallo y los documentos están listos/)).toBeNull();
    expect(llamadas.some((l) => l.ruta.includes("/api/casos/"))).toBe(false);
  });

  it("si el proceso termina con error no muestra «La ejecución se detuvo»: lo decide la pantalla de documentos", async () => {
    const { llamadas } = await montarProgreso();
    emitir("evento", evento(1, "No se pudo leer 02.pdf.", { tipo: "error" }));
    emitir("fin", { estado: "error", error: "El OCR falló." });
    await avanzar(0);

    expect(screen.getByText("Ejecución detenida por un error")).toBeTruthy();
    expect(screen.getByText("No se pudo leer 02.pdf.")).toBeTruthy();
    expect(screen.queryByText("La ejecución se detuvo")).toBeNull();
    expect(screen.queryByRole("button", { name: "Continuar" })).toBeNull();
    expect(llamadas.some((l) => l.ruta.includes("/api/casos/"))).toBe(false);
  });

  it("si se pierde la conexión con los eventos lo dice en la barra, sin aviso ni «Reintentar»", async () => {
    await montarProgreso();
    emitir("evento", evento(1, "Se leen 1 archivos."));
    for (let i = 0; i < 9; i++) {
      emitir("error");
      await avanzar(5000);
    }

    expect(screen.getByText("Sin conexión con el servidor")).toBeTruthy();
    expect(screen.queryByText("Se perdió la conexión con el servidor")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  it("sondea el job cada 1200 ms y avisa una sola vez al terminar", async () => {
    let consultas = 0;
    const { alTerminar } = await montarProgreso(() => {
      consultas += 1;
      return ok({ id: "j1", caso: "c1", cmd: "nuevo", estado: consultas < 3 ? "corriendo" : "terminado", error: null });
    });
    expect(consultas).toBe(1);

    await avanzar(1199);
    expect(consultas).toBe(1);
    await avanzar(1);
    expect(consultas).toBe(2);
    expect(alTerminar).not.toHaveBeenCalled();

    await avanzar(1200);
    expect(consultas).toBe(3);
    expect(alTerminar).toHaveBeenCalledTimes(1);
    expect(alTerminar.mock.calls[0]![0]).toMatchObject({ id: "j1", estado: "terminado" });

    await avanzar(10_000);
    expect(consultas).toBe(3);
  });

  it("avisa con null si el sondeo falla", async () => {
    const { alTerminar } = await montarProgreso(() => fallo(500, "boom"));

    expect(alTerminar).toHaveBeenCalledTimes(1);
    expect(alTerminar).toHaveBeenCalledWith(null);
  });

  it("al desmontar deja de sondear y cierra el flujo de eventos", async () => {
    const { alTerminar, llamadas } = await montarProgreso();
    const antes = llamadas.length;

    cleanup();
    await avanzar(10_000);

    expect(llamadas.length).toBe(antes);
    expect(fuente().cerrada).toBe(true);
    expect(alTerminar).not.toHaveBeenCalled();
  });

  it("sin EventSource muestra el spinner y el reloj, sin barra ni línea de tiempo, y sigue sondeando", async () => {
    vi.stubGlobal("EventSource", undefined);
    let consultas = 0;
    const { alTerminar } = await montarProgreso(() => {
      consultas += 1;
      return ok({ id: "j1", caso: "c1", cmd: "nuevo", estado: consultas < 2 ? "corriendo" : "terminado", error: null });
    });

    expect(FuenteSimulada.instancias).toHaveLength(0);
    expect(screen.getByText("Leyendo el expediente…")).toBeTruthy();
    expect(document.querySelector(".giro")).toBeTruthy();
    expect(screen.getByText(/Lleva 0 s\./)).toBeTruthy();
    expect(document.querySelector(".tz-top")).toBeNull();
    expect(screen.queryByRole("list", { name: "Etapas del proceso" })).toBeNull();

    await avanzar(3000);
    expect(screen.getByText(/Lleva 3 s\./)).toBeTruthy();
    expect(alTerminar).toHaveBeenCalledTimes(1);
  });
});
