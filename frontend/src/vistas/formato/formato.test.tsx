import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FormatoCuerpo, FormatoRespuesta } from "../../api/contrato";
import { toasts } from "../../estado";
import { coincidir, ruta } from "../../rutas";
import Formato from "./index";
import { CAMPOS_MOCK, DOCUMENTOS_MOCK, VALORES_MOCK } from "./mock";

interface Llamada {
  metodo: string;
  ruta: string;
  cuerpo: FormatoCuerpo | undefined;
}

const respuestaBase = (): FormatoRespuesta => ({
  campos: CAMPOS_MOCK,
  valores: structuredClone(VALORES_MOCK),
  plantilla_gen: "B",
  documentos: DOCUMENTOS_MOCK,
});

const json = (cuerpo: unknown, estado = 200) =>
  new Response(JSON.stringify(cuerpo), { status: estado, headers: { "Content-Type": "application/json" } });

let llamadas: Llamada[] = [];

function simular(manejador: (llamada: Llamada) => Response | Promise<Response>) {
  llamadas = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const llamada: Llamada = {
        metodo: init?.method ?? "GET",
        ruta: url,
        cuerpo: typeof init?.body === "string" ? (JSON.parse(init.body) as FormatoCuerpo) : undefined,
      };
      llamadas.push(llamada);
      return manejador(llamada);
    }),
  );
}

const servidorNormal = () =>
  simular((l) => {
    if (l.metodo === "PUT" && l.cuerpo) return json({ ...respuestaBase(), valores: l.cuerpo.valores, plantilla_gen: l.cuerpo.plantilla_gen });
    return json(respuestaBase());
  });

async function montar() {
  const vista = render(<Formato />);
  await screen.findByRole("heading", { name: "Formato de los documentos" });
  return vista;
}

const escribir = (etiqueta: string | RegExp, valor: string) => fireEvent.input(screen.getByLabelText(etiqueta), { target: { value: valor } });
const barra = () => screen.queryByRole("region", { name: "Cambios sin guardar" });
const marco = () => screen.getByRole("region", { name: /^Vista previa:/ });
const marcados = (clave: string) => Array.from(marco().querySelectorAll<HTMLElement>("[data-c]")).filter((el) => el.dataset.c === clave);

beforeEach(() => {
  toasts.value = [];
  history.replaceState(null, "", "/");
  ruta.value = coincidir("");
  servidorNormal();
});

afterEach(() => {
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

describe("Formato de documentos", () => {
  it("genera el formulario desde el catálogo, con los tres tipos de campo", async () => {
    await montar();
    for (const grupo of ["Despacho", "Firmas", "Contacto", "Cierres y pies de página"]) {
      expect(screen.getByRole("heading", { level: 2, name: grupo })).toBeTruthy();
    }
    expect(screen.getByLabelText("Nombre del juez").tagName).toBe("INPUT");
    expect(screen.getByLabelText("Nombre del despacho (encabezado del fallo)").tagName).toBe("TEXTAREA");
    const lista = screen.getByRole("group", { name: "Líneas del juzgado en la firma de los correos" });
    expect(within(lista).getAllByRole("textbox")).toHaveLength(2);
    expect((screen.getByRole("radio", { name: /Generación B/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/Los cambios aplican solo a casos nuevos/)).toBeTruthy();
    expect(barra()).toBeNull();
    const pestanas = within(screen.getByRole("group", { name: "Documento de la vista previa" })).getAllByRole("button");
    expect(pestanas.map((b) => b.textContent)).toEqual(["Fallo", "Auto", "Oficio", "Correos", "Formato de calidad"]);
    expect(pestanas[0]?.getAttribute("aria-pressed")).toBe("true");
  });

  it("arma la vista previa con los valores en edición y muestra la barra de cambios", async () => {
    await montar();
    escribir("Nombre del juez", "Ana Pérez");
    expect(marcados("juez")[0]?.textContent).toBe("ANA PÉREZ");
    const b = barra();
    expect(b).not.toBeNull();
    expect(within(b as HTMLElement).getByText(/Se aplican a los casos nuevos/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(barra()).toBeNull();
    expect((screen.getByLabelText("Nombre del juez") as HTMLInputElement).value).toBe(VALORES_MOCK.juez);
    expect(marcados("juez")[0]?.textContent).toBe(VALORES_MOCK.juez);
  });

  it("resalta el campo enfocado y cambia al documento donde aparece", async () => {
    await montar();
    fireEvent.focus(screen.getByLabelText("Nombre del juez"));
    expect(marcados("juez")[0]?.classList.contains("foco")).toBe(true);

    fireEvent.focus(screen.getByLabelText("Correo electrónico del despacho"));
    const pestanas = screen.getByRole("group", { name: "Documento de la vista previa" });
    expect(within(pestanas).getByRole("button", { name: "Correos" }).getAttribute("aria-pressed")).toBe("true");
    expect(marcados("correo")[0]?.classList.contains("foco")).toBe(true);
    expect(marcados("juez")[0]?.classList.contains("foco")).toBe(false);
  });

  it("permite saltar a un documento desde «Aparece en»", async () => {
    await montar();
    const grupo = screen.getByRole("group", { name: "Documentos donde aparece: Cargo del evaluador" });
    fireEvent.click(within(grupo).getByRole("button", { name: "Formato de calidad" }));
    expect(marcados("cargo_evaluador")[0]?.classList.contains("foco")).toBe(true);
  });

  it("cambia la plantilla, vuelve al fallo y avisa si el campo enfocado no aplica", async () => {
    await montar();
    fireEvent.focus(screen.getByLabelText("Pie de página del fallo (plantilla A)"));
    expect(screen.getByText(/no aparece en esta vista previa con la plantilla B/)).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /Generación A/ }));
    expect(barra()).not.toBeNull();
    expect(marcados("pie")).toHaveLength(2);
    expect(marcados("pie_fallo")).toHaveLength(0);
  });

  it("guarda el formato completo y reemplaza el estado con la respuesta", async () => {
    await montar();
    escribir("Ciudad", "Bogotá");
    fireEvent.click(screen.getByRole("radio", { name: /Generación A/ }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar formato" }));

    await waitFor(() => expect(barra()).toBeNull());
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.ruta).toBe("/api/formato");
    expect(put?.cuerpo?.plantilla_gen).toBe("A");
    expect(put?.cuerpo?.valores.ciudad).toBe("Bogotá");
    expect(Object.keys(put?.cuerpo?.valores ?? {}).sort()).toEqual(Object.keys(VALORES_MOCK).sort());
    expect(toasts.value.map((t) => t.texto)).toContain("Formato guardado");
    expect((screen.getByLabelText("Ciudad") as HTMLInputElement).value).toBe("Bogotá");
  });

  it("muestra los errores 422 por campo, enfoca el primero y los limpia al editar", async () => {
    simular((l) =>
      l.metodo === "PUT"
        ? json({ detail: { errores: [{ campo: "ciudad", mensaje: "debe ser texto." }, { campo: "pie_fallo.1", mensaje: "tiene un valor no válido." }, { campo: "", mensaje: "no es un JSON válido." }] } }, 422)
        : json(respuestaBase()),
    );
    await montar();
    escribir("Nombre del juez", "Ana");
    fireEvent.click(screen.getByRole("button", { name: "Guardar formato" }));

    const ciudad = (await screen.findByLabelText("Ciudad")) as HTMLInputElement;
    await waitFor(() => expect(ciudad.getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getByText("Debe ser texto.").id).toBe("f-ciudad-error");
    expect(ciudad.getAttribute("aria-describedby")).toContain("f-ciudad-error");
    expect(screen.getByText("Tiene un valor no válido.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("No es un JSON válido.");
    await waitFor(() => expect(document.activeElement).toBe(ciudad));
    expect(barra()).not.toBeNull();

    escribir("Ciudad", "Cali");
    expect(screen.queryByText("Debe ser texto.")).toBeNull();
    expect(ciudad.getAttribute("aria-invalid")).toBeNull();
  });

  it("muestra el error de guardado que no es de validación sin perder los cambios", async () => {
    simular((l) => (l.metodo === "PUT" ? json({ detail: "Disco lleno" }, 500) : json(respuestaBase())));
    await montar();
    escribir("Ciudad", "Cali");
    fireEvent.click(screen.getByRole("button", { name: "Guardar formato" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Disco lleno");
    expect(barra()).not.toBeNull();
    expect((screen.getByLabelText("Ciudad") as HTMLInputElement).value).toBe("Cali");
  });

  it("ofrece reintentar cuando falla la carga", async () => {
    let intentos = 0;
    simular(() => (++intentos === 1 ? json({ detail: "Servidor caído" }, 503) : json(respuestaBase())));
    render(<Formato />);
    expect((await screen.findByRole("alert")).textContent).toContain("Servidor caído");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await screen.findByRole("heading", { name: "Formato de los documentos" });
    expect(intentos).toBe(2);
  });
});

describe("editor de listas", () => {
  const lista = () => screen.getByRole("group", { name: "Líneas del juzgado en la firma de los correos" });
  const valoresLista = () => within(lista()).getAllByRole("textbox").map((i) => (i as HTMLInputElement).value);

  it("agrega, reordena y quita líneas con foco y nombres accesibles", async () => {
    await montar();
    fireEvent.click(within(lista()).getByRole("button", { name: "Agregar línea" }));
    expect(valoresLista()).toEqual(["Juzgado 3 Penal del Circuito con Funciones", "de Conocimiento de Medellín", ""]);
    await waitFor(() => expect(document.activeElement).toBe(within(lista()).getAllByRole("textbox")[2]));

    fireEvent.input(within(lista()).getAllByRole("textbox")[2] as HTMLElement, { target: { value: "Tercera" } });
    fireEvent.click(within(lista()).getByRole("button", { name: "Subir línea 3 de Líneas del juzgado en la firma de los correos" }));
    expect(valoresLista()).toEqual(["Juzgado 3 Penal del Circuito con Funciones", "Tercera", "de Conocimiento de Medellín"]);
    expect(within(lista()).getByRole("button", { name: "Subir línea 1 de Líneas del juzgado en la firma de los correos" }).hasAttribute("disabled")).toBe(true);

    fireEvent.click(within(lista()).getByRole("button", { name: "Quitar línea 1 de Líneas del juzgado en la firma de los correos" }));
    expect(valoresLista()).toEqual(["Tercera", "de Conocimiento de Medellín"]);
    expect(barra()).not.toBeNull();
    expect(marcados("firma_correo")[0]?.innerHTML).toBe("Tercera<br>de Conocimiento de Medellín");
  });

  it("refleja las líneas en la vista previa y descarta las vacías al guardar", async () => {
    await montar();
    fireEvent.click(within(lista()).getByRole("button", { name: "Agregar línea" }));
    fireEvent.input(within(lista()).getAllByRole("textbox")[0] as HTMLElement, { target: { value: "Cambiada" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Documento de la vista previa" })).getByRole("button", { name: "Correos" }));
    expect(marcados("firma_correo")[0]?.textContent).toContain("Cambiada");

    fireEvent.click(screen.getByRole("button", { name: "Guardar formato" }));
    await waitFor(() => expect(barra()).toBeNull());
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo?.valores.firma_correo).toEqual(["Cambiada", "de Conocimiento de Medellín"]);
  });
});

describe("guardia de salida", () => {
  const enlaceExterno = () => {
    const a = document.createElement("a");
    a.href = "#/ia";
    a.textContent = "Ir a IA";
    document.body.append(a);
    return a;
  };

  it("pide confirmación al seguir un enlace con cambios sin guardar", async () => {
    await montar();
    escribir("Ciudad", "Cali");
    const enlace = enlaceExterno();
    fireEvent.click(enlace);
    expect(location.hash).toBe("");
    const dialogo = await screen.findByRole("dialog", { hidden: true });
    expect(within(dialogo).getByText(/pierde los cambios/)).toBeTruthy();

    fireEvent.click(within(dialogo).getByRole("button", { name: "Seguir editando", hidden: true }));
    await waitFor(() => expect(screen.queryByText(/pierde los cambios/)).toBeNull());
    expect(location.hash).toBe("");

    fireEvent.click(enlace);
    fireEvent.click(await screen.findByRole("button", { name: "Salir sin guardar", hidden: true }));
    await waitFor(() => expect(location.hash).toBe("#/ia"));
    enlace.remove();
  });

  it("no interviene sin cambios", async () => {
    await montar();
    const enlace = enlaceExterno();
    fireEvent.click(enlace);
    await waitFor(() => expect(location.hash).toBe("#/ia"));
    expect(screen.queryByText(/pierde los cambios/)).toBeNull();
    enlace.remove();
  });

  it("cancela las navegaciones del historial cuando el navegador lo permite", async () => {
    const navegacion = new EventTarget();
    Object.defineProperty(window, "navigation", { value: navegacion, configurable: true });
    try {
      await montar();
      escribir("Ciudad", "Cali");
      await waitFor(() => expect(barra()).not.toBeNull());
      const intentar = (cancelable: boolean, url = "http://localhost:3000/#/ia", sameDocument = true) => {
        const evento = Object.assign(new Event("navigate", { cancelable }), { destination: { url, sameDocument } });
        navegacion.dispatchEvent(evento);
        return evento.defaultPrevented;
      };
      await act(async () => {
        expect(intentar(false)).toBe(false);
        expect(intentar(true, "http://localhost:3000/otra", false)).toBe(false);
        expect(intentar(true)).toBe(true);
      });
      expect(await screen.findByText(/pierde los cambios/)).toBeTruthy();

      fireEvent.click(await screen.findByRole("button", { name: "Salir sin guardar", hidden: true }));
      await waitFor(() => expect(location.hash).toBe("#/ia"));
    } finally {
      Reflect.deleteProperty(window, "navigation");
    }
  });

  it("avisa antes de cerrar la pestaña solo con cambios", async () => {
    await montar();
    const sin = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(sin);
    expect(sin.defaultPrevented).toBe(false);

    escribir("Ciudad", "Cali");
    const con = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(con);
    expect(con.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    const despues = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(despues);
    expect(despues.defaultPrevented).toBe(false);
  });
});
