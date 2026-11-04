import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLASE_FONDO_BLOQUEADO, Dialogo } from "./Dialogo";

const estilos = readFileSync(join(import.meta.dirname, "../estilos/ui.css"), "utf8");

function Montaje({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  return (
    <>
      <button>Abrir</button>
      <Dialogo abierto={abierto} titulo="Falta la clave" onCerrar={onCerrar} acciones={<button>Cancelar</button>}>
        <input aria-label="Clave" />
      </Dialogo>
    </>
  );
}

const dialogo = () => document.querySelector("dialog") as HTMLDialogElement;

describe("Dialogo", () => {
  it("no muestra contenido cerrado", () => {
    render(<Montaje abierto={false} onCerrar={() => {}} />);
    expect(dialogo().hasAttribute("open")).toBe(false);
    expect(screen.queryByText("Falta la clave")).toBeNull();
  });

  it("abre, nombra el diálogo y enfoca el primer control", () => {
    render(<Montaje abierto onCerrar={() => {}} />);
    expect(dialogo().hasAttribute("open")).toBe(true);
    expect(dialogo().getAttribute("aria-labelledby")).toBe(screen.getByRole("heading", { name: "Falta la clave" }).id);
    expect(document.activeElement).toBe(screen.getByLabelText("Clave"));
  });

  it("Escape pide cerrar", () => {
    const alCerrar = vi.fn();
    render(<Montaje abierto onCerrar={alCerrar} />);
    fireEvent.keyDown(screen.getByLabelText("Clave"), { key: "Escape" });
    expect(alCerrar).toHaveBeenCalledOnce();
  });

  it("el evento cancel del navegador pide cerrar sin cerrar solo", () => {
    const alCerrar = vi.fn();
    render(<Montaje abierto onCerrar={alCerrar} />);
    const evento = new Event("cancel", { cancelable: true });
    dialogo().dispatchEvent(evento);
    expect(alCerrar).toHaveBeenCalledOnce();
    expect(evento.defaultPrevented).toBe(true);
  });

  it("atrapa el foco con Tab y Shift+Tab", () => {
    render(<Montaje abierto onCerrar={() => {}} />);
    const clave = screen.getByLabelText("Clave");
    const cancelar = screen.getByRole("button", { name: "Cancelar" });
    cancelar.focus();
    fireEvent.keyDown(cancelar, { key: "Tab" });
    expect(document.activeElement).toBe(clave);
    fireEvent.keyDown(clave, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(cancelar);
  });

  it("cierra al pulsar el fondo pero no el contenido", () => {
    const alCerrar = vi.fn();
    render(<Montaje abierto onCerrar={alCerrar} />);
    fireEvent.click(screen.getByLabelText("Clave"));
    expect(alCerrar).not.toHaveBeenCalled();
    fireEvent.click(dialogo());
    expect(alCerrar).toHaveBeenCalledOnce();
  });

  it("devuelve el foco al elemento previo al cerrarse", () => {
    const { rerender } = render(<Montaje abierto={false} onCerrar={() => {}} />);
    const abrir = screen.getByRole("button", { name: "Abrir" });
    abrir.focus();
    rerender(<Montaje abierto onCerrar={() => {}} />);
    expect(document.activeElement).not.toBe(abrir);
    rerender(<Montaje abierto={false} onCerrar={() => {}} />);
    expect(dialogo().hasAttribute("open")).toBe(false);
    expect(document.activeElement).toBe(abrir);
  });
});

describe("Dialogo: bloqueo del desplazamiento del fondo", () => {
  const bloqueado = () => document.documentElement.classList.contains(CLASE_FONDO_BLOQUEADO);
  const overflowDelDocumento = () => getComputedStyle(document.documentElement).overflow;

  beforeEach(() => {
    const hoja = document.createElement("style");
    hoja.dataset["prueba"] = "ui";
    hoja.textContent = estilos;
    document.head.append(hoja);
  });

  afterEach(() => {
    document.head.querySelector("style[data-prueba]")?.remove();
    document.documentElement.classList.remove(CLASE_FONDO_BLOQUEADO);
  });

  it("la hoja de estilos oculta el desplazamiento del documento solo con un diálogo abierto", () => {
    expect(overflowDelDocumento()).not.toBe("hidden");
    document.documentElement.classList.add(CLASE_FONDO_BLOQUEADO);
    expect(overflowDelDocumento()).toBe("hidden");
    document.documentElement.classList.remove(CLASE_FONDO_BLOQUEADO);
    expect(overflowDelDocumento()).not.toBe("hidden");
  });

  it("bloquea el fondo al abrir y lo libera al cerrar", () => {
    const { rerender } = render(<Montaje abierto={false} onCerrar={() => {}} />);
    expect(bloqueado()).toBe(false);
    rerender(<Montaje abierto onCerrar={() => {}} />);
    expect(bloqueado()).toBe(true);
    expect(overflowDelDocumento()).toBe("hidden");
    rerender(<Montaje abierto={false} onCerrar={() => {}} />);
    expect(bloqueado()).toBe(false);
    expect(overflowDelDocumento()).not.toBe("hidden");
  });

  it("lo libera si el diálogo se desmonta estando abierto", () => {
    const { unmount } = render(<Montaje abierto onCerrar={() => {}} />);
    expect(bloqueado()).toBe(true);
    unmount();
    expect(bloqueado()).toBe(false);
  });

  it("con dos diálogos abiertos lo mantiene hasta cerrar el último", () => {
    const primero = render(<Montaje abierto onCerrar={() => {}} />);
    const segundo = render(<Montaje abierto onCerrar={() => {}} />);
    primero.unmount();
    expect(bloqueado()).toBe(true);
    segundo.unmount();
    expect(bloqueado()).toBe(false);
  });
});
