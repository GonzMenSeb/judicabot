import { capturar, crearCaso, descargar, expect, idDeCaso, iniciarRedaccion, normalizar, parrafosDocx, tabularHasta, test } from "../apoyo";

const NOMBRE = "Caso B confirma";

async function teclear(page: import("@playwright/test").Page, nombre: string | RegExp, rol: "button" | "link" | "radio"): Promise<void> {
  const destino = page.getByRole(rol, { name: nombre });
  await tabularHasta(page, destino);
  await expect(destino).toBeFocused();
  await page.keyboard.press(rol === "radio" ? "Space" : "Enter");
}

test("decisión CONFIRMAR de punta a punta usando solo el teclado", async ({ page, request }) => {
  test.setTimeout(120_000);
  await crearCaso(page, NOMBRE, true);
  const id = await idDeCaso(request, NOMBRE);
  await expect(page.locator("main")).toBeVisible();

  await iniciarRedaccion(page, true);
  await expect(page.getByRole("link", { name: "Ver el borrador" })).toBeVisible();
  await teclear(page, "Ver el borrador", "link");
  await expect(page).toHaveURL(/\/borrador$/);
  await expect(page.getByRole("article", { name: /Borrador del fallo/ })).toBeVisible();
  await expect(page.locator("main")).toBeFocused();
  await teclear(page, "Pasar a la decisión", "link");
  await expect(page).toHaveURL(/\/decision$/);

  await expect(page.getByRole("complementary", { name: "Vista previa del RESUELVE" })).toBeVisible();
  await teclear(page, "Confirmar", "radio");
  await expect(page.getByRole("radio", { name: "Confirmar" })).toBeChecked();
  await expect(page.getByRole("radiogroup", { name: "En su lugar, el Despacho" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Órdenes" })).toHaveCount(0);
  const resuelve = page.getByRole("complementary", { name: "Vista previa del RESUELVE" });
  await expect(resuelve).toContainText("CONFIRMAR");
  await expect(resuelve).not.toContainText("REVOCAR");

  const eje = page.getByRole("textbox", { name: "Por qué, en pocas líneas" });
  await eje.focus();
  await page.keyboard.type("Se confirma la decisión de primera instancia por las razones expuestas en la impugnación.");
  await expect(page.getByRole("status").filter({ hasText: "Listo para enviar" })).toBeVisible();
  await capturar(page, "12-decision-confirmar");

  await teclear(page, "Enviar decisión y redactar", "button");
  const dialogo = page.getByRole("dialog", { name: "¿Enviar la decisión?" });
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByRole("button", { name: "Enviar decisión" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialogo.getByRole("button", { name: "Revisar" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialogo).toBeHidden();
  await teclear(page, "Enviar decisión y redactar", "button");
  await expect(dialogo.getByRole("button", { name: "Enviar decisión" })).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/proceso$/);
  await expect(page.getByRole("link", { name: "Ver el fallo" })).toBeVisible();
  await teclear(page, "Ver el fallo", "link");
  await expect(page).toHaveURL(/\/fallo$/);
  const vista = page.getByRole("region", { name: "Vista previa del fallo" });
  await expect(vista).toBeVisible();
  await expect(vista.getByRole("region", { name: /Página 1 de/ })).toContainText("CONFIRMA");
  await capturar(page, "13-fallo-confirmar");

  const fallo = await descargar(page, page.getByRole("link", { name: "Descargar fallo" }), "confirmar");
  const texto = normalizar(parrafosDocx(fallo.ruta).join(" "));
  expect(texto).toContain("CONFIRMAR");
  expect(texto).not.toContain("REVOCAR");
  expect(id).toBe("caso-b-confirma");
});
