import type { APIRequestContext } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { capturar, casosDir, crearCaso, expect, idDeCaso, test } from "../apoyo";

const enlaceDe = (nombre: string) => new RegExp(`^[^:]+: ${nombre}$`);
const enPapelera = (id: string) => readdirSync(join(casosDir(), ".papelera")).filter((n) => n.startsWith(`${id}@`));

async function idsEnApi(request: APIRequestContext): Promise<string[]> {
  return ((await (await request.get("/api/casos")).json()) as { id: string }[]).map((c) => c.id);
}

async function abiertosEnApi(request: APIRequestContext): Promise<number> {
  return ((await (await request.get("/api/casos")).json()) as { estado: string }[]).filter((c) => c.estado !== "terminado").length;
}

test("eliminar: confirmar quita el caso de la lista y Deshacer lo devuelve", async ({ page, request }) => {
  const nombre = "Caso para eliminar";
  await crearCaso(page, nombre);
  const id = await idDeCaso(request, nombre);
  await page.goto("/#/segunda");
  const lista = page.getByRole("region", { name: "Casos" });
  const ficha = lista.getByRole("article").filter({ hasText: nombre });
  await expect(ficha.getByRole("link", { name: enlaceDe(nombre) })).toBeVisible();
  const papelera = ficha.getByRole("button", { name: `Eliminar: ${nombre}` });
  await expect(papelera).toHaveAttribute("title", "Eliminar caso");
  await capturar(page, "24-eliminar-lista", lista);

  await papelera.click();
  const dialogo = page.getByRole("dialog", { name: "¿Eliminar este caso?" });
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByText(nombre, { exact: true })).toBeVisible();
  await expect(dialogo.getByText(/^Radicado /)).toBeVisible();
  await expect(dialogo.getByRole("button", { name: "Cancelar" })).toBeFocused();
  await capturar(page, "25-eliminar-confirmar");

  await dialogo.getByRole("button", { name: "Cancelar" }).click();
  await expect(dialogo).toBeHidden();
  await expect(papelera).toBeFocused();
  expect(existsSync(join(casosDir(), id))).toBe(true);

  await papelera.click();
  await dialogo.getByRole("button", { name: "Eliminar caso" }).click();
  await expect(dialogo).toBeHidden();
  await expect(ficha).toHaveCount(0);
  await expect(lista.getByRole("heading", { name: "Casos", level: 2 })).toBeFocused();
  const aviso = page.locator(".toast").filter({ hasText: `Se eliminó «${nombre}».` });
  await expect(aviso).toBeVisible();
  await capturar(page, "26-eliminar-aviso");
  expect(existsSync(join(casosDir(), id))).toBe(false);
  expect(enPapelera(id)).toHaveLength(1);
  expect(await idsEnApi(request)).not.toContain(id);

  await aviso.getByRole("button", { name: "Deshacer" }).click();
  await expect(page.locator(".toast").filter({ hasText: `Se restauró «${nombre}».` })).toBeVisible();
  await expect(ficha.getByRole("link", { name: enlaceDe(nombre) })).toBeVisible();
  await expect(lista.getByRole("heading", { name: "Casos", level: 2 })).toBeFocused();
  expect(existsSync(join(casosDir(), id))).toBe(true);
  expect(enPapelera(id)).toEqual([]);
  expect(await idsEnApi(request)).toContain(id);

  await page.reload();
  await expect(ficha).toBeVisible();
});

test("eliminar: con el teclado en la vista compacta, y el caso sigue fuera tras recargar", async ({ page, request }) => {
  const nombre = "Caso compacto para eliminar";
  await crearCaso(page, nombre);
  const id = await idDeCaso(request, nombre);
  await page.goto("/#/segunda");
  const lista = page.getByRole("region", { name: "Casos" });
  await lista.getByRole("button", { name: "Compacta" }).click();
  const fila = lista.getByRole("article").filter({ hasText: nombre });
  await expect(fila).toHaveClass(/fila-c/);
  await capturar(page, "27-eliminar-compacta", lista);

  await fila.getByRole("link", { name: enlaceDe(nombre) }).focus();
  await page.keyboard.press("Tab");
  await expect(fila.getByRole("button", { name: `Eliminar: ${nombre}` })).toBeFocused();
  await page.keyboard.press("Enter");
  const dialogo = page.getByRole("dialog", { name: "¿Eliminar este caso?" });
  await expect(dialogo.getByRole("button", { name: "Cancelar" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialogo.getByRole("button", { name: "Eliminar caso" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialogo).toBeHidden();
  await expect(fila).toHaveCount(0);
  await expect(lista.getByRole("heading", { name: "Casos", level: 2 })).toBeFocused();
  await expect(page.locator(".toast").filter({ hasText: `Se eliminó «${nombre}».` })).toBeVisible();
  expect(enPapelera(id)).toHaveLength(1);

  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Buscar casos" }).or(page.getByText("Aún no hay casos"))).toBeVisible();
  await expect(fila).toHaveCount(0);
  expect(await idsEnApi(request)).not.toContain(id);
});

test("eliminar: Deshacer después de volver a Inicio actualiza Inicio, no la página que se dejó", async ({ page, request }) => {
  const nombre = "Caso para deshacer desde Inicio";
  await crearCaso(page, nombre);
  const id = await idDeCaso(request, nombre);
  await page.goto("/#/segunda");
  const ficha = page.getByRole("region", { name: "Casos" }).getByRole("article").filter({ hasText: nombre });
  await ficha.getByRole("button", { name: `Eliminar: ${nombre}` }).click();
  await page.getByRole("dialog", { name: "¿Eliminar este caso?" }).getByRole("button", { name: "Eliminar caso" }).click();
  await expect(ficha).toHaveCount(0);
  const aviso = page.locator(".toast").filter({ hasText: `Se eliminó «${nombre}».` });
  await expect(aviso).toBeVisible();

  const abiertos = await abiertosEnApi(request);
  const tarjeta = page.locator(".proceso-t.activo");
  const textoAbiertos = (n: number) => (n === 1 ? "1 caso abierto" : `${n} casos abiertos`);
  await page.getByRole("link", { name: "Inicio", exact: true }).first().click();
  await expect(tarjeta.getByText(textoAbiertos(abiertos), { exact: true })).toBeVisible();

  await aviso.getByRole("button", { name: "Deshacer" }).click();
  await expect(page.locator(".toast").filter({ hasText: `Se restauró «${nombre}».` })).toBeVisible();
  await expect(tarjeta.getByText(textoAbiertos(abiertos + 1), { exact: true })).toBeVisible();
  expect(await idsEnApi(request)).toContain(id);
});
