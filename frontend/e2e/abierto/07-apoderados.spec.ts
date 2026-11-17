import type { Locator, Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { capturar, crearCaso, decisionSintetica, expect, idDeCaso, iniciarRedaccion, test } from "../apoyo";

const NOMBRE = "Caso G apoderados";
const ABOGADA = "ANDREA PAOLA GIRALDO MONTOYA";
// Certificados sintéticos de la abogada ficticia de scripts/caso_sintetico.py (ver su LEEME.md).
const CERTIFICADOS = resolve(import.meta.dirname, "../../../backend/tests/fixtures/vigencia");

async function subirCertificado(page: Page, fila: Locator, archivo: string): Promise<void> {
  const [selector] = await Promise.all([page.waitForEvent("filechooser"), fila.getByRole("button", { name: "o elija un archivo" }).click()]);
  await selector.setFiles(join(CERTIFICADOS, archivo));
}

test("apoderados: la consulta simulada la deja en verde, las correcciones a mano la cambian y un certificado no vigente bloquea la decisión hasta revisarlo", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await crearCaso(page, NOMBRE);
  const id = await idDeCaso(request, NOMBRE);
  await iniciarRedaccion(page);
  await page.getByRole("link", { name: "Ver el borrador" }).click();
  await expect(page).toHaveURL(/\/borrador$/);

  const texto = page.getByRole("article", { name: /Borrador del fallo/ });
  const panel = page.getByRole("complementary", { name: "Antes de decidir" });
  const abogada = texto.getByRole("button", { name: /Andrea Paola Giraldo Montoya/ });
  const pasar = page.locator(".bor-dock a", { hasText: "Pasar a la decisión" });
  const fila = panel.locator("li.bor-fila", { hasText: ABOGADA });
  const abrirFila = async () => {
    await panel.getByRole("tab", { name: /^Apoderados/ }).click();
    await panel.getByRole("button", { name: new RegExp(ABOGADA), expanded: false }).click();
  };

  // Con el proveedor de prueba la vigencia se consulta sola (consulta simulada): sin subir nada, la abogada queda en verde.
  await expect(abogada).toHaveClass(/\bverificada\b/, { timeout: 30_000 });
  await expect(pasar).toHaveAttribute("href", /\/decision$/);
  await abrirFila();
  await expect(panel.getByRole("region", { name: "Verificados" })).toContainText(ABOGADA);
  const verPoder = fila.getByRole("button", { name: /^Poder · p\. \d+$/ });
  const paginaPoder = Number((await verPoder.textContent())?.match(/p\. (\d+)/)?.[1]);
  expect(paginaPoder).toBeGreaterThan(0);

  // «No es correcto…»: se confirma, el poder deja de contar y la abogada queda por revisar.
  await fila.getByRole("button", { name: "No es correcto…" }).click();
  const confirmar = page.getByRole("dialog", { name: "¿El poder no es correcto?" });
  await expect(confirmar).toContainText(`el poder del Doc. 1a-004, p. ${paginaPoder},`);
  await confirmar.getByLabel("Por qué no es correcto (opcional)").fill("Prueba de la corrección a mano.");
  await capturar(page, "14a-apoderado-no-es-correcto");
  await confirmar.getByRole("button", { name: "Descartar el poder" }).click();
  await expect(confirmar).toBeHidden();
  await expect(abogada).toHaveClass(/\brevisar\b/);
  await expect(panel.getByRole("region", { name: "Por revisar" })).toContainText(ABOGADA);
  await expect(fila).toContainText("Poder descartado");
  await expect(pasar).toHaveAttribute("href", /\/decision$/);

  // «Señalar el poder a mano…» en la página del poder: el servidor comprueba que la nombra y vuelve a verde.
  await fila.getByRole("button", { name: "Señalar el poder a mano…" }).click();
  const senalar = page.getByRole("dialog", { name: "Señalar el poder a mano" });
  await senalar.getByLabel("Documento del expediente").selectOption("1a-004");
  await senalar.getByLabel("Página").fill(String(paginaPoder));
  await capturar(page, "14b-apoderado-poder-a-mano");
  await senalar.getByRole("button", { name: "Señalar el poder" }).click();
  await expect(senalar).toBeHidden();
  await expect(abogada).toHaveClass(/\bverificada\b/);
  await expect(panel.getByRole("region", { name: "Verificados" })).toContainText(ABOGADA);
  await expect(fila).toContainText("Poder señalado a mano");
  await expect(fila.getByRole("button", { name: `Poder · p. ${paginaPoder}` })).toBeVisible();

  // Llega un certificado más reciente con la tarjeta suspendida (se sube por la API: a una abogada en verde el
  // borrador no le ofrece subir otro). Queda en rojo y la decisión se bloquea, en la pantalla y en el servidor.
  const lista = (await (await request.get(`/api/casos/${id}/apoderados`)).json()) as { apoderados: { id: string; nombre: string }[] };
  const apId = lista.apoderados.find((a) => a.nombre === ABOGADA)?.id ?? "";
  const subida = await request.put(`/api/casos/${id}/apoderados/${apId}/certificado`, {
    multipart: { archivo: { name: "certificado.pdf", mimeType: "application/pdf", buffer: readFileSync(join(CERTIFICADOS, "e2e_no_vigente.pdf")) } },
  });
  expect(subida.status()).toBe(200);
  await page.reload();
  await expect(abogada).toHaveClass(/\brechazada\b/);
  await abrirFila();
  await expect(panel.getByRole("region", { name: "No verificados" })).toContainText(ABOGADA);
  await expect(panel.getByRole("alert")).toContainText("Un apoderado no pudo verificarse.");
  await expect(pasar).toHaveAttribute("aria-disabled", "true");
  await expect(pasar).not.toHaveAttribute("href");
  await expect(page.getByText(`${ABOGADA} no pudo verificarse. Márquelo como revisado`)).toBeVisible();
  await expect(fila.getByRole("link", { name: /Certificado PDF/ })).toBeVisible();
  await expect(fila.getByRole("group", { name: `Subir el certificado de vigencia de ${ABOGADA}` })).toBeVisible();
  await capturar(page, "14-apoderados-ayuda", panel);
  const bloqueada = await request.post(`/api/casos/${id}/run`, { data: { cmd: "decidir", decision: decisionSintetica() } });
  expect(bloqueada.status()).toBe(409);

  // La fila abierta de la abogada es más alta que el panel: llevarla a la vista mueve solo el panel, nunca la
  // ventana, así que «Ver en el texto» deja el nombre a la vista y su detalle no queda bajo la barra inferior.
  const detalle = page.locator("#bor-detalle");
  const sobreLaBarra = () =>
    page.evaluate(() => {
      const caja = document.querySelector("#bor-detalle")?.getBoundingClientRect();
      const barra = document.querySelector(".bor-dock")?.getBoundingClientRect();
      return caja && barra ? caja.bottom <= barra.top + 1 : null;
    });
  await fila.getByRole("button", { name: "Ver en el texto" }).click();
  await expect(detalle).toBeVisible();
  await expect(abogada).toBeInViewport();
  await expect.poll(sobreLaBarra).toBe(true);
  await page.keyboard.press("Escape");
  await expect(detalle).toBeHidden();

  await abogada.click();
  await expect(detalle.getByText("No vigente", { exact: true })).toBeVisible();
  await expect(abogada).toBeInViewport();
  await expect.poll(sobreLaBarra).toBe(true);
  await expect(detalle.getByRole("link", { name: /Consultar sanciones \(CNDJ\)/ })).toBeVisible();
  const certificado = detalle.getByRole("link", { name: /Ver certificado \(PDF\)/ });
  const url = await certificado.getAttribute("href");
  expect(url).toMatch(new RegExp(`^/api/casos/${id}/apoderados/ap-[0-9a-f]{10}/certificado$`));
  const pdf = await request.get(url ?? "");
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString("latin1")).toBe("%PDF-");
  await capturar(page, "15-apoderado-no-vigente");
  await page.keyboard.press("Escape");
  await expect(detalle).toBeHidden();

  // Revisarla desbloquea la decisión.
  const revisado = panel.getByRole("button", { name: `Revisado: ${ABOGADA}` });
  await revisado.click();
  await expect(revisado).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("link", { name: "Pasar a la decisión" })).toHaveAttribute("href", /\/decision$/);
  await expect(panel.getByRole("alert")).toHaveCount(0);

  // Un certificado vigente la deja en verde: ya no hace falta la revisión.
  await subirCertificado(page, fila, "e2e_vigente.pdf");
  await expect(abogada).toHaveClass(/\bverificada\b/);
  await expect(panel.getByRole("region", { name: "Verificados" })).toContainText(ABOGADA);
  await expect(panel.getByRole("button", { name: `Revisado: ${ABOGADA}` })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Pasar a la decisión" })).toHaveAttribute("href", /\/decision$/);
  await abogada.click();
  await expect(detalle.getByText("Abogada verificada")).toBeVisible();
  await expect(detalle.getByText("Vigente", { exact: true })).toBeVisible();
  await expect(detalle).toContainText("Certificado subido por el despacho");
  await expect(detalle.getByText("Poder señalado a mano", { exact: true })).toBeVisible();
  await capturar(page, "16-apoderada-verificada");
});
