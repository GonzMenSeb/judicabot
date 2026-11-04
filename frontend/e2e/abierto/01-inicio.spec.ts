import { capturar, elegirCarpeta, expect, insumos, test } from "../apoyo";

test("inicio: tres procesos inactivos y uno activo", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Elige el proceso a realizar", level: 1 })).toBeVisible();
  for (const nombre of ["Fallo de tutela de primera instancia", "Incidente de desacato", "Penal"]) {
    const grupo = page.getByRole("group", { name: nombre });
    await expect(grupo).toBeVisible();
    await expect(grupo).toBeDisabled();
    await expect(grupo.getByText("Próximamente")).toBeVisible();
  }
  const segunda = page.getByRole("link", { name: "Fallo de tutela de segunda instancia" });
  await expect(segunda).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Para continuar" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Formato de documentos" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Inteligencia artificial/ })).toBeVisible();
  await capturar(page, "01-inicio");
  await segunda.click();
  await expect(page).toHaveURL(/#\/segunda$/);
  await expect(page.getByRole("heading", { name: "Fallos de tutela de segunda instancia", level: 1 })).toBeVisible();
});

test("casos: lista vacía y selección de carpeta", async ({ page }) => {
  await page.goto("/#/segunda");
  await expect(page.getByText("Aún no hay casos")).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Buscar casos" })).toHaveCount(0);
  await capturar(page, "02-casos-vacio");
  await elegirCarpeta(page, insumos());
  await expect(page.getByText(/9 archivos \(/)).toBeVisible();
  await expect(page.getByLabel("Nombre del caso (opcional)")).toHaveAttribute("placeholder", "01PrimeraInstancia");
  await capturar(page, "03-carpeta-lista");
  await page.getByRole("button", { name: "Elegir otra carpeta" }).click();
  await expect(page.getByRole("button", { name: "Elegir carpeta" })).toBeVisible();
});

test("casos: soltar archivos sobre la página muestra la superposición y la selección", async ({ page }) => {
  await page.goto("/#/segunda");
  await expect(page.getByRole("button", { name: "Elegir carpeta" })).toBeVisible();
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array([37, 80, 68, 70])], "uno.pdf", { type: "application/pdf" }));
    dt.items.add(new File([new Uint8Array([37, 80, 68, 70])], "dos.pdf", { type: "application/pdf" }));
    (window as unknown as { __dt: DataTransfer }).__dt = dt;
    document.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true, cancelable: true }));
    document.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  await expect(page.getByText("Suelte la carpeta")).toBeVisible();
  await page.evaluate(() => {
    const dt = (window as unknown as { __dt: DataTransfer }).__dt;
    document.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  await expect(page.getByRole("heading", { name: "Carpeta lista" })).toBeVisible();
  await expect(page.getByText(/2 archivos \(/)).toBeVisible();
  await page.getByRole("button", { name: "Elegir otra carpeta" }).click();
});
