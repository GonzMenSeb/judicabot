import { capturar, expect, test } from "../apoyo";

test("ia: cambiar modelo, modo de Jev y avanzadas persiste tras recargar", async ({ page, request }) => {
  await page.goto("/#/ia");
  await expect(page.getByRole("heading", { name: "Inteligencia artificial", level: 1 })).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Sonnet 5.5/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Apagado/ })).toBeChecked();
  await expect(page.getByRole("region", { name: "Clave de Anthropic" }).getByRole("status")).toBeVisible();
  await capturar(page, "17-ia");

  await page.locator("label", { hasText: "Opus 5.5" }).click();
  await page.locator("label", { hasText: "Sombra" }).click();
  await page.getByText("Opciones avanzadas").click();
  await page.getByRole("combobox", { name: "Esfuerzo de razonamiento" }).selectOption("medium");
  const tokens = page.getByRole("spinbutton", { name: "Máximo de tokens de salida" });
  await tokens.fill("0");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(tokens).toHaveAttribute("aria-invalid", "true");
  await tokens.fill("32000");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(tokens).not.toHaveAttribute("aria-invalid", "true");

  await expect
    .poll(async () => ((await (await request.get("/api/ia")).json()) as { modelo: string; jev: { modo: string }; effort: string; max_tokens: number }))
    .toMatchObject({ modelo: "claude-opus-5-5", jev: { modo: "sombra" }, effort: "medium", max_tokens: 32000 });

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Opus 5.5/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Sombra/ })).toBeChecked();
  await page.getByText("Opciones avanzadas").click();
  await expect(page.getByRole("combobox", { name: "Esfuerzo de razonamiento" })).toHaveValue("medium");
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
