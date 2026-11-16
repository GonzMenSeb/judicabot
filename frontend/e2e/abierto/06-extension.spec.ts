import { capturar, contenidoZip, descargar, expect, test } from "../apoyo";

test("extensión: en un teléfono la pestaña de la sección abierta queda a la vista", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/configuracion/extension");
  const pestana = page.getByRole("dialog", { name: "Configuración" }).getByRole("link", { name: "Extensión de la relatoría" });
  await expect(pestana).toHaveAttribute("aria-current", "page");
  await expect(pestana).toBeInViewport({ ratio: 1 });
});

test("extensión: sección propia del panel con la descarga y los pasos de instalación", async ({ page }) => {
  await page.goto("/#/configuracion/extension");
  const panel = page.getByRole("dialog", { name: "Configuración" });
  await expect(panel.getByRole("heading", { name: "Extensión de la relatoría", level: 1 })).toBeVisible();
  const secciones = panel.getByRole("navigation", { name: "Secciones de configuración" });
  await expect(secciones.getByRole("link")).toHaveText([/^Formato de documentos/, /^Inteligencia artificial/, /^Extensión de la relatoría/]);
  await expect(secciones.getByRole("link", { name: "Extensión de la relatoría" })).toHaveAttribute("aria-current", "page");
  await expect(page).toHaveTitle("Extensión de la relatoría · Configuración · Judicabot");

  const pasos = panel.getByRole("list", { name: "Pasos para instalar la extensión" });
  await expect(pasos.getByRole("listitem")).toHaveCount(6);
  await expect(pasos.locator("code", { hasText: /^http/ })).toHaveText(new URL(page.url()).origin);
  await capturar(page, "23-extension");

  const zip = await descargar(page, panel.getByRole("link", { name: "Descargar extensión (.zip)" }), "extension");
  expect(zip.nombre).toMatch(/^judicabot-relatoria-.+\.zip$/);
  const { malo, nombres } = contenidoZip(zip.ruta);
  expect(malo).toBeNull();
  expect(nombres).toContain("judicabot-relatoria/manifest.json");

  await secciones.getByRole("link", { name: /^Inteligencia artificial/ }).click();
  await expect(page).toHaveURL(/#\/configuracion\/ia$/);
  await expect(panel.getByRole("heading", { name: "Proveedor", level: 2 })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Descargar extensión (.zip)" })).toHaveCount(0);
});
