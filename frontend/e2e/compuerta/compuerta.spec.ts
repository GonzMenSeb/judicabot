import { capturar, crearCaso, espiarEventos, expect, iniciarRedaccion, leerEventos, test } from "../apoyo";

const CLAVE = process.env.E2E_CLAVE ?? "";

test.describe.configure({ mode: "serial" });

test("sin sesión: la interfaz redirige al acceso y la API responde 401", async ({ page, request, vigilante }) => {
  vigilante.permitir(401, /\/api\//);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByPlaceholder("Contraseña")).toBeVisible();
  await capturar(page, "20-acceso");
  const api = await request.get("/api/casos");
  expect(api.status()).toBe(401);
  expect((await request.get("/healthz")).status()).toBe(200);
});

test("contraseña incorrecta no abre la sesión y la correcta sí", async ({ page, vigilante }) => {
  vigilante.permitir(401, /\/login$/);
  await page.goto("/login");
  await page.getByPlaceholder("Contraseña").fill("incorrecta");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Contraseña incorrecta.")).toBeVisible();
  await page.getByPlaceholder("Contraseña").fill(CLAVE);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Elige el proceso a realizar", level: 1 })).toBeVisible();
  const cookies = await page.context().cookies();
  const acceso = cookies.find((c) => c.name === "judicabot_acceso");
  expect(acceso?.httpOnly).toBe(true);
  expect(acceso?.sameSite).toBe("Lax");
});

test("con sesión: la interfaz y el SSE funcionan detrás de la compuerta", async ({ page, context }) => {
  test.setTimeout(120_000);
  await espiarEventos(page);
  await page.goto("/login");
  await page.getByPlaceholder("Contraseña").fill(CLAVE);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/$/);

  await crearCaso(page, "Caso protegido");
  await expect(page.getByText("Están las piezas obligatorias")).toBeVisible();

  const flujo = page.waitForResponse((r) => /\/api\/jobs\/[^/]+\/eventos/.test(r.url()));
  await iniciarRedaccion(page);
  const respuesta = await flujo;
  expect(respuesta.status()).toBe(200);
  expect(respuesta.headers()["content-type"]).toContain("text/event-stream");
  await expect(page.getByRole("link", { name: "Ver el borrador" })).toBeVisible();
  await expect(page.getByText("Ejecución terminada")).toBeVisible();
  const sse = await leerEventos(page);
  expect(sse?.eventos).toBeGreaterThanOrEqual(10);
  expect(sse?.fin).toContain("terminado");
  await capturar(page, "21-proceso-protegido");

  const jobs = (await (await context.request.get("/api/casos")).json()) as { id: string; job_activo: string | null }[];
  expect(jobs.length).toBe(1);
  const sinSesion = await (await import("@playwright/test")).request.newContext({ baseURL: page.url().split("#")[0] ?? "" });
  expect((await sinSesion.get("/api/casos")).status()).toBe(401);
  await sinSesion.dispose();
});
