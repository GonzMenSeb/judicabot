import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DecisionVistaRespuesta } from "../../api/contrato";
import Decision from "./index";
import type { PayloadDecision } from "./tipos";

const CASO = "caso-1";

const payload: PayloadDecision = {
  reparos: [{ id: "R1", sintesis: "El a quo no valoró la orden médica." }],
  decision_a_quo: "Declaró improcedente la acción de tutela",
  impugnante: "Marta Quintero",
  impugnante_rol: "accionante",
  derechos_invocados: ["salud"],
  pruebas_nuevas_2a: [],
  fecha_hoy: "2026-11-03",
  errores: [],
};

interface Llamada {
  url: string;
  metodo: string;
  cuerpo: any;
  signal: AbortSignal | null;
}

interface Opciones {
  estado?: unknown;
  vista?: (cuerpo: any) => DecisionVistaRespuesta | Response | Promise<Response>;
  run?: () => Response;
  resumen?: () => Response | Promise<Response>;
}

const json = (datos: unknown, estado = 200) =>
  new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });

const numeralesDe = (cuerpo: any): DecisionVistaRespuesta => ({
  numerales: [
    { clave: "resultado", texto: `${cuerpo.resultado ?? "⟦FALTA: resultado⟧"} la sentencia de primera instancia.`, negritas: [cuerpo.resultado ?? ""] },
    { clave: "notificar", texto: "NOTIFICAR esta providencia a las partes.", negritas: ["NOTIFICAR"] },
    { clave: "remitir", texto: "REMITIR el expediente a la Corte.", negritas: ["REMITIR"] },
  ],
  faltantes: [],
  errores: [],
});

function servidor(opciones: Opciones = {}) {
  const llamadas: Llamada[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const metodo = init.method ?? "GET";
      const cuerpo = typeof init.body === "string" ? JSON.parse(init.body) : null;
      llamadas.push({ url, metodo, cuerpo, signal: (init.signal as AbortSignal | undefined) ?? null });
      if (url.endsWith("/estado")) {
        return json(opciones.estado ?? { ok: true, estado: "esperando_decision", payload, salidas: [], resumen: {}, error: null, job_activo: null });
      }
      if (url.endsWith("/config")) return json({ despacho: { juez: "Juez Demo", cierre_fallo: "NOTIFÍQUESE Y CÚMPLASE" }, llm: { proveedor: "fake" } });
      if (url === `/api/casos/${CASO}/resumen`) {
        return opciones.resumen ? opciones.resumen() : json({ id: CASO, nombre: "Quintero c. EPS", radicado: "2026-00412", juzgado_a_quo: "Juzgado 9 Penal", etapa: 2 });
      }
      if (url.endsWith("/decision/vista")) {
        const r = opciones.vista ? await opciones.vista(cuerpo) : numeralesDe(cuerpo);
        return r instanceof Response ? r : json(r);
      }
      if (url.endsWith("/run")) return opciones.run ? opciones.run() : json({ job_id: "j-1" });
      return json({ detail: "no encontrado" }, 404);
    }),
  );
  return llamadas;
}

const vistas = (llamadas: Llamada[]) => llamadas.filter((l) => l.url.endsWith("/decision/vista"));

beforeEach(() => {
  sessionStorage.clear();
  location.hash = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function montar() {
  const r = render(<Decision caso={CASO} />);
  await screen.findByRole("heading", { name: "Qué decide" });
  return r;
}

const estadoBarra = () => document.getElementById("dec-estado")?.textContent ?? "";
const elegir = (nombre: string) => fireEvent.click(screen.getByRole("radio", { name: new RegExp(nombre) }));
const escribir = (etiqueta: RegExp | string, valor: string) => fireEvent.input(screen.getByLabelText(etiqueta), { target: { value: valor } });

describe("Decisión: render con datos", () => {
  it("muestra el contexto, el caso, los reparos y la vista previa vacía", async () => {
    servidor();
    await montar();
    expect(screen.getByRole("heading", { level: 1, name: "Quintero c. EPS" })).toBeTruthy();
    expect(screen.getByText("Declaró improcedente la acción de tutela")).toBeTruthy();
    expect(screen.getByText("El a quo no valoró la orden médica.")).toBeTruthy();
    expect(screen.getByLabelText("Disposición del reparo R1")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Órdenes" })).toBeNull();
    expect(screen.getByText(/Elija qué decide/)).toBeTruthy();
    expect(estadoBarra()).toContain("Para enviar falta: el resultado");
  });

  it("muestra órdenes y derechos solo al amparar y la vista previa marca negritas del servidor", async () => {
    servidor();
    await montar();
    elegir("Revocar");
    expect(await screen.findByText("REVOCAR", { selector: "b" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Órdenes" })).toBeNull();
    elegir("Amparar");
    expect(screen.getByRole("heading", { name: "Órdenes" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Derechos invocados" })).toBeTruthy();
    expect(screen.getByLabelText("Destinatario")).toBeTruthy();
    expect(screen.getByText("NOTIFÍQUESE Y CÚMPLASE")).toBeTruthy();
  });

  it("al cargar un caso que ya no espera decisión explica y enlaza al fallo", async () => {
    servidor({ estado: { ok: true, estado: "terminado", payload: null, salidas: [], resumen: {}, error: null } });
    render(<Decision caso={CASO} />);
    expect(await screen.findByText(/La decisión ya fue enviada/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ver el fallo" }).getAttribute("href")).toBe(`#/segunda/${CASO}/fallo`);
  });
});

describe("Decisión: resumen del caso", () => {
  it("pide solo el resumen de este caso, no la lista completa", async () => {
    const llamadas = servidor();
    await montar();
    await screen.findByRole("heading", { level: 1, name: "Quintero c. EPS" });
    const urls = llamadas.map((l) => l.url);
    expect(urls).toContain(`/api/casos/${CASO}/resumen`);
    expect(urls).not.toContain("/api/casos");
  });

  it("pinta el editor sin esperar el resumen y completa la cabecera cuando llega", async () => {
    let entregar: (r: Response) => void = () => {};
    servidor({ resumen: () => new Promise<Response>((ok) => (entregar = ok)) });
    await montar();
    expect(screen.getByRole("heading", { level: 1, name: CASO })).toBeTruthy();
    expect(screen.queryByText(/Radicado/)).toBeNull();

    entregar(json({ id: CASO, nombre: "Quintero c. EPS", radicado: "2026-00412", juzgado_a_quo: "Juzgado 9 Penal", etapa: 3 }));
    expect(await screen.findByRole("heading", { level: 1, name: "Quintero c. EPS" })).toBeTruthy();
    expect(screen.getByText("Radicado 2026-00412")).toBeTruthy();
  });

  it("sigue mostrando el editor si el resumen falla", async () => {
    servidor({ resumen: () => json({ detail: "boom" }, 500) });
    await montar();
    expect(screen.getByRole("heading", { level: 1, name: CASO })).toBeTruthy();
  });
});

describe("Decisión: errores de la API", () => {
  it("muestra el error de carga y permite reintentar", async () => {
    let falla = true;
    const fetchFalso = vi.fn(async (url: string) => {
      if (url.endsWith("/estado")) return falla ? json({ detail: "Fallo interno." }, 500) : json({ ok: true, estado: "esperando_decision", payload, salidas: [], resumen: {}, error: null, job_activo: null });
      return json({ detail: "no encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchFalso);
    render(<Decision caso={CASO} />);
    expect(await screen.findByText("Fallo interno.")).toBeTruthy();
    falla = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("heading", { name: "Qué decide" })).toBeTruthy();
  });

  it("si no hay conexión muestra un mensaje claro y permite reintentar", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<Decision caso={CASO} />);
    expect(await screen.findByText("No se pudo conectar con el servidor. Revise su conexión e intente de nuevo.")).toBeTruthy();
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeTruthy();
  });

  it("si el caso no existe lo dice, enlaza a la lista y no ofrece reintentar", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Caso no encontrado." }, 404)));
    render(<Decision caso={CASO} />);
    expect(await screen.findByText("No se encontró el caso")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Qué decide" })).toBeNull();
  });

  it("si falla la vista previa avisa y reintenta sin perder el formulario", async () => {
    let falla = true;
    servidor({ vista: (c) => (falla ? json({ detail: "Servidor caído" }, 500) : numeralesDe(c)) });
    await montar();
    escribir("Por qué, en pocas líneas", "Mi eje");
    elegir("Revocar");
    expect(await screen.findByText(/No se pudo actualizar la vista previa/)).toBeTruthy();
    falla = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("REVOCAR", { selector: "b" })).toBeTruthy();
    expect((screen.getByLabelText("Por qué, en pocas líneas") as HTMLTextAreaElement).value).toBe("Mi eje");
  });

  it("muestra el error del servidor al enviar y no navega", async () => {
    servidor({ run: () => json({ detail: "Ya hay una ejecución en curso para este caso." }, 409) });
    await montar();
    elegir("Confirmar");
    escribir("Por qué, en pocas líneas", "Se confirma.");
    await waitFor(() => expect(estadoBarra()).toContain("Listo para enviar."));
    fireEvent.click(screen.getByRole("button", { name: "Enviar decisión y redactar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Enviar decisión" }));
    expect(await screen.findByText("No se pudo enviar la decisión")).toBeTruthy();
    expect(location.hash).toBe("");
  });
});

describe("Decisión: interacción principal", () => {
  it("cancela la petición anterior y espera 250 ms antes de pedir la siguiente", async () => {
    const llamadas = servidor({
      vista: (c) =>
        c.eje === "primero"
          ? new Promise<Response>(() => undefined)
          : numeralesDe(c),
    });
    await montar();
    elegir("Revocar");
    escribir("Por qué, en pocas líneas", "primero");
    await waitFor(() => expect(vistas(llamadas).some((l) => l.cuerpo.eje === "primero")).toBe(true));
    const primera = vistas(llamadas).find((l) => l.cuerpo.eje === "primero");
    escribir("Por qué, en pocas líneas", "segundo");
    expect(vistas(llamadas).some((l) => l.cuerpo.eje === "segundo")).toBe(false);
    await waitFor(() => expect(vistas(llamadas).some((l) => l.cuerpo.eje === "segundo")).toBe(true));
    expect(primera?.signal?.aborted).toBe(true);
  });

  it("valida al enviar, muestra errores por campo y no abre el diálogo", async () => {
    servidor();
    await montar();
    fireEvent.click(screen.getByRole("button", { name: "Enviar decisión y redactar" }));
    expect(await screen.findByText("Revise la decisión antes de enviarla")).toBeTruthy();
    expect(document.getElementById("dec-eje-error")?.textContent).toContain("Falta el eje");
    expect(screen.queryByRole("heading", { name: "¿Enviar la decisión?" })).toBeNull();
  });

  it("completa una decisión, confirma en el diálogo, envía y va al proceso", async () => {
    const llamadas = servidor();
    await montar();
    elegir("Revocar");
    elegir("Amparar");
    escribir("Por qué, en pocas líneas", "El a quo omitió la orden médica.");
    escribir("Destinatario", "la EPS HORIZONTE");
    escribir("Qué debe hacer", "autorice el medicamento");
    await waitFor(() => expect(estadoBarra()).toContain("Listo para enviar."));
    fireEvent.click(screen.getByRole("button", { name: "Enviar decisión y redactar" }));
    const dialogo = await screen.findByRole("heading", { name: "¿Enviar la decisión?" });
    expect(dialogo).toBeTruthy();
    fireEvent.click(within(dialogo.closest("dialog") as HTMLElement).getByRole("button", { name: "Enviar decisión" }));
    await waitFor(() => expect(location.hash).toBe(`#/segunda/${CASO}/proceso`));
    const run = llamadas.find((l) => l.url.endsWith("/run"));
    expect(run?.metodo).toBe("POST");
    expect(run?.cuerpo.cmd).toBe("decidir");
    expect(run?.cuerpo.decision).toMatchObject({
      accion: "decidir",
      resultado: "REVOCAR",
      sustitutiva: "AMPARAR",
      eje: "El a quo omitió la orden médica.",
      decidido_por: "Juez Demo",
      por_reparo: [{ reparo_id: "R1", disposicion: "ACOGE", nota: "" }],
      derechos: [{ derecho: "salud", disposicion: "AMPARA" }],
      ordenes: [{ destinatario: "la EPS HORIZONTE", conducta: "autorice el medicamento", plazo: { n: 48, unidad: "horas_habiles" } }],
    });
  });

  it("reordena los numerales con el teclado y lo envía como orden_numerales", async () => {
    const llamadas = servidor();
    await montar();
    elegir("Confirmar");
    const subir = await screen.findByRole("button", { name: "Subir el numeral SEGUNDO" });
    fireEvent.click(subir);
    await waitFor(() => {
      const ultima = vistas(llamadas).at(-1);
      expect(ultima?.cuerpo.orden_numerales).toEqual(["notificar", "resultado", "remitir"]);
    });
  });

  it("conserva lo escrito al salir y volver (sessionStorage)", async () => {
    servidor();
    const primera = await montar();
    escribir("Por qué, en pocas líneas", "Texto que no debe perderse");
    elegir("Modificar");
    primera.unmount();
    await montar();
    expect((screen.getByLabelText("Por qué, en pocas líneas") as HTMLTextAreaElement).value).toBe("Texto que no debe perderse");
    expect((screen.getByRole("radio", { name: "Modificar" }) as HTMLInputElement).checked).toBe(true);
  });
});
