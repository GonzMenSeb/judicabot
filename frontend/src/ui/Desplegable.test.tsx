import { fireEvent, render, screen } from "@testing-library/preact";
import { useState } from "preact/hooks";
import { describe, expect, it, vi } from "vitest";
import { Desplegable } from "./Desplegable";

function Montaje({ inicial = false, alEscape }: { inicial?: boolean; alEscape?: () => void }) {
  const [abierto, setAbierto] = useState(inicial);
  return (
    <div onKeyDown={alEscape ? (e) => e.key === "Escape" && alEscape() : undefined}>
      <button>Antes</button>
      <Desplegable etiqueta="Estado" titulo="Filtrar por estado" abierto={abierto} onAbrir={() => setAbierto(true)} onCerrar={() => setAbierto(false)} pie={<button>Listo · 12 casos</button>}>
        <input aria-label="Buscar estado" />
      </Desplegable>
      <button>Después</button>
    </div>
  );
}

const disparador = () => screen.getByRole("button", { name: "Estado" });

describe("Desplegable", () => {
  it("cerrado no monta el panel y declara aria-expanded=false", () => {
    render(<Montaje />);
    expect(disparador().getAttribute("aria-expanded")).toBe("false");
    expect(disparador().getAttribute("type")).toBe("button");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("abierto enlaza el botón con un panel role=dialog nombrado y enfoca el primer control", () => {
    render(<Montaje />);
    fireEvent.click(disparador());
    const panel = screen.getByRole("dialog", { name: "Filtrar por estado" });
    expect(disparador().getAttribute("aria-expanded")).toBe("true");
    expect(disparador().getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.tagName).toBe("DIV");
    expect(document.activeElement).toBe(screen.getByLabelText("Buscar estado"));
  });

  it("sin controles enfocables enfoca el propio panel", () => {
    render(<Desplegable etiqueta="X" titulo="Vacío" abierto onAbrir={() => {}} onCerrar={() => {}} />);
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
  });

  it("Escape cierra, devuelve el foco al disparador y no llega a otros manejadores", () => {
    const fuera = vi.fn();
    render(<Montaje inicial alEscape={fuera} />);
    fireEvent.keyDown(screen.getByLabelText("Buscar estado"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(disparador());
    expect(fuera).not.toHaveBeenCalled();
  });

  it("Escape con el panel cerrado sigue su camino", () => {
    const fuera = vi.fn();
    render(<Montaje alEscape={fuera} />);
    fireEvent.keyDown(disparador(), { key: "Escape" });
    expect(fuera).toHaveBeenCalledOnce();
  });

  it("clic en el velo cierra y devuelve el foco", () => {
    const { container } = render(<Montaje inicial />);
    fireEvent.click(container.querySelector(".desplegable-velo")!);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(disparador());
  });

  it("el velo no es accesible", () => {
    const { container } = render(<Montaje inicial />);
    const velo = container.querySelector(".desplegable-velo")!;
    expect(velo.getAttribute("aria-hidden")).toBe("true");
    expect(velo.getAttribute("tabindex")).toBe("-1");
  });

  it("clic en el disparador abierto lo cierra", () => {
    render(<Montaje inicial />);
    fireEvent.click(disparador());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("el foco que sale del componente cierra; el que se queda dentro no", () => {
    render(<Montaje inicial />);
    const dentro = screen.getByRole("button", { name: "Listo · 12 casos" });
    fireEvent.focusOut(screen.getByLabelText("Buscar estado"), { relatedTarget: dentro });
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.focusOut(screen.getByLabelText("Buscar estado"), { relatedTarget: screen.getByRole("button", { name: "Después" }) });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("nunca crea un elemento dialog", () => {
    const { container } = render(<Montaje />);
    fireEvent.click(disparador());
    expect(container.querySelector("dialog")).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
  });

  it("muestra el pie y acepta aria-label y estado activo en el disparador", () => {
    render(<Desplegable etiqueta="Estado" aria-label="Estado, 2 elegidos" titulo="T" activo abierto onAbrir={() => {}} onCerrar={() => {}} pie={<button>Listo · 12 casos</button>} />);
    expect(screen.getByRole("button", { name: "Listo · 12 casos" })).toBeTruthy();
    const boton = screen.getByRole("button", { name: "Estado, 2 elegidos" });
    expect(boton.classList.contains("activo")).toBe(true);
  });
});
