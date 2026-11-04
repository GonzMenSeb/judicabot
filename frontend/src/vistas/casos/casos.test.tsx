import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toasts } from "../../estado";
import Casos from "./index";
import { casosMock } from "./mock";
import { useSoltarGlobal } from "./soltar";
import { archivoDe, json, simularFetch, XhrFalso } from "./utilesPrueba";

beforeEach(() => {
  location.hash = "";
  toasts.value = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const entradas = (contenedor: Element) => contenedor.querySelectorAll<HTMLInputElement>('input[type="file"]');

function elegirArchivos(contenedor: Element, rutas: string[]) {
  const [carpeta] = entradas(contenedor);
  fireEvent.change(carpeta!, { target: { files: rutas.map((r) => archivoDe(r)) } });
}

describe("lista de casos", () => {
  it("agrupa los casos, muestra avance, alertas, siguiente paso y enlaces a la etapa que corresponde", async () => {
    simularFetch({ "GET /api/casos": () => json(casosMock) });
    render(<Casos />);
    expect(await screen.findByRole("heading", { level: 3, name: /Requieren su atención/ })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: /En redacción/ })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: /Terminados/ })).toBeTruthy();

    const decidir = screen.getByRole("link", { name: "Decidir: Quintero Bedoya c. EPS Horizonte Salud" });
    expect(decidir.getAttribute("href")).toBe("#/segunda/quintero-bedoya/borrador");
    expect(screen.getByRole("link", { name: /Completar: Cárdenas/ }).getAttribute("href")).toBe("#/segunda/cardenas-ospina/documentos");
    expect(screen.getByRole("link", { name: /Ver avance: Restrepo/ }).getAttribute("href")).toBe("#/segunda/restrepo-gil/proceso");
    expect(screen.getAllByRole("link", { name: /Ver fallo/ }).map((a) => a.getAttribute("href"))).toEqual([
      "#/segunda/mejia-rios/fallo",
      "#/segunda/duque-salazar/fallo",
    ]);

    const ficha = decidir.closest("article")!;
    expect(within(ficha).getByText("Revisar el borrador y decidir")).toBeTruthy();
    expect(within(ficha).getByText("1 alerta")).toBeTruthy();
    expect(within(ficha).getByText("Radicado 2026-00412")).toBeTruthy();
    expect(within(ficha).getByRole("img", { name: "Avance: paso 3 de 4, Decisión" })).toBeTruthy();
    expect(Array.from(ficha.querySelectorAll(".seg4 i")).map((i) => i.className)).toEqual(["h", "h", "a", ""]);
  });

  it("filtra con la búsqueda y avisa cuando nada coincide", async () => {
    simularFetch({ "GET /api/casos": () => json(casosMock) });
    render(<Casos />);
    const buscar = await screen.findByRole("searchbox", { name: "Buscar casos" });

    fireEvent.input(buscar, { target: { value: "ceiba" } });
    await waitFor(() => expect(screen.queryByText("Quintero Bedoya c. EPS Horizonte Salud")).toBeNull());
    expect(screen.getByText("Arango Londoño c. EPS Ceiba Salud")).toBeTruthy();
    expect(screen.getByText("Duque Salazar c. EPS Ceiba Salud")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 3, name: /En redacción/ })).toBeNull();

    fireEvent.input(buscar, { target: { value: "zzz" } });
    expect(await screen.findByText("Ningún caso coincide con «zzz».")).toBeTruthy();
  });

  it("muestra un estado vacío cuando no hay casos", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    render(<Casos />);
    expect(await screen.findByText("Aún no hay casos")).toBeTruthy();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("muestra el error de red y permite reintentar", async () => {
    let intento = 0;
    simularFetch({
      "GET /api/casos": () => {
        intento += 1;
        if (intento === 1) throw new TypeError("Failed to fetch");
        return json(casosMock);
      },
    });
    render(<Casos />);
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toMatch(/No se pudo conectar con el servidor/);
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("heading", { level: 3, name: /Requieren su atención/ })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("muestra el detalle de un error HTTP", async () => {
    simularFetch({ "GET /api/casos": () => json({ detail: "Sin permiso" }, 403) });
    render(<Casos />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Sin permiso/);
  });
});

describe("nuevo caso", () => {
  beforeEach(() => {
    XhrFalso.ultimo = null;
    vi.stubGlobal("XMLHttpRequest", XhrFalso);
  });

  it("muestra el árbol de la carpeta elegida y el nombre por defecto", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, [
      "Tutela 2026-00412/01PrimeraInstancia/C01Principal/001.pdf",
      "Tutela 2026-00412/01PrimeraInstancia/C01Principal/002.pdf",
      "Tutela 2026-00412/01PrimeraInstancia/C01Principal/003.pdf",
      "Tutela 2026-00412/01PrimeraInstancia/C01Principal/004.pdf",
      "Tutela 2026-00412/02SegundaInstancia/otro.pdf",
      "Tutela 2026-00412/.DS_Store",
    ]);
    expect(await screen.findByRole("heading", { name: "Carpeta lista" })).toBeTruthy();
    expect(screen.getByText("5 archivos (5 B)")).toBeTruthy();
    const arbol = screen.getByRole("list", { name: "Contenido de la carpeta" });
    expect(within(arbol).getByText("esta")).toBeTruthy();
    expect(within(arbol).getByText(/se ignora/)).toBeTruthy();
    expect(within(arbol).getByText("001.pdf … 004.pdf")).toBeTruthy();
    const nombre = screen.getByLabelText("Nombre del caso (opcional)") as HTMLInputElement;
    expect(nombre.placeholder).toBe("Tutela 2026-00412");
    expect(nombre.value).toBe("");
  });

  it("sube con progreso, inicia la lectura y navega a documentos", async () => {
    const llamadas = simularFetch({
      "GET /api/casos": () => json([]),
      "POST /api/casos/c-nuevo/run": () => json({ job_id: "j1" }),
    });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/01PrimeraInstancia/a.pdf", "T/01PrimeraInstancia/b.pdf"]);
    fireEvent.input(await screen.findByLabelText("Nombre del caso (opcional)"), { target: { value: "Mi tutela" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear caso y revisar documentos" }));

    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    const xhr = XhrFalso.ultimo!;
    const datos = xhr.cuerpo as FormData;
    expect(datos.get("nombre")).toBe("Mi tutela");
    expect((datos.getAll("files") as File[]).map((f) => f.name)).toEqual(["T/01PrimeraInstancia/a.pdf", "T/01PrimeraInstancia/b.pdf"]);

    act(() => xhr.progreso(40, 100));
    const barra = await screen.findByRole("progressbar", { name: "Progreso de la subida" });
    await waitFor(() => expect(barra.getAttribute("aria-valuenow")).toBe("40"));
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeTruthy();

    act(() => xhr.responder(200, { id: "c-nuevo", n_insumos: 2 }));
    await waitFor(() => expect(location.hash).toBe("#/segunda/c-nuevo/documentos"));
    expect(llamadas.find((l) => l.ruta === "/api/casos/c-nuevo/run")?.cuerpo).toEqual({ cmd: "nuevo" });
    expect(toasts.value.map((t) => t.texto)).toEqual(["Caso «c-nuevo» creado con 2 archivos."]);
  });

  it("navega aunque la lectura ya estuviera en curso (409) sin mostrar error", async () => {
    simularFetch({
      "GET /api/casos": () => json([]),
      "POST /api/casos/c-2/run": () => json({ detail: "Ya hay un job en curso." }, 409),
    });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/a.pdf", "T/b.pdf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Crear caso y revisar documentos" }));
    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    act(() => XhrFalso.ultimo!.responder(200, { id: "c-2", n_insumos: 2 }));
    await waitFor(() => expect(location.hash).toBe("#/segunda/c-2/documentos"));
    expect(toasts.value.some((t) => t.tipo === "error")).toBe(false);
  });

  it("conserva la selección y muestra el error del servidor (422) para reintentar", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/a.pdf", "T/b.pdf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Crear caso y revisar documentos" }));
    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    act(() => XhrFalso.ultimo!.responder(422, { detail: [{ msg: "Nombre demasiado largo" }] }));
    expect((await screen.findByRole("alert")).textContent).toBe("Nombre demasiado largo");
    expect(screen.getByRole("heading", { name: "Carpeta lista" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Crear caso y revisar documentos" }) as HTMLButtonElement).disabled).toBe(false);
    expect(location.hash).toBe("");
  });

  it("muestra el error de red de la subida y el 409", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/a.pdf", "T/b.pdf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Crear caso y revisar documentos" }));
    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    act(() => XhrFalso.ultimo!.fallarRed());
    expect((await screen.findByRole("alert")).textContent).toMatch(/No se pudo conectar/);

    XhrFalso.ultimo = null;
    fireEvent.click(screen.getByRole("button", { name: "Crear caso y revisar documentos" }));
    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    act(() => XhrFalso.ultimo!.responder(409, { detail: "Ya existe un caso con ese nombre." }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Ya existe un caso con ese nombre."));
  });

  it("cancela la subida en curso y vuelve a la carpeta lista", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/a.pdf", "T/b.pdf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Crear caso y revisar documentos" }));
    await waitFor(() => expect(XhrFalso.ultimo).not.toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    expect(XhrFalso.ultimo!.abortado).toBe(true);
    expect(await screen.findByRole("button", { name: "Elegir otra carpeta" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("avisa si lo elegido no tiene archivos útiles", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/.oculto"]);
    expect((await screen.findByRole("alert")).textContent).toMatch(/No se encontraron archivos/);
    expect(screen.queryByRole("heading", { name: "Carpeta lista" })).toBeNull();
  });

  it("vuelve a elegir otra carpeta", async () => {
    simularFetch({ "GET /api/casos": () => json([]) });
    const { container } = render(<Casos />);
    await screen.findByText("Aún no hay casos");
    elegirArchivos(container, ["T/a.pdf", "T/b.pdf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Elegir otra carpeta" }));
    expect(await screen.findByRole("heading", { name: "Nuevo caso" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Elegir carpeta" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Elegir archivos" })).toBeTruthy();
  });
});

describe("soltar en cualquier parte de la página", () => {
  const archivos = { dataTransfer: { types: ["Files"], items: [], files: [] } };

  beforeEach(() => {
    simularFetch({ "GET /api/casos": () => json([]) });
  });

  it("mantiene la capa mientras el contador de dragenter no vuelva a cero", async () => {
    render(<Casos />);
    await screen.findByText("Aún no hay casos");
    fireEvent.dragEnter(document, archivos);
    fireEvent.dragEnter(document, archivos);
    expect(await screen.findByText("Suelte la carpeta")).toBeTruthy();
    fireEvent.dragLeave(document, archivos);
    expect(screen.getByText("Suelte la carpeta")).toBeTruthy();
    fireEvent.dragLeave(document, archivos);
    await waitFor(() => expect(screen.queryByText("Suelte la carpeta")).toBeNull());
  });

  it("ignora arrastres que no traen archivos", async () => {
    render(<Casos />);
    await screen.findByText("Aún no hay casos");
    fireEvent.dragEnter(document, { dataTransfer: { types: ["text/plain"] } });
    expect(screen.queryByText("Suelte la carpeta")).toBeNull();
  });

  it("lee la carpeta soltada y muestra su árbol", async () => {
    const hoja = {
      isFile: true,
      isDirectory: false,
      fullPath: "/Tutela X/01PrimeraInstancia/001.pdf",
      file: (ok: (f: File) => void) => ok(archivoDe("Tutela X/01PrimeraInstancia/001.pdf")),
    };
    const interna = {
      isFile: false,
      isDirectory: true,
      fullPath: "/Tutela X/01PrimeraInstancia",
      createReader: () => {
        let dado = false;
        return { readEntries: (ok: (l: unknown[]) => void) => { ok(dado ? [] : [hoja]); dado = true; } };
      },
    };
    const raiz = {
      isFile: false,
      isDirectory: true,
      fullPath: "/Tutela X",
      createReader: () => {
        let dado = false;
        return { readEntries: (ok: (l: unknown[]) => void) => { ok(dado ? [] : [interna]); dado = true; } };
      },
    };
    render(<Casos />);
    await screen.findByText("Aún no hay casos");
    fireEvent.dragEnter(document, archivos);
    await screen.findByText("Suelte la carpeta");
    fireEvent.drop(document, { dataTransfer: { types: ["Files"], items: [{ kind: "file", webkitGetAsEntry: () => raiz }], files: [] } });
    expect(await screen.findByRole("heading", { name: "Carpeta lista" })).toBeTruthy();
    expect(screen.queryByText("Suelte la carpeta")).toBeNull();
    expect(screen.getByRole("list", { name: "Contenido de la carpeta" }).textContent).toContain("001.pdf");
    expect((screen.getByLabelText("Nombre del caso (opcional)") as HTMLInputElement).placeholder).toBe("Tutela X");
  });

  it("previene la navegación del navegador al soltar un archivo", async () => {
    render(<Casos />);
    await screen.findByText("Aún no hay casos");
    const evento = new Event("drop", { cancelable: true });
    Object.defineProperty(evento, "dataTransfer", { value: { types: ["Files"], items: [], files: [] } });
    document.dispatchEvent(evento);
    expect(evento.defaultPrevented).toBe(true);
  });
});

describe("useSoltarGlobal", () => {
  function Sonda({ habilitado = true }: { habilitado?: boolean }) {
    const activo = useSoltarGlobal(() => undefined, habilitado);
    return <output>{activo ? "activo" : "quieto"}</output>;
  }

  it("oculta la capa si el arrastre termina sin eventos de salida", () => {
    vi.useFakeTimers();
    try {
      render(<Sonda />);
      act(() => {
        fireEvent.dragEnter(document, { dataTransfer: { types: ["Files"] } });
      });
      expect(screen.getByText("activo")).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(1600);
      });
      expect(screen.getByText("quieto")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("no muestra la capa si está deshabilitado", () => {
    render(<Sonda habilitado={false} />);
    act(() => {
      fireEvent.dragEnter(document, { dataTransfer: { types: ["Files"] } });
    });
    expect(screen.getByText("quieto")).toBeTruthy();
  });
});
