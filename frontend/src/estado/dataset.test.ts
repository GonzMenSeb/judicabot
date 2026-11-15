import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const URL_DATOS = "https://www.datos.gov.co/resource/v2k4-2t8s.csv?$limit=50000";
const CSV = '"sentencia","magistrado_a","fecha_sentencia"\n"T-200/22","José Fernando Reyes Cuartas","2022-06-06"\n';

type Llamada = { url: string; init?: RequestInit };

function simular(rutas: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  const llamadas: Llamada[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      llamadas.push({ url, init });
      const respuesta = rutas[`${init?.method ?? "GET"} ${url}`];
      if (!respuesta) throw new TypeError(`sin simulación para ${init?.method ?? "GET"} ${url}`);
      return respuesta(init);
    }),
  );
  return llamadas;
}

const json = (cuerpo: unknown) => new Response(JSON.stringify(cuerpo), { headers: { "Content-Type": "application/json" } });

async function cargar() {
  vi.resetModules();
  return (await import("./dataset")).sincronizarDataset;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sincronizarDataset", () => {
  it("si el servidor ya tiene el dataset vigente no pide nada a datos.gov.co", async () => {
    const llamadas = simular({ "GET /api/dataset": () => json({ vigente: true, url: URL_DATOS }) });
    await (await cargar())();
    expect(llamadas.map((l) => l.url)).toEqual(["/api/dataset"]);
  });

  it("si no está vigente lo descarga desde el navegador y lo sube sin interpretarlo", async () => {
    const subido: { archivo?: FormDataEntryValue | null } = {};
    const llamadas = simular({
      "GET /api/dataset": () => json({ vigente: false, url: URL_DATOS }),
      [`GET ${URL_DATOS}`]: () => new Response(CSV, { headers: { "Content-Type": "text/csv" } }),
      "PUT /api/dataset": (init) => {
        subido.archivo = (init?.body as FormData).get("archivo");
        return new Response(null, { status: 204 });
      },
    });
    await (await cargar())();
    expect(llamadas.map((l) => `${l.init?.method ?? "GET"} ${l.url}`)).toEqual([
      "GET /api/dataset",
      `GET ${URL_DATOS}`,
      "PUT /api/dataset",
    ]);
    const origen = llamadas[1]?.init;
    expect(origen).toMatchObject({ credentials: "omit", referrerPolicy: "no-referrer" });
    expect(origen?.method).toBeUndefined();
    expect(subido.archivo).toBeInstanceOf(File);
    const archivo = subido.archivo as File;
    expect(archivo.name).toBe("cc_sentencias.csv");
    expect(await archivo.text()).toBe(CSV);
  });

  it("si datos.gov.co no responde bien no sube nada y no falla", async () => {
    const llamadas = simular({
      "GET /api/dataset": () => json({ vigente: false, url: URL_DATOS }),
      [`GET ${URL_DATOS}`]: () => new Response("caído", { status: 503 }),
    });
    await expect((await cargar())()).resolves.toBeUndefined();
    expect(llamadas.some((l) => l.init?.method === "PUT")).toBe(false);
  });

  it("si el navegador no puede llegar a datos.gov.co deja que el servidor use su propia descarga", async () => {
    simular({ "GET /api/dataset": () => json({ vigente: false, url: URL_DATOS }) });
    await expect((await cargar())()).resolves.toBeUndefined();
  });

  it("si el servidor rechaza el archivo no propaga el error", async () => {
    simular({
      "GET /api/dataset": () => json({ vigente: false, url: URL_DATOS }),
      [`GET ${URL_DATOS}`]: () => new Response(CSV),
      "PUT /api/dataset": () => new Response(JSON.stringify({ detail: "no es el dataset" }), { status: 422 }),
    });
    await expect((await cargar())()).resolves.toBeUndefined();
  });

  it("si el servidor no responde (sesión sin abrir, red caída) no propaga el error", async () => {
    simular({ "GET /api/dataset": () => new Response(JSON.stringify({ detail: "No autenticado" }), { status: 401 }) });
    await expect((await cargar())()).resolves.toBeUndefined();
  });

  it("no repite la sincronización durante la misma sesión", async () => {
    const llamadas = simular({ "GET /api/dataset": () => json({ vigente: true, url: URL_DATOS }) });
    const sincronizar = await cargar();
    await sincronizar();
    await sincronizar();
    expect(llamadas).toHaveLength(1);
  });
});
