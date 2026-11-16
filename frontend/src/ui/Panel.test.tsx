import { act, fireEvent, render, screen, within } from "@testing-library/preact";
import { useState } from "preact/hooks";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mostrarToast, toasts } from "../estado";
import { Dialogo } from "./Dialogo";
import { Panel } from "./Panel";

const ITEMS = [
  { href: "#/a", texto: "Sección A", actual: true },
  { href: "#/b", texto: "Sección B", detalle: "detalle de B" },
];

function Montaje({ abierto, onCerrar = () => {} }: { abierto: boolean; onCerrar?: () => void }) {
  return (
    <>
      <button id="volver">Volver</button>
      <Panel abierto={abierto} titulo="Configuración" items={ITEMS} encabezado="Sección A" onCerrar={onCerrar} retorno="#volver">
        <input aria-label="Campo" />
      </Panel>
    </>
  );
}

function ConDialogo({ onCerrar }: { onCerrar: () => void }) {
  const [abierto, setAbierto] = useState(false);
  return (
    <Panel abierto titulo="Configuración" items={ITEMS} encabezado="Sección A" onCerrar={onCerrar}>
      <button onClick={() => setAbierto(true)}>Confirmar</button>
      <Dialogo abierto={abierto} titulo="Confirmar" onCerrar={() => setAbierto(false)}>
        <button>Aceptar</button>
      </Dialogo>
    </Panel>
  );
}

const panel = () => document.querySelector("dialog.panel") as HTMLDialogElement;

beforeEach(() => {
  toasts.value = [];
});

describe("Panel", () => {
  it("cerrado no muestra contenido", () => {
    render(<Montaje abierto={false} />);
    expect(panel().hasAttribute("open")).toBe(false);
    expect(screen.queryByText("Sección A")).toBeNull();
  });

  it("se nombra con el título, muestra el encabezado y la navegación, y enfoca la sección actual", () => {
    render(<Montaje abierto />);
    const dialogo = screen.getByRole("dialog", { name: "Configuración" });
    expect(within(dialogo).getByRole("heading", { level: 1, name: "Sección A" })).toBeTruthy();
    const nav = within(dialogo).getByRole("navigation", { name: "Secciones de configuración" });
    const [a, b] = within(nav).getAllByRole("link");
    expect(a?.getAttribute("href")).toBe("#/a");
    expect(a?.getAttribute("aria-current")).toBe("page");
    expect(b?.getAttribute("aria-current")).toBeNull();
    expect(within(nav).getByRole("link", { name: "Sección B detalle de B" })).toBe(b);
    expect(document.activeElement).toBe(a);
    expect(within(dialogo).getByLabelText("Campo")).toBeTruthy();
  });

  it("la X, Escape y el fondo piden cerrar; un clic que empieza en el contenido no", () => {
    const alCerrar = vi.fn();
    render(<Montaje abierto onCerrar={alCerrar} />);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar configuración" }));
    expect(alCerrar).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("Campo"), { key: "Escape" });
    expect(alCerrar).toHaveBeenCalledTimes(2);
    fireEvent.mouseDown(screen.getByLabelText("Campo"));
    fireEvent.click(panel());
    expect(alCerrar).toHaveBeenCalledTimes(2);
    fireEvent.mouseDown(panel());
    fireEvent.click(panel());
    expect(alCerrar).toHaveBeenCalledTimes(3);
  });

  it("Escape dentro de un diálogo anidado solo cierra ese diálogo", () => {
    const alCerrar = vi.fn();
    render(<ConDialogo onCerrar={alCerrar} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    const aceptar = screen.getByRole("button", { name: "Aceptar" });
    expect(document.activeElement).toBe(aceptar);
    fireEvent.keyDown(aceptar, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Aceptar" })).toBeNull();
    expect(alCerrar).not.toHaveBeenCalled();
  });

  it("devuelve el foco al elemento de retorno al cerrar", () => {
    const { rerender } = render(<Montaje abierto />);
    expect(document.activeElement).not.toBe(screen.getByRole("button", { name: "Volver" }));
    rerender(<Montaje abierto={false} />);
    expect(panel().hasAttribute("open")).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Volver" }));
  });

  it("muestra los toasts dentro del panel abierto", async () => {
    render(<Montaje abierto />);
    await act(async () => {
      mostrarToast("Guardado", { ms: 0 });
    });
    expect(within(panel()).getByText("Guardado")).toBeTruthy();
  });
});
