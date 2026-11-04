import type { APIRequestContext } from "@playwright/test";
import { capturar, correr, crearCaso, decisionSintetica, descargar, expect, idDeCaso, parrafosDocx, test } from "../apoyo";

const JUEZ_NUEVO = "JUEZ DE PRUEBA E2E";
const JUEZ_ORIGINAL = "SANTIAGO ALEJANDRO CADAVID DUQUE";

const juezDe = async (request: APIRequestContext, id: string): Promise<string> =>
  ((await (await request.get(`/api/casos/${id}/config`)).json()) as { despacho: { juez: string } }).despacho.juez;

test.describe.configure({ mode: "serial" });

test("formato: editar un campo, guardar y conservar tras recargar", async ({ page, request }) => {
  await page.goto("/#/formato");
  const juez = page.getByRole("textbox", { name: "Nombre del juez", exact: true });
  await expect(juez).toHaveValue(JUEZ_ORIGINAL);
  await expect(page.getByRole("region", { name: "Cambios sin guardar" })).toHaveCount(0);
  await juez.fill(JUEZ_NUEVO);
  await expect(page.getByRole("region", { name: "Cambios sin guardar" })).toBeVisible();
  await expect(page.getByRole("region", { name: /Vista previa: Fallo/ })).toContainText(JUEZ_NUEVO);
  await capturar(page, "14-formato-editado");
  await page.getByRole("button", { name: "Guardar formato" }).click();
  await expect(page.getByRole("region", { name: "Cambios sin guardar" })).toBeHidden();
  const guardado = (await (await request.get("/api/formato")).json()) as { valores: { juez: string } };
  expect(guardado.valores.juez).toBe(JUEZ_NUEVO);
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Nombre del juez", exact: true })).toHaveValue(JUEZ_NUEVO);
  await capturar(page, "15-formato-guardado");
});

test("formato: la guardia de cambios sin guardar y descartar", async ({ page }) => {
  await page.goto("/#/formato");
  const ciudad = page.getByRole("textbox", { name: "Ciudad", exact: true });
  await expect(ciudad).toHaveValue("Medellín");
  await ciudad.fill("Bogotá");
  await page.getByRole("link", { name: "Inicio", exact: true }).first().click();
  const dialogo = page.getByRole("dialog", { name: "Hay cambios sin guardar" });
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByRole("button", { name: "Seguir editando" })).toBeFocused();
  await dialogo.getByRole("button", { name: "Seguir editando" }).click();
  await expect(dialogo).toBeHidden();
  await expect(page).toHaveURL(/#\/formato$/);
  await expect(ciudad).toHaveValue("Bogotá");
  await capturar(page, "16-formato-guardia");
  await page.getByRole("button", { name: "Descartar" }).click();
  await expect(ciudad).toHaveValue("Medellín");
  await ciudad.fill("Cali");
  await page.getByRole("link", { name: "Inicio", exact: true }).first().click();
  await dialogo.getByRole("button", { name: "Salir sin guardar" }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByRole("heading", { name: "Elige el proceso a realizar" })).toBeVisible();
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const evento = new Event("beforeunload", { cancelable: true });
          window.dispatchEvent(evento);
          return evento.defaultPrevented;
        }),
      { message: "tras salir sin guardar no debe quedar la guardia de beforeunload", timeout: 5000 },
    )
    .toBe(false);
  await page.goto("/#/formato");
  await expect(page.getByRole("textbox", { name: "Ciudad", exact: true })).toHaveValue("Medellín");
});

test("formato: un caso nuevo usa el formato guardado y el existente conserva el suyo", async ({ page, request }) => {
  test.setTimeout(120_000);
  const idA = await idDeCaso(request, "Caso A amparo");
  await crearCaso(page, "Caso C formato");
  const idC = await idDeCaso(request, "Caso C formato");
  expect(await juezDe(request, idC)).toBe(JUEZ_NUEVO);
  expect(await juezDe(request, idA)).toBe(JUEZ_ORIGINAL);

  await correr(request, idC, { cmd: "iniciar" });
  await correr(request, idC, { cmd: "decidir", decision: decisionSintetica() });
  await page.goto(`/#/segunda/${idC}/fallo`);
  const nuevo = await descargar(page, page.getByRole("link", { name: "Descargar fallo" }), "formato-c");
  const textoNuevo = parrafosDocx(nuevo.ruta).join("\n");
  expect(textoNuevo).toContain(JUEZ_NUEVO);
  expect(textoNuevo).not.toContain(JUEZ_ORIGINAL);

  await page.goto(`/#/segunda/${idA}/fallo`);
  const viejo = await descargar(page, page.getByRole("link", { name: "Descargar fallo" }), "formato-a");
  const textoViejo = parrafosDocx(viejo.ruta).join("\n");
  expect(textoViejo).toContain(JUEZ_ORIGINAL);
  expect(textoViejo).not.toContain(JUEZ_NUEVO);
});
