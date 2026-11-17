import { afterEach, describe, expect, it, vi } from "vitest";
import { mostrarDentro } from "./desplazar";

const caja = (top: number, alto: number) => ({ top, bottom: top + alto, height: alto, left: 0, right: 300, width: 300, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function montar(contenedor: DOMRect, el: DOMRect, margenes: { top?: string; bottom?: string } = {}, inicial = 100) {
  const padre = document.createElement("div");
  const hijo = document.createElement("div");
  padre.append(hijo);
  document.body.append(padre);
  padre.scrollTop = inicial;
  vi.spyOn(padre, "getBoundingClientRect").mockReturnValue(contenedor);
  vi.spyOn(hijo, "getBoundingClientRect").mockReturnValue(el);
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((e: Element) =>
    e === hijo ? ({ scrollMarginTop: margenes.top ?? "0px", scrollMarginBottom: margenes.bottom ?? "0px" } as CSSStyleDeclaration) : real(e),
  );
  return { padre, hijo };
}

describe("mostrarDentro", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("baja lo justo, sube lo justo o no se mueve", () => {
    let { padre, hijo } = montar(caja(100, 500), caja(640, 60));
    mostrarDentro(padre, hijo);
    expect(padre.scrollTop).toBe(100 + (700 - 600 + 8));
    vi.restoreAllMocks();
    ({ padre, hijo } = montar(caja(100, 500), caja(50, 60)));
    mostrarDentro(padre, hijo);
    expect(padre.scrollTop).toBe(100 - (100 - 50 + 8));
    vi.restoreAllMocks();
    ({ padre, hijo } = montar(caja(100, 500), caja(300, 60)));
    mostrarDentro(padre, hijo);
    expect(padre.scrollTop).toBe(100);
  });

  it("respeta el scroll-margin: la fila no queda bajo la cabecera fija de su grupo", () => {
    const { padre, hijo } = montar(caja(100, 500), caja(400, 700), { top: "41.6px" }, 0);
    mostrarDentro(padre, hijo);
    expect(padre.scrollTop).toBeCloseTo(400 - 100 - 41.6);
  });

  it("sin alto (panel oculto) no hace nada", () => {
    const { padre, hijo } = montar(caja(0, 0), caja(640, 60));
    mostrarDentro(padre, hijo);
    expect(padre.scrollTop).toBe(100);
  });
});
