import { act, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mostrarToast, toasts } from "../estado";
import { Toasts } from "./Toasts";

beforeEach(() => {
  vi.useFakeTimers();
  toasts.value = [];
});

afterEach(() => {
  vi.useRealTimers();
});

const avanzar = (ms: number) => act(() => void vi.advanceTimersByTime(ms));
const aviso = () => screen.getByText("Se eliminó «Caso».").closest(".toast")!;

describe("Toasts con acción", () => {
  it("dibuja la acción antes de cerrar; al pulsarla cierra el aviso y llama alHacer", () => {
    const alHacer = vi.fn();
    render(<Toasts />);
    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer } }));
    const botones = [...aviso().querySelectorAll("button")].map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(botones).toEqual(["Deshacer", "Cerrar aviso"]);
    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(alHacer).toHaveBeenCalledOnce();
    expect(toasts.value).toEqual([]);
  });

  it("si la acción tenía el foco, al quitar el aviso lo pasa al contenido en vez de dejarlo en <body>", () => {
    render(
      <>
        <main id="contenido" tabIndex={-1}>
          <input aria-label="Buscar" />
        </main>
        <Toasts />
      </>,
    );
    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer: () => {} } }));
    const deshacer = screen.getByRole("button", { name: "Deshacer" });
    deshacer.focus();
    fireEvent.click(deshacer);
    expect(document.activeElement).toBe(screen.getByRole("main"));

    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer: () => {} } }));
    const buscar = screen.getByRole("textbox", { name: "Buscar" });
    buscar.focus();
    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(document.activeElement).toBe(buscar);
  });

  it("se cierra solo al cumplir su tiempo", () => {
    render(<Toasts />);
    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer: () => {} } }));
    avanzar(9_999);
    expect(toasts.value).toHaveLength(1);
    avanzar(1);
    expect(toasts.value).toEqual([]);
  });

  it("no vence mientras el foco está dentro; al salir vuelve a contar desde cero", () => {
    render(<Toasts />);
    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer: () => {} } }));
    avanzar(8_000);
    const deshacer = screen.getByRole("button", { name: "Deshacer" });
    fireEvent.focusIn(deshacer);
    avanzar(30_000);
    expect(toasts.value).toHaveLength(1);
    // Pasar el foco de un botón a otro del mismo aviso no reanuda.
    fireEvent.focusOut(deshacer, { relatedTarget: screen.getByRole("button", { name: "Cerrar aviso" }) });
    avanzar(30_000);
    expect(toasts.value).toHaveLength(1);
    fireEvent.focusOut(aviso(), { relatedTarget: document.body });
    avanzar(9_999);
    expect(toasts.value).toHaveLength(1);
    avanzar(1);
    expect(toasts.value).toEqual([]);
  });

  it("no vence mientras el puntero está encima, ni si el foco sigue dentro cuando el puntero sale", () => {
    render(<Toasts />);
    act(() => void mostrarToast("Se eliminó «Caso».", { ms: 10_000, accion: { texto: "Deshacer", alHacer: () => {} } }));
    fireEvent.pointerEnter(aviso());
    avanzar(20_000);
    expect(toasts.value).toHaveLength(1);
    fireEvent.focusIn(screen.getByRole("button", { name: "Deshacer" }));
    fireEvent.pointerLeave(aviso());
    avanzar(20_000);
    expect(toasts.value).toHaveLength(1);
    fireEvent.focusOut(aviso(), { relatedTarget: null });
    avanzar(10_000);
    expect(toasts.value).toEqual([]);
  });

  it("los avisos sin acción no se detienen con el puntero", () => {
    render(<Toasts />);
    act(() => void mostrarToast("Guardado", { tipo: "ok" }));
    expect(screen.queryByRole("button", { name: "Deshacer" })).toBeNull();
    fireEvent.pointerEnter(screen.getByText("Guardado").closest(".toast")!);
    avanzar(3_500);
    expect(toasts.value).toEqual([]);
  });

  it("los errores con acción tampoco se cierran solos", () => {
    render(<Toasts />);
    act(() => void mostrarToast("Falló", { tipo: "error", accion: { texto: "Reintentar", alHacer: () => {} } }));
    fireEvent.pointerEnter(screen.getByText("Falló").closest(".toast")!);
    fireEvent.pointerLeave(screen.getByText("Falló").closest(".toast")!);
    avanzar(60_000);
    expect(toasts.value).toHaveLength(1);
  });
});
