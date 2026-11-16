import type { Page } from "@playwright/test";
import { capturar, expect, test } from "../apoyo";

async function agregarClave(page: Page, seccion: string, etiqueta: string, valor: string): Promise<void> {
  await page.getByRole("region", { name: seccion }).getByRole("button", { name: "Agregar clave" }).click();
  const dialogo = page.getByRole("dialog");
  await dialogo.getByLabel(etiqueta).fill(valor);
  await dialogo.getByRole("button", { name: "Guardar clave" }).click();
  await expect(page.getByRole("region", { name: seccion }).getByText("Hay una clave lista.")).toBeVisible();
}

test("ia: cambiar modelo, modo de Jev y avanzadas persiste tras recargar", async ({ page, request }) => {
  await page.goto("/#/ia");
  await expect(page.getByRole("heading", { name: "Inteligencia artificial", level: 1 })).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Anthropic/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Apagado/ })).toBeChecked();
  const { api_key: conClave } = (await (await request.get("/api/ia")).json()) as { api_key: boolean };
  if (!conClave) {
    await expect(page.getByText("Falta la clave de Anthropic")).toBeVisible();
    await expect(page.getByRole("radio", { name: /^Sonnet 5.5/ })).toHaveCount(0);
    await agregarClave(page, "Anthropic", "Clave de la API de Anthropic", "sk-ant-e2e-sin-uso");
  }
  await expect(page.getByText("Falta la clave de Anthropic")).toHaveCount(0);
  await expect(page.getByRole("radio", { name: /^Sonnet 5.5/ })).toBeChecked();
  await capturar(page, "17-ia");

  await page.locator("label", { hasText: "Opus 5.5" }).click();
  await page.locator("label", { hasText: "Sombra" }).click();
  await page.getByRole("combobox", { name: "Esfuerzo de razonamiento" }).selectOption("medium");
  await page.getByText("Opciones avanzadas").click();
  const tokens = page.getByRole("spinbutton", { name: "Máximo de tokens de salida" });
  await tokens.fill("0");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(tokens).toHaveAttribute("aria-invalid", "true");
  await tokens.fill("32000");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(tokens).not.toHaveAttribute("aria-invalid", "true");

  await expect
    .poll(async () => ((await (await request.get("/api/ia")).json()) as { modelo: string; jev: { modo: string }; effort: string; max_tokens: number }))
    .toMatchObject({ proveedor: "anthropic", modelo: "claude-opus-5-5", jev: { modo: "sombra" }, effort: "medium", max_tokens: 32000 });

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Opus 5.5/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Sombra/ })).toBeChecked();
  await expect(page.getByRole("combobox", { name: "Esfuerzo de razonamiento" })).toHaveValue("medium");
  await page.getByText("Opciones avanzadas").click();
  await expect(page.getByRole("spinbutton", { name: "Máximo de tokens de salida" })).toHaveValue("32000");
  await expect(page.getByRole("link", { name: /Opus 5.5/ })).toBeVisible();
  await capturar(page, "18-ia-guardada");

  await page.locator("label", { hasText: "Sonnet 5.5" }).click();
  await page.locator("label", { hasText: "Apagado" }).click();
  await page.getByRole("combobox", { name: "Esfuerzo de razonamiento" }).selectOption("high");
  await page.getByRole("spinbutton", { name: "Máximo de tokens de salida" }).fill("64000");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect
    .poll(async () => ((await (await request.get("/api/ia")).json()) as { modelo: string; jev: { modo: string } }))
    .toMatchObject({ modelo: "claude-sonnet-5-5", jev: { modo: "apagado" } });
});

test("ia: con la clave de Gemini aparecen sus modelos y sus niveles, y se puede activar", async ({ page, request }) => {
  await page.goto("/#/ia");
  const gemini = page.getByRole("region", { name: "Gemini (Google)" });
  await expect(gemini.getByText("Con una clave gratuita, Google puede usar lo que se envía")).toBeVisible();
  await expect(gemini.getByRole("radio")).toHaveCount(0);

  await page.locator("label", { hasText: "Gemini (Google)" }).click();
  await expect(page.getByText("Falta la clave de Gemini (Google)")).toBeVisible();
  await capturar(page, "19-ia-gemini-sin-clave");

  await agregarClave(page, "Gemini (Google)", "Clave de la API de Gemini", "AIza-e2e-sin-uso");
  await expect(page.getByText("Falta la clave de Gemini (Google)")).toHaveCount(0);
  await expect(page.getByRole("radio", { name: /^Gemini 4 Argon/ })).toBeChecked();
  const nivel = gemini.getByRole("combobox", { name: "Nivel de razonamiento" });
  await expect(nivel.locator("option")).toHaveText(["Bajo (low)", "Medio (medium)", "Alto (high)"]);
  await page.locator("label", { hasText: "Gemini 4 Hydrogen" }).click();
  await expect(nivel.locator("option")).toHaveText(["Bajo (low)", "Medio (medium)", "Alto (high)", "Muy alto (xhigh)"]);
  await nivel.selectOption("xhigh");
  await page.getByRole("button", { name: "Guardar cambios" }).click();

  await expect
    .poll(async () => (await (await request.get("/api/ia")).json()) as Record<string, unknown>)
    .toMatchObject({ proveedor: "gemini", gemini_key: true, gemini: { modelo: "gemini-4-hydrogen", razonamiento: "xhigh" }, modelo: "claude-sonnet-5-5" });
  const servidor = (await (await request.get("/api/estado-servidor")).json()) as Record<string, unknown>;
  expect(servidor).toMatchObject({ proveedor: "gemini", gemini_key: true, modelo: "gemini-4-hydrogen" });
  expect(JSON.stringify(servidor)).not.toContain("AIza");

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Gemini \(Google\)/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Gemini 4 Hydrogen/ })).toBeChecked();
  await expect(nivel).toHaveValue("xhigh");
  await expect(page.getByRole("link", { name: /Gemini 4 Hydrogen/ })).toBeVisible();
  await capturar(page, "19b-ia-gemini");

  await page.locator("label", { hasText: "Anthropic" }).first().click();
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect
    .poll(async () => ((await (await request.get("/api/ia")).json()) as { proveedor: string }).proveedor)
    .toBe("anthropic");
});
