import { expect, test as base } from "@playwright/test";
import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";

export { expect };

export const raiz = (): string => {
  const valor = process.env.E2E_RAIZ;
  if (!valor) throw new Error("E2E_RAIZ no está definida");
  return valor;
};
export const insumos = (): string => join(raiz(), "insumos", "01PrimeraInstancia");
export const casosDir = (servidor = "abierto"): string => join(raiz(), servidor, "casos");
export const descargas = (): string => {
  const ruta = join(raiz(), "descargas");
  mkdirSync(ruta, { recursive: true });
  return ruta;
};
const capturas = join(import.meta.dirname, "capturas");
const backend = resolve(import.meta.dirname, "../../backend");

interface Vigilante {
  permitir: (estado: number, patron: RegExp) => void;
  consola: string[];
  fallidas: string[];
}

export const test = base.extend<{ vigilante: Vigilante }>({
  vigilante: [
    async ({ page }, use) => {
      const consola: string[] = [];
      const fallidas: string[] = [];
      const permitidas: { estado: number; patron: RegExp }[] = [];
      page.on("console", (m) => {
        if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) consola.push(m.text());
      });
      page.on("pageerror", (e) => consola.push(`pageerror: ${e.message}`));
      page.on("response", (r) => {
        const estado = r.status();
        if (estado < 400) return;
        if (permitidas.some((p) => p.estado === estado && p.patron.test(r.url()))) return;
        fallidas.push(`${estado} ${r.request().method()} ${r.url()}`);
      });
      page.on("requestfailed", (r) => {
        const motivo = r.failure()?.errorText ?? "";
        if (!motivo.includes("ERR_ABORTED")) fallidas.push(`fallo ${r.method()} ${r.url()} ${motivo}`);
      });
      await use({ permitir: (estado, patron) => permitidas.push({ estado, patron }), consola, fallidas });
      expect.soft(consola, "errores de consola").toEqual([]);
      expect.soft(fallidas, "peticiones 4xx/5xx inesperadas").toEqual([]);
    },
    { auto: true },
  ],
});

export async function capturar(page: Page, nombre: string): Promise<void> {
  mkdirSync(capturas, { recursive: true });
  for (const [ancho, alto] of [
    [1440, 900],
    [390, 844],
  ] as const) {
    await page.setViewportSize({ width: ancho, height: alto });
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      return new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    });
    await page.screenshot({ path: join(capturas, `${nombre}-${ancho}.png`), fullPage: true });
    if (ancho === 390) {
      const desborde = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect.soft(desborde, `${nombre}: desborde horizontal a 390 px`).toBeLessThanOrEqual(1);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

export async function tabularHasta(page: Page, destino: Locator, max = 150): Promise<number> {
  await page.locator("main").focus();
  for (let n = 1; n <= max; n++) {
    await page.keyboard.press("Tab");
    if (await destino.evaluate((el) => el === document.activeElement)) return n;
  }
  throw new Error(`No se llegó al elemento con Tab en ${max} pulsaciones`);
}

export async function elegirCarpeta(page: Page, ruta: string, porTeclado = false): Promise<void> {
  const boton = page.getByRole("button", { name: "Elegir carpeta" });
  const [selector] = await Promise.all([
    page.waitForEvent("filechooser"),
    porTeclado ? tabularHasta(page, boton).then(() => page.keyboard.press("Enter")) : boton.click(),
  ]);
  await selector.setFiles(ruta);
  await expect(page.getByRole("heading", { name: "Carpeta lista" })).toBeVisible();
}

export async function crearCaso(page: Page, nombre: string, porTeclado = false): Promise<void> {
  await page.goto("/#/segunda");
  await elegirCarpeta(page, insumos(), porTeclado);
  await page.getByLabel("Nombre del caso (opcional)").fill(nombre);
  const crear = page.getByRole("button", { name: "Crear caso y revisar documentos" });
  if (porTeclado) {
    await tabularHasta(page, crear);
    await page.keyboard.press("Enter");
  } else {
    await crear.click();
  }
  await page.waitForURL(/#\/segunda\/[^/]+\/documentos$/);
  await expect(page.getByRole("button", { name: "Iniciar redacción" })).toBeVisible();
}

export async function idDeCaso(request: APIRequestContext, nombre: string): Promise<string> {
  const respuesta = await request.get("/api/casos");
  expect(respuesta.ok()).toBeTruthy();
  const casos = (await respuesta.json()) as { id: string; nombre: string }[];
  const caso = casos.find((c) => c.nombre === nombre);
  if (!caso) throw new Error(`No existe el caso «${nombre}»`);
  return caso.id;
}

export async function iniciarRedaccion(page: Page, porTeclado = false): Promise<void> {
  const boton = page.getByRole("button", { name: "Iniciar redacción" });
  if (porTeclado) {
    await tabularHasta(page, boton);
    await page.keyboard.press("Enter");
  } else {
    await boton.click();
  }
  const clave = page.getByRole("textbox", { name: "Clave de la API" });
  const destino = page.waitForURL(/\/proceso$/);
  const dialogo = clave.waitFor({ state: "visible", timeout: 3000 }).then(
    () => true,
    () => false,
  );
  if (await dialogo) {
    await clave.fill("sk-ant-e2e-sin-uso");
    await page.getByRole("button", { name: "Guardar y continuar" }).click();
  }
  await destino;
}

export async function espiarEventos(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const Original = window.EventSource;
    const registro = { abiertas: [] as string[], eventos: 0, fin: null as string | null };
    (window as unknown as { __sse: typeof registro }).__sse = registro;
    window.EventSource = class extends Original {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(url, init);
        registro.abiertas.push(String(url));
        this.addEventListener("evento", () => (registro.eventos += 1));
        this.addEventListener("fin", (e) => (registro.fin = (e as MessageEvent<string>).data));
      }
    } as typeof EventSource;
  });
}

export const leerEventos = (page: Page) =>
  page.evaluate(() => (window as unknown as { __sse?: { abiertas: string[]; eventos: number; fin: string | null } }).__sse ?? null);

const PYTHON_DOCX = `
import json, sys, zipfile
from docx import Document
ruta = sys.argv[1]
if zipfile.ZipFile(ruta).testzip() is not None:
    raise SystemExit("zip corrupto")
d = Document(ruta)
textos = [p.text for p in d.paragraphs if p.text.strip()]
for t in d.tables:
    for fila in t.rows:
        for c in fila.cells:
            textos += [p.text for p in c.paragraphs if p.text.strip()]
print(json.dumps(textos, ensure_ascii=False))
`;

const PYTHON_ZIP = `
import json, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
malo = z.testzip()
print(json.dumps({"malo": malo, "nombres": z.namelist()}, ensure_ascii=False))
`;

export function parrafosDocx(ruta: string): string[] {
  const salida = execFileSync("uv", ["run", "python", "-I", "-c", PYTHON_DOCX, ruta], { cwd: backend, encoding: "utf-8" });
  return JSON.parse(salida) as string[];
}

export function contenidoZip(ruta: string): { malo: string | null; nombres: string[] } {
  const salida = execFileSync("uv", ["run", "python", "-I", "-c", PYTHON_ZIP, ruta], { cwd: backend, encoding: "utf-8" });
  return JSON.parse(salida) as { malo: string | null; nombres: string[] };
}

export async function descargar(page: Page, enlace: Locator, destino: string): Promise<{ ruta: string; nombre: string }> {
  const [descarga] = await Promise.all([page.waitForEvent("download"), enlace.click()]);
  const ruta = join(descargas(), `${destino}-${descarga.suggestedFilename()}`);
  await descarga.saveAs(ruta);
  return { ruta, nombre: descarga.suggestedFilename() };
}

export const normalizar = (texto: string): string => texto.replace(/\s+/g, " ").trim();

export function decisionSintetica(): Record<string, unknown> {
  const script = "import json, sys; sys.path.insert(0, 'scripts'); import caso_sintetico as c; print(json.dumps(c.DECISION_POR_DEFECTO))";
  return JSON.parse(execFileSync("uv", ["run", "python", "-I", "-c", script], { cwd: backend, encoding: "utf-8" })) as Record<string, unknown>;
}

export async function esperarJob(request: APIRequestContext, jobId: string): Promise<void> {
  await expect
    .poll(
      async () => {
        const job = (await (await request.get(`/api/jobs/${jobId}`)).json()) as { estado: string; error?: string | null };
        if (job.estado === "error") throw new Error(`El job ${jobId} falló: ${job.error}`);
        return job.estado;
      },
      { timeout: 60_000, intervals: [300] },
    )
    .toBe("terminado");
}

export async function correr(request: APIRequestContext, caso: string, cuerpo: Record<string, unknown>): Promise<void> {
  const respuesta = await request.post(`/api/casos/${caso}/run`, { data: cuerpo });
  expect(respuesta.status()).toBe(200);
  await esperarJob(request, ((await respuesta.json()) as { job_id: string }).job_id);
}
