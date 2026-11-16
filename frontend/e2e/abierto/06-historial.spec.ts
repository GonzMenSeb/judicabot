import type { Page } from "@playwright/test";
import { expect, test } from "../apoyo";

const panelDe = (page: Page) => page.getByRole("dialog", { name: "Configuración" });

async function abrirDesdeCasos(page: Page) {
  await page.goto("/");
  await page.goto("/#/segunda");
  await page.getByRole("link", { name: /^Configuración/ }).click();
  await expect(page).toHaveURL(/#\/configuracion\/formato$/);
  await expect(panelDe(page)).toBeVisible();
}

test("historial: cerrar el panel tras cambiar de sección deja Atrás como si no se hubiera abierto", async ({ page }) => {
  await abrirDesdeCasos(page);
  await panelDe(page).getByRole("link", { name: /Inteligencia artificial/ }).click();
  await expect(page).toHaveURL(/#\/configuracion\/ia$/);
  await panelDe(page).getByRole("button", { name: "Cerrar configuración" }).click();
  await expect(panelDe(page)).toBeHidden();
  await expect(page).toHaveURL(/#\/segunda$/);
  await page.goBack();
  await expect(page).not.toHaveURL(/configuracion/);
  await expect(page).not.toHaveURL(/#\/segunda$/);
  await expect(panelDe(page)).toBeHidden();
});

test("historial: con cambios sin guardar, salir sin guardar también retrocede en el historial", async ({ page }) => {
  await abrirDesdeCasos(page);
  await panelDe(page).getByRole("textbox", { name: "Ciudad", exact: true }).fill("Pereira");
  await page.keyboard.press("Escape");
  const guardia = page.getByRole("dialog", { name: "Hay cambios sin guardar" });
  await expect(guardia).toBeVisible();
  await expect(page).toHaveURL(/#\/configuracion\/formato$/);
  await guardia.getByRole("button", { name: "Salir sin guardar" }).click();
  await expect(panelDe(page)).toBeHidden();
  await expect(page).toHaveURL(/#\/segunda$/);
  await expect(guardia).toBeHidden();
  await page.goBack();
  await expect(page).not.toHaveURL(/configuracion/);
  await expect(panelDe(page)).toBeHidden();
});

test("historial: con enlace directo, cerrar reemplaza la entrada y Atrás no reabre el panel", async ({ page }) => {
  await page.goto("/#/configuracion/ia");
  await expect(panelDe(page)).toBeVisible();
  await panelDe(page).getByRole("link", { name: /Formato de documentos/ }).click();
  await expect(page).toHaveURL(/#\/configuracion\/formato$/);
  await panelDe(page).getByRole("button", { name: "Cerrar configuración" }).click();
  await expect(panelDe(page)).toBeHidden();
  await expect(page).toHaveURL(/#\/$/);
  await page.goBack();
  await expect(page).not.toHaveURL(/configuracion/);
  await expect(panelDe(page)).toBeHidden();
});

test("panel: a 390 px el anillo de foco de la pestaña activa cabe en la barra de pestañas", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/configuracion/formato");
  const actual = panelDe(page).locator("nav a[aria-current=page]");
  await expect(actual).toBeFocused();
  const holgura = await actual.evaluate((el) => {
    const nav = el.closest("nav") as HTMLElement;
    const estilo = getComputedStyle(el);
    const anillo = parseFloat(estilo.outlineWidth) + parseFloat(estilo.outlineOffset);
    return el.getBoundingClientRect().top - anillo - nav.getBoundingClientRect().top;
  });
  expect(holgura).toBeGreaterThanOrEqual(0);
});

test("historial: con enlace directo y sin cambiar de sección, cerrar reemplaza la entrada", async ({ page }) => {
  await page.goto("/");
  await page.goto("/#/configuracion/ia");
  await expect(panelDe(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panelDe(page)).toBeHidden();
  await expect(page).toHaveURL(/#\/$/);
  await page.goBack();
  await expect(page).not.toHaveURL(/configuracion/);
});
