import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PreferenciasIa } from "../../api/contrato";
import { toasts } from "../../estado";
import InteligenciaArtificial from "./index";

const base = (): PreferenciasIa => ({
  proveedor: "anthropic",
  modelo: "claude-sonnet-5-5",
  modelos: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
  gemini: { modelo: "gemini-4-argon", razonamiento: "high" },
  modelos_gemini: ["gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen"],
  razonamientos_gemini: {
    "gemini-4-argon": ["low", "medium", "high"],
    "gemini-4-carbon": ["low", "medium", "high"],
    "gemini-4-hydrogen": ["low", "medium", "high", "xhigh"],
  },
  api_key: true,
  gemini_key: false,
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

const estadoServidor: Manejador = () => ({
  cuerpo: { proveedor: "anthropic", api_key: true, gemini_key: false, jev_key: false, modelo: "claude-sonnet-5-5", modelos: [], modelos_gemini: [] },
});

async function montar(extra: Record<string, Manejador> = {}, inicial: PreferenciasIa = base()) {
  const llamadas = simular({ "GET /api/ia": () => ({ cuerpo: inicial }), "GET /api/estado-servidor": estadoServidor, ...extra });
  render(<InteligenciaArtificial />);
  await screen.findByRole("heading", { name: "Proveedor" });
  return llamadas;
}

const guardar = () => screen.getByRole("button", { name: "Guardar cambios" });
const seccion = (nombre: string) => screen.getByRole("region", { name: nombre });
const textos = (radios: HTMLElement[]) => radios.map((r) => r.closest("label")?.querySelector("b")?.textContent);

beforeEach(() => {
  toasts.value = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Inteligencia artificial", () => {
  it("muestra el modelo, las claves y Jev apagado con los datos del servidor", async () => {
    await montar();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Migas de pan" })).toBeNull();
    const modelos = within(seccion("Anthropic")).getAllByRole("radio");
    expect(textos(modelos)).toEqual(["Sonnet 5.5", "Opus 5.5", "Haiku 5.5"]);
    expect((screen.getByRole("radio", { name: /Sonnet 5\.5/ }) as HTMLInputElement).checked).toBe(true);
    expect(within(seccion("Anthropic")).getByText("Hay una clave lista.")).toBeTruthy();
    expect(within(seccion("Anthropic")).getByRole("button", { name: "Reemplazar clave" })).toBeTruthy();
    expect((within(seccion("Anthropic")).getByLabelText("Esfuerzo de razonamiento") as HTMLSelectElement).value).toBe("high");
    expect((screen.getByRole("radio", { name: /Apagado/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByText(/artículo 8\.6/)).toBeNull();
    expect(screen.queryByLabelText("Confianza mínima de Jev")).toBeNull();
    expect(screen.queryByText(/no está permitido en este servidor/)).toBeNull();
    expect(screen.queryByText(/No hay modelos permitidos/)).toBeNull();
  });

  it("al encender Jev avisa que la información sale del despacho y pide clave y umbral", async () => {
    await montar();
    fireEvent.click(screen.getByRole("radio", { name: /Sombra/ }));
    expect(screen.getByText(/artículo 8\.6 del Acuerdo PCSJA24-12243/)).toBeTruthy();
    expect(screen.getByText("Esta información sale del despacho")).toBeTruthy();
    expect(screen.getByText(/No hay clave de Jev/)).toBeTruthy();
    expect(within(seccion("Jev, segunda opinión")).getByRole("button", { name: "Agregar clave" })).toBeTruthy();
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
      effort: "high",
      jev: { modo: "relleno", umbral: 0.8 },
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
    await screen.findByRole("heading", { name: "Proveedor" });
    expect(intentos).toBe(2);
  });

  it("deja el editor de instrucciones desactivado con la nota Próximamente", async () => {
    await montar();
    const boton = screen.getByRole("button", { name: "Editar instrucciones" }) as HTMLButtonElement;
    expect(boton.disabled).toBe(true);
    expect(boton.getAttribute("aria-describedby")).toBe(screen.getByText("Próximamente").id);
  });
});

describe("Modelos permitidos por el servidor", () => {
  const radiosModelo = () => screen.queryAllByRole("radio", { name: /5\.5/ }) as HTMLInputElement[];
  const restringido = (): PreferenciasIa => ({ ...base(), modelo: "claude-opus-5-5", modelos: ["claude-sonnet-5-5"] });

  it("avisa que el modelo guardado no está permitido y no lo ofrece", async () => {
    await montar({}, restringido());
    const aviso = screen.getByText("El modelo guardado no está permitido en este servidor").closest(".aviso") as HTMLElement;
    expect(aviso.classList.contains("alerta")).toBe(true);
    expect(aviso.textContent).toContain("Opus 5.5");
    expect(aviso.textContent).toMatch(/la redacción fallará/);
    expect(radiosModelo().map((r) => r.closest("label")?.querySelector("b")?.textContent)).toEqual(["Sonnet 5.5"]);
    expect(radiosModelo().some((r) => r.checked)).toBe(false);
    expect(screen.queryByRole("radio", { name: /Opus/ })).toBeNull();
  });

  it("no guarda mientras no se elija uno permitido y retira el aviso al guardarlo", async () => {
    const llamadas = await montar(
      { "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...restringido(), ...(cuerpo as object), api_key: true, jev_key: false, modelos: ["claude-sonnet-5-5"] } }) },
      restringido(),
    );
    fireEvent.click(screen.getByRole("radio", { name: /Sombra/ }));
    fireEvent.click(guardar());
    expect(await screen.findByText("Elija uno de los modelos disponibles.")).toBeTruthy();
    expect(llamadas.some((l) => l.clave === "PUT /api/ia")).toBe(false);
    expect(screen.getByText("El modelo guardado no está permitido en este servidor")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /Sonnet 5\.5/ }));
    expect(screen.queryByText("Elija uno de los modelos disponibles.")).toBeNull();
    fireEvent.click(guardar());
    await screen.findByText("Cambios guardados.");
    expect(llamadas.find((l) => l.clave === "PUT /api/ia")?.cuerpo).toMatchObject({ modelo: "claude-sonnet-5-5" });
    expect(screen.queryByText("El modelo guardado no está permitido en este servidor")).toBeNull();
    expect(radiosModelo().filter((r) => r.checked).length).toBe(1);
  });

  it("no avisa del modelo guardado cuando sí está en la lista restringida", async () => {
    await montar({}, { ...base(), modelos: ["claude-sonnet-5-5", "claude-haiku-5-5"] });
    expect(screen.queryByText(/no está permitido en este servidor/)).toBeNull();
    expect(radiosModelo().map((r) => r.closest("label")?.querySelector("b")?.textContent)).toEqual(["Sonnet 5.5", "Haiku 5.5"]);
    expect((screen.getByRole("radio", { name: /Sonnet 5\.5/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("explica que no hay ningún modelo permitido cuando la lista llega vacía", async () => {
    await montar({}, { ...base(), modelos: [] });
    const aviso = screen.getByText("No hay modelos permitidos en este servidor").closest(".aviso") as HTMLElement;
    expect(aviso.textContent).toContain("TUTELA2_MODELOS_PERMITIDOS");
    expect(screen.queryByText("El modelo guardado no está permitido en este servidor")).toBeNull();
    expect(radiosModelo().length).toBe(0);
    expect(screen.getByRole("radio", { name: /Apagado/ })).toBeTruthy();
  });
});

describe("Claves", () => {
  it("guarda la clave de Anthropic sin conservarla en el navegador", async () => {
    const llamadas = await montar({ "POST /api/api-key": () => ({ cuerpo: { api_key: true } }) }, { ...base(), api_key: false });
    expect(screen.getByText("No hay clave. Agréguela para elegir el modelo de Anthropic.")).toBeTruthy();
    fireEvent.click(within(seccion("Anthropic")).getByRole("button", { name: "Agregar clave" }));

    const dialogo = screen.getByRole("dialog", { hidden: true });
    const campo = within(dialogo).getByLabelText("Clave de la API de Anthropic") as HTMLInputElement;
    expect(campo.type).toBe("password");
    fireEvent.input(campo, { target: { value: "  sk-ant-secreta  " } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar clave" }));

    await within(seccion("Anthropic")).findByText("Hay una clave lista.");
    expect(within(seccion("Anthropic")).getAllByRole("radio")).toHaveLength(3);
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
    fireEvent.click(within(seccion("Jev, segunda opinión")).getByRole("button", { name: "Agregar clave" }));
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

  it("no incluye la extensión de consultas públicas ni su descarga", async () => {
    const llamadas = await montar();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Proveedor", "Anthropic", "Gemini (Google)", "Jev, segunda opinión"]);
    expect(screen.queryByText("Extensión de consultas públicas")).toBeNull();
    expect(screen.queryByRole("link", { name: "Descargar extensión (.zip)" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Pasos para instalar la extensión" })).toBeNull();
    expect(screen.queryByText(/citas/)).toBeNull();
    expect(llamadas.some((l) => l.clave.includes("/api/extension"))).toBe(false);
  });
});

describe("Proveedores", () => {
  const radiosGemini = () => within(seccion("Gemini (Google)")).queryAllByRole("radio") as HTMLInputElement[];
  const conGemini = (extra: Partial<PreferenciasIa> = {}): PreferenciasIa => ({ ...base(), gemini_key: true, ...extra });
  const nivel = () => within(seccion("Gemini (Google)")).getByLabelText("Nivel de razonamiento") as HTMLSelectElement;
  const opcionesNivel = () => Array.from(nivel().options).map((o) => o.value);

  it("muestra los proveedores con el estado de su clave y Anthropic activo", async () => {
    await montar();
    const tarjetas = within(seccion("Proveedor")).getAllByRole("radio") as HTMLInputElement[];
    expect(textos(tarjetas)).toEqual(["Anthropic", "Gemini (Google)"]);
    expect(tarjetas.map((t) => t.checked)).toEqual([true, false]);
    expect(seccion("Proveedor").textContent).toContain("Modelos Claude. Clave lista.");
    expect(seccion("Proveedor").textContent).toContain("Modelos Gemini. Sin clave.");
    expect(screen.queryByText(/^Falta la clave de/)).toBeNull();
  });

  it("sin la clave de Gemini oculta sus opciones, avisa al elegirlo y guarda solo el proveedor", async () => {
    const llamadas = await montar({ "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...base(), ...(cuerpo as object) } }) });
    expect(radiosGemini()).toHaveLength(0);
    expect(within(seccion("Gemini (Google)")).queryByLabelText("Nivel de razonamiento")).toBeNull();
    expect(within(seccion("Gemini (Google)")).getByText("No hay clave. Agréguela para elegir el modelo de Gemini.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /^Gemini \(Google\)/ }));
    const aviso = screen.getByText("Falta la clave de Gemini (Google)").closest(".aviso") as HTMLElement;
    expect(aviso.classList.contains("alerta")).toBe(true);
    expect(aviso.textContent).toContain("La redacción no funcionará");
    fireEvent.click(guardar());
    await screen.findByText("Cambios guardados.");
    const put = llamadas.find((l) => l.clave === "PUT /api/ia")?.cuerpo as Record<string, unknown>;
    expect(put.proveedor).toBe("gemini");
    expect(put).not.toHaveProperty("gemini");
    expect(put.modelo).toBe("claude-sonnet-5-5");
  });

  it("sin la clave de Anthropic oculta su modelo y su esfuerzo y no los envía", async () => {
    const llamadas = await montar({ "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...base(), api_key: false, ...(cuerpo as object) } }) }, { ...base(), api_key: false });
    expect(screen.queryAllByRole("radio", { name: /5\.5/ })).toHaveLength(0);
    expect(screen.queryByLabelText("Esfuerzo de razonamiento")).toBeNull();
    expect(screen.getByText("Falta la clave de Anthropic")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Sombra/ }));
    fireEvent.click(guardar());
    await screen.findByText("Cambios guardados.");
    const put = llamadas.find((l) => l.clave === "PUT /api/ia")?.cuerpo as Record<string, unknown>;
    expect(put).not.toHaveProperty("modelo");
    expect(put).not.toHaveProperty("effort");
    expect(put.jev).toEqual({ modo: "sombra", umbral: 0.9 });
  });

  it("no envía el proveedor si el usuario no lo cambió, para no pisar el del servidor", async () => {
    const llamadas = await montar({ "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...conGemini({ proveedor: "gemini" }), ...(cuerpo as object) } }) }, conGemini({ proveedor: "gemini" }));
    expect((screen.getByRole("radio", { name: /^Gemini \(Google\)/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.input(screen.getByLabelText("Reintentos por llamada"), { target: { value: "3" } });
    fireEvent.click(guardar());
    await screen.findByText("Cambios guardados.");
    const put = llamadas.find((l) => l.clave === "PUT /api/ia")?.cuerpo as Record<string, unknown>;
    expect(put).not.toHaveProperty("proveedor");
    expect(put.max_retries).toBe(3);
  });

  it("avisa que con una clave gratuita Google puede usar lo que se envía", async () => {
    await montar();
    const aviso = within(seccion("Gemini (Google)")).getByText("Con una clave gratuita, Google puede usar lo que se envía").closest(".aviso") as HTMLElement;
    expect(aviso.classList.contains("alerta")).toBe(true);
    expect(aviso.textContent).toMatch(/nivel gratuito/);
    expect(aviso.textContent).toMatch(/personas pueden revisarlo/);
    expect(aviso.textContent).toMatch(/facturación activa/);
    const enlace = within(aviso).getByRole("link", { name: "Condiciones adicionales de la API de Gemini" });
    expect(enlace.getAttribute("href")).toBe("https://aistudio.google.com/docs/terms");
  });

  it("al agregar la clave de Gemini muestra sus modelos y niveles", async () => {
    const llamadas = await montar({ "POST /api/gemini-key": () => ({ cuerpo: { gemini_key: true } }) });
    fireEvent.click(within(seccion("Gemini (Google)")).getByRole("button", { name: "Agregar clave" }));
    const dialogo = screen.getByRole("dialog", { hidden: true });
    expect(within(dialogo).getByRole("heading", { name: "Agregar la clave de Gemini" })).toBeTruthy();
    const campo = within(dialogo).getByLabelText("Clave de la API de Gemini") as HTMLInputElement;
    expect(campo.type).toBe("password");
    expect(campo.placeholder).toBe("AIza…");
    fireEvent.input(campo, { target: { value: " AIza-secreta " } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar clave" }));

    await within(seccion("Gemini (Google)")).findByText("Hay una clave lista.");
    expect(llamadas.find((l) => l.clave === "POST /api/gemini-key")?.cuerpo).toEqual({ key: "AIza-secreta" });
    expect(document.body.innerHTML).not.toContain("AIza-secreta");
    expect(toasts.value.map((t) => t.texto)).toContain("Clave de Gemini guardada.");
    expect(textos(radiosGemini())).toEqual(["Gemini 4 Argon", "Gemini 4 Carbon", "Gemini 4 Hydrogen"]);
    expect(radiosGemini()[0]?.checked).toBe(true);
    expect(opcionesNivel()).toEqual(["low", "medium", "high"]);
    expect(seccion("Proveedor").textContent).toContain("Modelos Gemini. Clave lista.");
  });

  it("lista solo los niveles que admite el modelo y ajusta el nivel al cambiarlo", async () => {
    const llamadas = await montar({ "PUT /api/ia": (cuerpo) => ({ cuerpo: { ...conGemini(), ...(cuerpo as object) } }) }, conGemini());
    fireEvent.click(screen.getByRole("radio", { name: /^Gemini 4 Hydrogen/ }));
    expect(opcionesNivel()).toEqual(["low", "medium", "high", "xhigh"]);
    fireEvent.change(nivel(), { target: { value: "xhigh" } });
    expect(nivel().value).toBe("xhigh");
    fireEvent.click(screen.getByRole("radio", { name: /^Gemini 4 Carbon/ }));
    expect(opcionesNivel()).toEqual(["low", "medium", "high"]);
    expect(nivel().value).toBe("high");
    fireEvent.change(nivel(), { target: { value: "medium" } });
    fireEvent.click(screen.getByRole("radio", { name: /^Gemini \(Google\)/ }));
    fireEvent.click(guardar());
    await screen.findByText("Cambios guardados.");
    expect(llamadas.find((l) => l.clave === "PUT /api/ia")?.cuerpo).toMatchObject({
      proveedor: "gemini",
      modelo: "claude-sonnet-5-5",
      gemini: { modelo: "gemini-4-carbon", razonamiento: "medium" },
    });
  });

  it("muestra el error del servidor en el nivel de razonamiento", async () => {
    await montar(
      { "PUT /api/ia": () => ({ estado: 422, cuerpo: { detail: { errores: [{ campo: "gemini.razonamiento", mensaje: "con gemini-4-carbon debe ser uno de: low, medium o high." }] } } }) },
      conGemini(),
    );
    fireEvent.click(screen.getByRole("radio", { name: /^Gemini 4 Carbon/ }));
    fireEvent.click(guardar());
    expect(await screen.findByText("Con gemini-4-carbon debe ser uno de: low, medium o high.")).toBeTruthy();
    expect(nivel().getAttribute("aria-invalid")).toBe("true");
  });

  it("avisa cuando el servidor no permite ningún modelo de Gemini o el guardado", async () => {
    await montar({}, conGemini({ modelos_gemini: [] }));
    expect(screen.getByText("No hay modelos de Gemini permitidos en este servidor")).toBeTruthy();
    expect(radiosGemini()).toHaveLength(0);
    cleanup();
    await montar({}, conGemini({ modelos_gemini: ["gemini-4-hydrogen"] }));
    const aviso = screen.getByText("El modelo de Gemini guardado no está permitido en este servidor").closest(".aviso") as HTMLElement;
    expect(aviso.textContent).toContain("Gemini 4 Argon");
    expect(textos(radiosGemini())).toEqual(["Gemini 4 Hydrogen"]);
  });

  it("el esfuerzo de Anthropic ya no está en las opciones avanzadas", async () => {
    await montar();
    const detalles = document.querySelector("details") as HTMLDetailsElement;
    expect(within(detalles).queryByLabelText("Esfuerzo de razonamiento")).toBeNull();
    expect(within(detalles).getByLabelText("Máximo de tokens de salida")).toBeTruthy();
    expect(within(detalles).getByLabelText("Reintentos por llamada")).toBeTruthy();
  });
});
