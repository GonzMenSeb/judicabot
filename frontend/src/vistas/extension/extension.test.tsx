import { render, screen, within } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import Extension from "./index";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Extensión de consultas públicas", () => {
  it("ofrece descargar la extensión sin llamar a la API", () => {
    const fetchSimulado = vi.fn();
    vi.stubGlobal("fetch", fetchSimulado);
    render(<Extension />);
    const enlace = screen.getByRole("link", { name: "Descargar extensión (.zip)" });
    expect(enlace.getAttribute("href")).toBe("/api/extension/zip");
    expect(enlace.getAttribute("download")).toBe("");
    expect(enlace.classList.contains("btn")).toBe(true);
    expect(fetchSimulado).not.toHaveBeenCalled();
  });

  it("explica las dos consultas y que para la vigencia solo sale el número de cédula", () => {
    const { container } = render(<Extension />);
    const texto = container.textContent ?? "";
    for (const frase of [
      "relatoría de la Corte Constitucional",
      "certificado de vigencia de la tarjeta profesional",
      "cuando la consulta automática está activada en el servidor",
      "solo envía el número de cédula del abogado, y solo a la página de certificados de la Rama Judicial",
      "trae de vuelta el PDF público",
      "el navegador envía a esa página las cookies que tenga de la Rama Judicial",
      "la consulta solo necesita las dos de afinidad que pone la propia página, que no tienen datos personales",
      "No hay inicio de sesión, no sigue redirecciones y no se envía ninguna cookie de otros sitios",
      "La consulta de la relatoría no cambia y sigue sin cookies",
      "necesita la versión 1.1.0 o más",
    ]) {
      expect(texto).toContain(frase);
    }
    expect(texto).not.toContain("No usa ni envía las cookies");
    // El navegador envía todas las cookies que tenga de la Rama Judicial, no solo las de afinidad.
    expect(texto).not.toContain("Las únicas cookies");
  });

  it("no repite el título ni usa encabezados: lo pone el panel", () => {
    render(<Extension />);
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
  });

  it("los pasos de instalación muestran el servidor de esta instalación", () => {
    render(<Extension />);
    const lista = screen.getByRole("list", { name: "Pasos para instalar la extensión" });
    expect(within(lista).getAllByRole("listitem")).toHaveLength(6);
    for (const texto of ["chrome://extensions", "edge://extensions", "Cargar extensión sin empaquetar", "judicabot-relatoria"]) {
      expect(lista.textContent).toContain(texto);
    }
    expect(within(lista).getByText(location.origin).tagName).toBe("CODE");
  });

  it("el botón va antes de los pasos y la nota de actualización al final", () => {
    render(<Extension />);
    const enlace = screen.getByRole("link", { name: "Descargar extensión (.zip)" });
    const lista = screen.getByRole("list", { name: "Pasos para instalar la extensión" });
    const nota = screen.getByText(/Para actualizarla, descargue el archivo de nuevo/);
    expect(enlace.compareDocumentPosition(lista) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(lista.compareDocumentPosition(nota) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
