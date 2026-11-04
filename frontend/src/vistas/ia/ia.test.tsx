import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PreferenciasIa } from "../../api/contrato";
import { toasts } from "../../estado";
import InteligenciaArtificial from "./index";

const base = (): PreferenciasIa => ({
  modelo: "claude-sonnet-5-5",
  modelos: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
  api_key: true,
  jev_key: false,
  jev: { modo: "apagado", umbral: 0.9 },
  effort: "high",
  max_tokens: 64000,
  max_retries: 1,
});

interface Respuesta {
  estado?: number;
  cuerpo: unknown;
}
type Manejador = (cuerpo: unknown) => Respuesta;

function simular(rutas: Record<string, Manejador>) {
  const llamadas: { clave: string; cuerpo: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (ruta: string, init?: RequestInit) => {
      const clave = `${init?.method ?? "GET"} ${ruta}`;
      const cuerpo = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      llamadas.push({ clave, cuerpo });
      const manejador = rutas[clave];
      if (!manejador) throw new Error(`sin simulación para ${clave}`);
      const r = manejador(cuerpo);
      return new Response(JSON.stringify(r.cuerpo), { status: r.estado ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return llamadas;
}

const estadoServidor: Manejador = () => ({ cuerpo: { api_key: true, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [] } });

async function montar(extra: Record<string, Manejador> = {}, inicial: PreferenciasIa = base()) {
  const llamadas = simular({ "GET /api/ia": () => ({ cuerpo: inicial }), "GET /api/estado-servidor": estadoServidor, ...extra });
  render(<InteligenciaArtificial />);
  await screen.findByRole("heading", { name: "Modelo" });
  return llamadas;
}

const guardar = () => screen.getByRole("button", { name: "Guardar cambios" });

beforeEach(() => {
  toasts.value = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Inteligencia artificial", () => {
  it("muestra el modelo, las claves y Jev apagado con los datos del servidor", async () => {
    await montar();
    expect(screen.getByRole("heading", { level: 1, name: "Inteligencia artificial" })).toBeTruthy();
    const modelos = screen.getAllByRole("radio", { name: /5\.5/ });
    expect(modelos.map((m) => m.closest("label")?.querySelector("b")?.textContent)).toEqual(["Sonnet 5.5", "Opus 5.5", "Haiku 5.5"]);
    expect((screen.getByRole("radio", { name: /Sonnet 5\.5/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Hay una clave lista.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reemplazar clave" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: /Apagado/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByText(/artículo 8\.6/)).toBeNull();
    expect(screen.queryByLabelText("Confianza mínima de Jev")).toBeNull();
  });

  it("al encender Jev avisa que la información sale del despacho y pide clave y umbral", async () => {
    await montar();
    fireEvent.click(screen.getByRole("radio", { name: /Sombra/ }));
    expect(screen.getByText(/artículo 8\.6 del Acuerdo PCSJA24-12243/)).toBeTruthy();
    expect(screen.getByText("Esta información sale del despacho")).toBeTruthy();
    expect(screen.getByText(/No hay clave de Jev/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Agregar clave" })).toBeTruthy();
    const umbral = screen.getByLabelText("Confianza mínima de Jev") as HTMLInputElement;
    expect(umbral.value).toBe("90");
    fireEvent.input(umbral, { target: { value: "75" } });
    expect(screen.getByText("Hay cambios sin guardar.")).toBeTruthy();
    expect(umbral.getAttribute("aria-valuetext")).toMatch(/75/);
  });

  it("guarda los cambios, confirma y refresca el estado del servidor", async () => {
    const llamadas = await montar({
      "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...base(), ...(cuerpo as object), api_key: true, jev_key: false, modelos: base().modelos } }),
    });
    fireEvent.click(screen.getByRole("radio", { name: /Opus 5\.5/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Relleno/ }));
    fireEvent.input(screen.getByLabelText("Confianza mínima de Jev"), { target: { value: "80" } });
    fireEvent.click(guardar());

    await screen.findByText("Cambios guardados.");
    const put = llamadas.find((l) => l.clave === "PUT /api/ia");
    expect(put?.cuerpo).toEqual({
      modelo: "claude-opus-5-5",
      jev: { modo: "relleno", umbral: 0.8 },
      effort: "high",
      max_tokens: 64000,
      max_retries: 1,
    });
    expect(toasts.value.map((t) => t.texto)).toContain("Preferencias guardadas.");
    await waitFor(() => expect(llamadas.some((l) => l.clave === "GET /api/estado-servidor")).toBe(true));
    expect(screen.queryByText("Hay cambios sin guardar.")).toBeNull();
  });

  it("no envía nada si no hay cambios", async () => {
    const llamadas = await montar();
    fireEvent.click(guardar());
    await Promise.resolve();
    expect(llamadas.some((l) => l.clave === "PUT /api/ia")).toBe(false);
  });

  it("valida las opciones avanzadas, las despliega y no llama al servidor", async () => {
    const llamadas = await montar();
    const detalles = document.querySelector("details") as HTMLDetailsElement;
    expect(detalles.open).toBe(false);
    fireEvent.input(screen.getByLabelText("Máximo de tokens de salida"), { target: { value: "0" } });
    fireEvent.input(screen.getByLabelText("Reintentos por llamada"), { target: { value: "9" } });
    fireEvent.click(guardar());

    expect(await screen.findByText("Escriba un número entero entre 1 y 64.000.")).toBeTruthy();
    expect(screen.getByText("Escriba un número entero entre 0 y 5.")).toBeTruthy();
    expect(screen.getByLabelText("Máximo de tokens de salida").getAttribute("aria-invalid")).toBe("true");
    expect(detalles.open).toBe(true);
    expect(llamadas.some((l) => l.clave === "PUT /api/ia")).toBe(false);

    fireEvent.input(screen.getByLabelText("Máximo de tokens de salida"), { target: { value: "32000" } });
    expect(screen.queryByText("Escriba un número entero entre 1 y 64.000.")).toBeNull();
  });

  it("muestra los errores de campo que devuelve el servidor", async () => {
    await montar({
      "PUT /api/ia": () => ({
        estado: 422,
        cuerpo: { detail: { errores: [{ campo: "max_tokens", mensaje: "debe ser menor o igual a 64000." }, { campo: "otro", mensaje: "no admitido." }] } },
      }),
    });
    fireEvent.input(screen.getByLabelText("Máximo de tokens de salida"), { target: { value: "5000" } });
    fireEvent.click(guardar());

    expect(await screen.findByText("Debe ser menor o igual a 64000.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("otro: No admitido.");
    expect(screen.getByLabelText("Máximo de tokens de salida").getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByText("Cambios guardados.")).toBeNull();
  });

  it("muestra un error general cuando el servidor falla", async () => {
    await montar({ "PUT /api/ia": () => ({ estado: 500, cuerpo: { detail: null } }) });
    fireEvent.click(screen.getByRole("radio", { name: /Haiku/ }));
    fireEvent.click(guardar());
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("El servidor no pudo completar la operación");
    expect(screen.getByText("Hay cambios sin guardar.")).toBeTruthy();
  });

  it("ofrece reintentar cuando no se pueden cargar las preferencias", async () => {
    let intentos = 0;
    simular({
      "GET /api/ia": () => (++intentos === 1 ? { estado: 500, cuerpo: { detail: "Fallo del servidor." } } : { cuerpo: base() }),
    });
    render(<InteligenciaArtificial />);
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("No se pudieron cargar las preferencias");
    expect(alerta.textContent).toContain("Fallo del servidor.");
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    await screen.findByRole("heading", { name: "Modelo" });
    expect(intentos).toBe(2);
  });

  it("deja el editor de instrucciones desactivado con la nota Próximamente", async () => {
    await montar();
    const boton = screen.getByRole("button", { name: "Editar instrucciones" }) as HTMLButtonElement;
    expect(boton.disabled).toBe(true);
    expect(boton.getAttribute("aria-describedby")).toBe(screen.getByText("Próximamente").id);
  });
});

describe("Claves", () => {
  it("guarda la clave de Anthropic sin conservarla en el navegador", async () => {
    const llamadas = await montar({ "POST /api/api-key": () => ({ cuerpo: { api_key: true } }) }, { ...base(), api_key: false });
    expect(screen.getByText("No hay clave. Sin ella no se puede redactar.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Agregar clave" }));

    const dialogo = screen.getByRole("dialog", { hidden: true });
    const campo = within(dialogo).getByLabelText("Clave de la API de Anthropic") as HTMLInputElement;
    expect(campo.type).toBe("password");
    fireEvent.input(campo, { target: { value: "  sk-ant-secreta  " } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar clave" }));

    await screen.findByText("Hay una clave lista.");
    expect(llamadas.find((l) => l.clave === "POST /api/api-key")?.cuerpo).toEqual({ key: "sk-ant-secreta" });
    expect(document.querySelector("dialog input")).toBeNull();
    expect(document.body.innerHTML).not.toContain("sk-ant-secreta");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(toasts.value.map((t) => t.texto)).toContain("Clave de Anthropic guardada.");
  });

  it("muestra el mensaje del servidor cuando rechaza la clave de Jev y no marca la clave como lista", async () => {
    const mensaje = "La clave de Jev solo admite caracteres ASCII visibles, sin espacios ni saltos de línea.";
    await montar({ "POST /api/jev-key": () => ({ estado: 422, cuerpo: { detail: mensaje } }) });
    fireEvent.click(screen.getByRole("radio", { name: /Sombra/ }));
    fireEvent.click(screen.getByRole("button", { name: "Agregar clave" }));
    const dialogo = screen.getByRole("dialog", { hidden: true });
    fireEvent.input(within(dialogo).getByLabelText("Clave de Jev"), { target: { value: "con espacio" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar clave" }));

    const alerta = await within(dialogo).findByRole("alert");
    expect(alerta.textContent).toBe(mensaje);
    expect(screen.getByText(/No hay clave de Jev/)).toBeTruthy();
  });

  it("no envía una clave vacía", async () => {
    const llamadas = await montar();
    fireEvent.click(screen.getByRole("button", { name: "Reemplazar clave" }));
    const dialogo = screen.getByRole("dialog", { hidden: true });
    expect(within(dialogo).getByRole("heading", { name: "Reemplazar la clave de Anthropic" })).toBeTruthy();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar clave" }));
    expect(await within(dialogo).findByText("Escriba la clave de la API de Anthropic.")).toBeTruthy();
    expect(llamadas.some((l) => l.clave === "POST /api/api-key")).toBe(false);
  });

  it("Cancelar descarta lo escrito", async () => {
    await montar();
    fireEvent.click(screen.getByRole("button", { name: "Reemplazar clave" }));
    const dialogo = screen.getByRole("dialog", { hidden: true });
    fireEvent.input(within(dialogo).getByLabelText("Clave de la API de Anthropic"), { target: { value: "sk-ant-x" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(document.querySelector("dialog input")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Reemplazar clave" }));
    expect((within(screen.getByRole("dialog", { hidden: true })).getByLabelText("Clave de la API de Anthropic") as HTMLInputElement).value).toBe("");
  });
});
