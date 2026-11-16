import { render, screen, within } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import Extension from "./index";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Extensión de la relatoría", () => {
  it("ofrece descargar la extensión de la relatoría sin llamar a la API", () => {
    const fetchSimulado = vi.fn();
    vi.stubGlobal("fetch", fetchSimulado);
    render(<Extension />);
    const enlace = screen.getByRole("link", { name: "Descargar extensión (.zip)" });
    expect(enlace.getAttribute("href")).toBe("/api/extension/zip");
    expect(enlace.getAttribute("download")).toBe("");
    expect(enlace.classList.contains("btn")).toBe(true);
    expect(fetchSimulado).not.toHaveBeenCalled();
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
