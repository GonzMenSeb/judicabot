import {
  capturar,
  contenidoZip,
  crearCaso,
  descargar,
  espiarEventos,
  expect,
  idDeCaso,
  iniciarRedaccion,
  leerEventos,
  normalizar,
  parrafosDocx,
  test,
} from "../apoyo";

const NOMBRE = "Caso A amparo";
const comparable = (texto: string) => normalizar(texto);
const MARCAS_DE_CITA = / \((?:cita con alerta|cita sin verificar)\)/g;
const ROLES: Record<string, string> = {
  "001.pdf": "acta_reparto_1a",
  "002.pdf": "escrito_tutela",
  "003.pdf": "auto_admisorio",
  "004.pdf": "contestacion",
  "005.pdf": "fallo_a_quo",
  "006.pdf": "impugnacion",
  "007.pdf": "auto_concede_impugnacion",
  "008.pdf": "notificacion",
  "009.pdf": "acta_reparto_2a",
};

test.describe.configure({ mode: "serial" });

let id = "";
const ruta = (etapa: string) => `/#/segunda/${id}/${etapa}`;

test("crear el caso con la carpeta sintética aparece en la lista", async ({ page, request }) => {
  await crearCaso(page, NOMBRE);
  id = await idDeCaso(request, NOMBRE);
  await expect(page.getByRole("heading", { name: NOMBRE, level: 1 })).toBeVisible();
  await page.goto("/#/segunda");
  const ficha = page.getByRole("article").filter({ hasText: NOMBRE });
  await expect(ficha).toBeVisible();
  await expect(ficha.getByRole("link", { name: new RegExp(NOMBRE) })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Buscar casos" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Buscar casos" }).fill("zzz-no-existe");
  await expect(page.getByText(/Ningún caso coincide/).first()).toBeVisible();
  await page.getByRole("searchbox", { name: "Buscar casos" }).fill(NOMBRE.toLowerCase());
  await expect(ficha).toBeVisible();
  await capturar(page, "04-casos-lista");
});

test("documentos: roles, reglas del código, sin faltantes y evidencia", async ({ page }) => {
  await page.goto(ruta("documentos"));
  await expect(page.getByRole("heading", { name: NOMBRE, level: 1 })).toBeVisible();
  await expect(page.getByText("Radicado 05001408800920260041201")).toBeVisible();
  await expect(page.getByText("Están las piezas obligatorias")).toBeVisible();
  await expect(page.getByText("Faltan piezas obligatorias")).toHaveCount(0);
  for (const [archivo, rol] of Object.entries(ROLES)) {
    await expect(page.getByRole("combobox", { name: `Rol de ${archivo}` })).toHaveValue(rol);
  }
  await expect(page.getByText("Reglas del código")).toHaveCount(9);
  await expect(page.getByText(/Jev (propone|\d)/)).toHaveCount(0);
  const evidencia = page.getByRole("button", { name: "Evidencia de 002.pdf" });
  await evidencia.click();
  await expect(evidencia).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#ev-1a-002 q")).not.toBeEmpty();
  await expect(page.getByRole("link", { name: /Descargar Auto que asume el conocimiento/ })).toBeVisible();
  await capturar(page, "05-documentos");
});

test("documentos: editar un dato del auto y guardar", async ({ page }) => {
  await page.goto(ruta("documentos"));
  const fecha = page.getByRole("textbox", { name: "Fecha del auto" });
  await expect(fecha).toHaveValue("2026-10-08");
  await expect(page.getByRole("button", { name: "Guardar cambios" })).toHaveCount(0);
  await fecha.fill("2026-10-09");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByText("Cambios guardados.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Fecha del auto" })).toHaveValue("2026-10-09");
});

test("documentos: cambiar un rol deja faltantes, bloquea el inicio y se puede revertir", async ({ page }) => {
  await page.goto(ruta("documentos"));
  const rol = page.getByRole("combobox", { name: "Rol de 005.pdf" });
  await rol.selectOption("otro");
  await expect(page.getByText(/roles? cambiados?/)).toBeVisible();
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByText("Cambios guardados.")).toBeVisible();
  await expect(page.getByText("Faltan piezas obligatorias")).toBeVisible();
  await expect(page.getByText("Falta: Fallo de primera instancia")).toBeAttached();
  await expect(page.getByRole("button", { name: "Iniciar redacción" })).toBeDisabled();
  await expect(page.getByText("Asignado por usted")).toBeVisible();
  await capturar(page, "05b-documentos-faltantes");
  await rol.selectOption("fallo_a_quo");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByText("Están las piezas obligatorias")).toBeVisible();
  await expect(page.getByRole("button", { name: "Iniciar redacción" })).toBeEnabled();
});

test("iniciar redacción: pide la clave, se puede cancelar y luego continuar al proceso con eventos en vivo", async ({ page }) => {
  await espiarEventos(page);
  await page.goto(ruta("documentos"));
  await page.getByRole("button", { name: "Iniciar redacción" }).click();
  const clave = page.getByRole("textbox", { name: "Clave de la API" });
  await expect(clave).toBeVisible();
  await page.getByRole("button", { name: "Cancelar" }).click();
  await expect(clave).toBeHidden();
  await expect(page).toHaveURL(/\/documentos$/);
  const evento = page.waitForResponse((r) => /\/api\/jobs\/[^/]+\/eventos/.test(r.url()));
  await iniciarRedaccion(page);
  const respuesta = await evento;
  expect(respuesta.status()).toBe(200);
  expect(respuesta.headers()["content-type"]).toContain("text/event-stream");
  await expect(page.getByRole("heading", { name: NOMBRE, level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Ver el borrador" })).toBeVisible();
  await expect(page.getByText("Ejecución terminada")).toBeVisible();
  await expect(page.getByRole("button", { name: /Apertura \(completada\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Consideraciones \(completada\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Verificación de citas \(completada\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Caso concreto \(pendiente\)/ })).toBeVisible();
  const sse = await leerEventos(page);
  expect(sse?.abiertas.some((u) => u.includes("/eventos"))).toBeTruthy();
  expect(sse?.eventos).toBeGreaterThanOrEqual(10);
  expect(sse?.fin).toContain("terminado");
  await expect(page.getByText(/Cita c1 \(T-200\/22\)/)).toBeVisible();
  await capturar(page, "06-proceso");
});

test("borrador: bloques, citas clicables, índice y sin tarjeta de Jev", async ({ page }) => {
  await page.goto(ruta("proceso"));
  await page.getByRole("link", { name: "Ver el borrador" }).click();
  await expect(page).toHaveURL(/\/borrador$/);
  const texto = page.getByRole("article", { name: /Borrador del fallo/ });
  await expect(texto).toBeVisible();
  await expect(texto.getByText("Borrador, aún no es el fallo")).toBeVisible();
  for (const titulo of ["I. ASUNTO", "II. ANTECEDENTES DEL CASO", "III. LA SENTENCIA IMPUGNADA", "IV. LA IMPUGNACIÓN", "V. CONSIDERACIONES"]) {
    await expect(texto.getByRole("heading", { name: titulo })).toBeVisible();
  }
  await expect(texto.getByRole("heading", { name: "INFORME DE CITAS" })).toBeVisible();
  await expect(page.getByText("Jev", { exact: true })).toHaveCount(0);

  const cita = texto.getByRole("button", { name: /Sentencia T-200 de 2022.*Con alerta/ });
  await expect(cita).toBeVisible();
  await cita.click();
  await expect(cita).toHaveAttribute("aria-pressed", "true");
  const detalle = page.locator("#bor-detalle");
  await expect(detalle).toBeVisible();
  await expect(detalle).toContainText("T-200");
  await expect(detalle).toContainText("Cobertura");
  await page.keyboard.press("Escape");
  await expect(detalle).toBeHidden();
  await expect(cita).toHaveAttribute("aria-pressed", "false");

  const indice = page.getByRole("region", { name: "Secciones" });
  await indice.getByRole("button", { name: "El término razonable de conservación del dato negativo" }).click();
  await expect(texto.getByRole("heading", { name: "El término razonable de conservación del dato negativo" })).toBeInViewport();

  await page.getByRole("region", { name: "Qué conviene revisar" }).getByRole("button", { name: "Ver en el texto" }).first().click();
  await page.getByRole("checkbox", { name: "Marcar el texto que sale de plantillas" }).check();
  await page.getByRole("checkbox", { name: "Marcar el texto que sale de plantillas" }).uncheck();
  await capturar(page, "07-borrador");
  await page.getByRole("link", { name: "Pasar a la decisión" }).click();
  await expect(page).toHaveURL(/\/decision$/);
});

test("decisión AMPARAR: validaciones, vista previa del RESUELVE y envío", async ({ page }) => {
  await page.goto(ruta("decision"));
  const enviar = page.getByRole("button", { name: "Enviar decisión y redactar" });
  await expect(page.getByRole("status").filter({ hasText: "Para enviar falta" })).toContainText("el resultado");
  await expect(page.getByText("Elija qué decide y esta parte del fallo se arma aquí")).toBeVisible();

  await enviar.click();
  const resumen = page.getByText("Revise la decisión antes de enviarla");
  await expect(resumen).toBeVisible();
  await expect(page.getByText(/Indique|Elija|obligatorio|falta/i).first()).toBeVisible();
  await capturar(page, "08-decision-validacion");

  await page.getByText("Revocar", { exact: true }).click();
  await expect(page.getByRole("radiogroup", { name: "En su lugar, el Despacho" })).toBeVisible();
  await page.locator("label.dec-opcion", { hasText: "Amparar" }).click();
  await expect(page.getByRole("button", { name: "Agregar orden" })).toBeVisible();

  const resuelve = page.getByRole("complementary", { name: "Vista previa del RESUELVE" });
  await expect(resuelve.getByRole("list", { name: "Numerales del RESUELVE" })).toBeVisible();
  await expect(resuelve).toContainText("REVOCAR");
  await expect(resuelve).toContainText("Falta:");

  await page.getByRole("textbox", { name: "Por qué, en pocas líneas" }).fill(
    "Se revoca porque la falta de pago de las incapacidades compromete el mínimo vital de la accionante y de su hijo menor.",
  );
  const orden = page.getByRole("group", { name: "Orden 1" });
  await expect(orden).toBeVisible();
  await orden.getByLabel("Destinatario").fill("la EPS HORIZONTE SALUD S.A.S.");
  await orden.getByLabel("Plazo", { exact: true }).fill("48");
  await orden.getByLabel("Qué debe hacer").fill("resuelva de fondo y pague las incapacidades médicas pendientes");
  await expect(resuelve).toContainText("EPS HORIZONTE SALUD S.A.S.");
  await expect(resuelve).toContainText("cuarenta y ocho (48)");
  await expect(resuelve).not.toContainText("Falta: Destinatario");

  await page.getByRole("button", { name: "Agregar orden" }).click();
  const segunda = page.getByRole("group", { name: "Orden 2" });
  await expect(segunda).toBeVisible();
  await enviar.click();
  await expect(page.locator("#dec-resumen-errores")).toContainText("Cada orden necesita destinatario y conducta.");
  await expect(segunda.getByLabel("Destinatario")).toHaveAttribute("aria-invalid", "true");
  await segunda.getByRole("button", { name: "Quitar orden" }).click();
  await expect(segunda).toBeHidden();

  await page.getByRole("checkbox", { name: /Compulsar copias/ }).check();
  await enviar.click();
  await expect(page.getByText(/Respecto de quién|compulsa/i).first()).toBeVisible();
  await page.getByRole("checkbox", { name: /Compulsar copias/ }).uncheck();

  await page.getByRole("button", { name: "Agregar un numeral de texto libre" }).click();
  await page.getByRole("textbox", { name: "Numeral libre 1" }).fill("Por Secretaría, líbrense las comunicaciones del caso.");
  await expect(resuelve).toContainText("Por Secretaría, líbrense las comunicaciones del caso.");
  await page.getByRole("button", { name: "Quitar el numeral libre 1" }).click();
  await expect(resuelve).not.toContainText("Por Secretaría, líbrense");

  await capturar(page, "09-decision-completa");
  await enviar.click();
  const dialogo = page.getByRole("dialog", { name: "¿Enviar la decisión?" });
  await expect(dialogo).toBeVisible();
  await expect(dialogo).toContainText("Resultado: REVOCAR");
  await dialogo.getByRole("button", { name: "Revisar" }).click();
  await expect(dialogo).toBeHidden();
  await enviar.click();
  await dialogo.getByRole("button", { name: "Enviar decisión" }).click();
  await expect(page).toHaveURL(/\/proceso$/);
  await expect(page.getByRole("link", { name: "Ver el fallo" })).toBeVisible();
  await expect(page.getByText("Ejecución terminada")).toBeVisible();
  await expect(page.getByRole("button", { name: /Documentos \(completada\)/ })).toBeVisible();
  await capturar(page, "10-proceso-final");
});

test("fallo: visor de páginas, descargas y contenido del docx y del zip", async ({ page }) => {
  await page.goto(ruta("proceso"));
  await page.getByRole("link", { name: "Ver el fallo" }).click();
  await expect(page).toHaveURL(/\/fallo$/);
  const vista = page.getByRole("region", { name: "Vista previa del fallo" });
  await expect(vista).toBeVisible();
  const total = Number((await vista.getByRole("status").textContent())?.match(/de (\d+)/)?.[1]);
  expect(total).toBeGreaterThan(1);
  await expect(vista.getByRole("button", { name: "Página anterior" })).toBeDisabled();
  await vista.getByRole("button", { name: "Página siguiente" }).click();
  await expect(vista.getByRole("status")).toContainText(`Página 2 de ${total}`);
  await vista.getByRole("button", { name: `Ir a la página ${total}` }).click();
  await expect(vista.getByRole("button", { name: "Página siguiente" })).toBeDisabled();
  await vista.getByRole("button", { name: "Ir a la página 1" }).click();
  await expect(vista.getByRole("status")).toContainText(`Página 1 de ${total}`);

  const paginas: string[] = [];
  for (let n = 1; n <= total; n++) {
    await vista.getByRole("button", { name: `Ir a la página ${n}` }).click();
    const pagina = vista.getByRole("region", { name: `Página ${n} de ${total}` });
    await expect.poll(async () => (await pagina.innerText()).trim().length, { message: `texto de la página ${n}` }).toBeGreaterThan(40);
    paginas.push((await pagina.evaluate((el) => el.textContent ?? "")).replace(MARCAS_DE_CITA, ""));
  }
  const visor = comparable(paginas.join("\n"));
  expect(visor.length, paginas.map((x) => x.length).join(",")).toBeGreaterThan(2000);
  await vista.getByRole("button", { name: "Ir a la página 1" }).click();
  expect(visor).toContain("RESUELVE");
  expect(visor).toContain("REVOCAR");
  expect(visor).toContain("NOTIFÍQUESE Y CÚMPLASE");
  await capturar(page, "11-fallo");

  const fallo = await descargar(page, page.getByRole("link", { name: "Descargar fallo" }), "fallo");
  expect(fallo.nombre).toMatch(/^003FalloSegunda\d+\.docx$/);
  const parrafos = parrafosDocx(fallo.ruta);
  expect(parrafos.length).toBeGreaterThan(20);
  const ausentes = parrafos.map(comparable).filter((p) => p.length > 25 && !visor.includes(p));
  expect(ausentes, "párrafos del .docx que no aparecen en el visor").toEqual([]);
  expect(parrafos.join("\n")).toContain("SANTIAGO ALEJANDRO CADAVID DUQUE");

  const zip = await descargar(page, page.getByRole("link", { name: "Descargar todo (.zip)" }), "zip");
  expect(zip.nombre).toMatch(/\.zip$/);
  const contenido = contenidoZip(zip.ruta);
  expect(contenido.malo).toBeNull();
  const nombres = contenido.nombres.join("\n");
  for (const esperado of ["003FalloSegunda", "002AutoAsumeSegunda", "004FormatoCalificacion", "OficioRemiteCorteConstitucional", "NotificacionFalloPartes", "declaracion_ia"]) {
    expect(nombres, esperado).toContain(esperado);
  }

  const auto = await descargar(page, page.getByRole("link", { name: /Descargar Auto que asume el conocimiento/ }), "auto");
  expect(parrafosDocx(auto.ruta).length).toBeGreaterThan(5);
  await expect(page.getByRole("region", { name: "Antes de firmar" })).toBeVisible();
});

test("la lista de casos y el inicio reflejan el caso terminado", async ({ page }) => {
  await page.goto("/#/segunda");
  const ficha = page.getByRole("article").filter({ hasText: NOMBRE });
  await expect(page.getByRole("heading", { name: /Terminados/ })).toBeVisible();
  await expect(ficha.getByRole("link", { name: /Ver fallo/ })).toHaveAttribute("href", `#/segunda/${id}/fallo`);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Elige el proceso a realizar" })).toBeVisible();
});
