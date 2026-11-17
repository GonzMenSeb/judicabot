import type { Page } from "@playwright/test";
import type { EdicionesRespuesta } from "../../src/api/contrato";
import { crearCaso, descargar, expect, idDeCaso, iniciarRedaccion, normalizar, parrafosDocx, test } from "../apoyo";

const NOMBRE = "Caso C edición";
const PIEZA = "apertura.antecedentes_hechos";
const PARRAFO = 1;
const FRASE = "El despacho corrigió a mano este párrafo de los antecedentes durante la prueba e2e de la edición in situ.";
const MARCAS_DE_CITA = / \((?:cita con alerta|cita sin verificar|se abre en una pestaña nueva)\)/g;
const FICHA = /⟦[^⟧]*⟧/g;

async function ediciones(page: Page, id: string): Promise<EdicionesRespuesta> {
  const respuesta = await page.request.get(`/api/casos/${id}/ediciones`);
  expect(respuesta.status()).toBe(200);
  return (await respuesta.json()) as EdicionesRespuesta;
}

async function textoDelVisor(page: Page): Promise<string> {
  const vista = page.getByRole("region", { name: "Vista previa del fallo" });
  await expect(vista).toBeVisible();
  const total = Number((await vista.getByRole("status").textContent())?.match(/de (\d+)/)?.[1]);
  expect(total).toBeGreaterThan(1);
  const paginas: string[] = [];
  for (let n = 1; n <= total; n++) {
    await vista.getByRole("button", { name: `Ir a la página ${n}` }).click();
    const pagina = vista.getByRole("region", { name: `Página ${n} de ${total}` });
    await expect.poll(async () => (await pagina.innerText()).trim().length, { message: `texto de la página ${n}` }).toBeGreaterThan(40);
    paginas.push((await pagina.evaluate((el) => el.textContent ?? "")).replace(MARCAS_DE_CITA, ""));
  }
  return normalizar(paginas.join("\n"));
}

test("edición in situ: se corrige un párrafo del borrador, persiste y llega al fallo y a la declaración", async ({ page, request }) => {
  test.setTimeout(180_000);
  await crearCaso(page, NOMBRE);
  const id = await idDeCaso(request, NOMBRE);
  await iniciarRedaccion(page);
  await expect(page.getByText("Ejecución terminada")).toBeVisible();
  await expect.poll(async () => (await ediciones(page, id)).editable, { message: "el caso espera la decisión" }).toBe(true);

  const inicial = (await ediciones(page, id)).piezas[PIEZA];
  expect(inicial?.parrafos.length).toBeGreaterThan(PARRAFO);
  expect(inicial?.editados).toEqual([]);
  const original = inicial?.parrafos[PARRAFO] ?? "";
  expect(original).not.toBe(FRASE);

  await page.getByRole("link", { name: "Ver el borrador" }).click();
  await expect(page).toHaveURL(/\/borrador$/);
  const texto = page.getByRole("article", { name: /Borrador del fallo/ });
  await expect(texto).toBeVisible();
  const interruptor = page.getByRole("switch", { name: "Editar texto" });
  await expect(interruptor).toBeVisible();
  await expect(interruptor).not.toBeChecked();
  await expect(texto.getByRole("button", { name: "Editar párrafo" })).toHaveCount(0);
  await expect(texto.getByText("Editado", { exact: true })).toHaveCount(0);

  await interruptor.check();
  await expect(interruptor).toBeChecked();
  await expect(texto.getByRole("button", { name: "Editar párrafo" }).first()).toBeVisible();
  const unidad = texto.locator(`[data-unidad="${PIEZA}#${PARRAFO}"]`);
  await expect(unidad).toContainText(original);
  const antes = await texto.getByRole("heading", { name: "II. ANTECEDENTES DEL CASO" }).elementHandle();
  const despues = await texto.getByRole("heading", { name: "III. LA SENTENCIA IMPUGNADA" }).elementHandle();
  expect(antes).not.toBeNull();
  expect(despues).not.toBeNull();
  const enAntecedentes = await unidad.evaluate(
    (el, [desde, hasta]) =>
      Boolean(desde && hasta) &&
      Boolean(desde!.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      Boolean(el.compareDocumentPosition(hasta!) & Node.DOCUMENT_POSITION_FOLLOWING),
    [antes, despues],
  );
  expect(enAntecedentes, "el párrafo editado está entre los títulos II y III").toBe(true);

  await unidad.getByRole("button", { name: "Editar párrafo" }).click();
  const campo = unidad.getByRole("textbox", { name: "Texto del párrafo" });
  await expect(campo).toBeFocused();
  const entregado = await campo.inputValue();
  expect(entregado).toBe(original);
  const fichas = entregado.match(FICHA) ?? [];
  await campo.fill([FRASE, ...fichas].join(" "));
  await campo.press("Control+Enter");
  await expect(campo).toBeHidden();

  const editada = texto.locator("[data-unidad]").filter({ hasText: FRASE });
  await expect(editada).toHaveCount(1);
  await expect(editada.getByText("Editado", { exact: true })).toBeVisible();
  await expect(texto.getByText("Editado", { exact: true })).toHaveCount(1);
  await expect(texto).not.toContainText(original);

  const guardada = await ediciones(page, id);
  expect(guardada.editable).toBe(true);
  expect(guardada.conflictos).toEqual([]);
  expect(guardada.piezas[PIEZA]?.editados).toEqual([PARRAFO]);
  expect(guardada.piezas[PIEZA]?.parrafos[PARRAFO]).toBe([FRASE, ...fichas].join(" "));
  expect(guardada.piezas[PIEZA]?.parrafos[0]).toBe(inicial?.parrafos[0]);

  await page.reload();
  await expect(texto).toBeVisible();
  await expect(interruptor).toBeVisible();
  await expect(interruptor).not.toBeChecked();
  const persistida = texto.locator("[data-unidad]").filter({ hasText: FRASE });
  await expect(persistida).toBeVisible();
  await expect(persistida.getByText("Editado", { exact: true })).toBeVisible();
  await expect(texto).not.toContainText(original);
  await expect(texto.getByRole("button", { name: "Editar párrafo" })).toHaveCount(0);
  expect((await ediciones(page, id)).piezas[PIEZA]?.editados).toEqual([PARRAFO]);

  await page.getByRole("link", { name: "Pasar a la decisión" }).click();
  await expect(page).toHaveURL(/\/decision$/);
  await expect(page.getByRole("complementary", { name: "Vista previa del RESUELVE" })).toBeVisible();
  await page.getByText("Confirmar", { exact: true }).click();
  await expect(page.getByRole("radio", { name: "Confirmar" })).toBeChecked();
  await page.getByRole("textbox", { name: "Por qué, en pocas líneas" }).fill("Se confirma la decisión de primera instancia por las razones expuestas en la impugnación.");
  await expect(page.getByRole("status").filter({ hasText: "Listo para enviar" })).toBeVisible();
  await page.getByRole("button", { name: "Enviar decisión y redactar" }).click();
  const dialogo = page.getByRole("dialog", { name: "¿Enviar la decisión?" });
  await expect(dialogo).toBeVisible();
  await dialogo.getByRole("button", { name: "Enviar decisión" }).click();
  await expect(page).toHaveURL(/\/proceso$/);
  await expect(page.getByRole("link", { name: "Ver el fallo" })).toBeVisible();
  await expect(page.getByText("Ejecución terminada")).toBeVisible();

  const cerrada = await ediciones(page, id);
  expect(cerrada.editable).toBe(false);
  expect(cerrada.piezas).toEqual({});

  await page.getByRole("link", { name: "Ver el fallo" }).click();
  await expect(page).toHaveURL(/\/fallo$/);
  const visor = await textoDelVisor(page);
  expect(visor).toContain(normalizar(FRASE));
  expect(visor).not.toContain(normalizar(original));

  const fallo = await descargar(page, page.getByRole("link", { name: "Descargar fallo" }), "edicion-fallo");
  expect(fallo.nombre).toMatch(/^003FalloSegunda\d+\.docx$/);
  const enFallo = parrafosDocx(fallo.ruta).map(normalizar);
  expect(enFallo.some((p) => p.includes(normalizar(FRASE)))).toBe(true);
  expect(enFallo.some((p) => p.includes(normalizar(original)))).toBe(false);

  const declaracion = await descargar(page, page.getByRole("link", { name: "Descargar Declaración de uso de IA" }), "edicion-declaracion");
  const celdas = parrafosDocx(declaracion.ruta).map(normalizar);
  expect(celdas.filter((c) => c === "IA + edición humana")).toHaveLength(1);
  expect(celdas.some((c) => c.includes("Corregido por el despacho en el borrador."))).toBe(true);
});
