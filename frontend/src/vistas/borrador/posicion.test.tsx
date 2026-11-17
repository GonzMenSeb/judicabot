import { render } from "@testing-library/preact";
import { useRef } from "preact/hooks";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePosicionPopover } from "./posicion";

class ObservadorFalso {
  static ultimo: ObservadorFalso | null = null;
  readonly observados: Element[] = [];
  desconectado = false;
  constructor(private readonly alCambiar: ResizeObserverCallback) {
    ObservadorFalso.ultimo = this;
  }
  observe(el: Element) {
    this.observados.push(el);
  }
  unobserve() {}
  disconnect() {
    this.desconectado = true;
  }
  disparar() {
    this.alCambiar([], this as unknown as ResizeObserver);
  }
}

const rect = (top: number, alto: number, left = 100, ancho = 120): DOMRect =>
  ({ top, bottom: top + alto, left, right: left + ancho, width: ancho, height: alto, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

let altoCaja = 300;

function Prueba({ ancla, contenedor }: { ancla: HTMLElement; contenedor: HTMLElement }) {
  const caja = useRef<HTMLElement>(null);
  const arriba = usePosicionPopover(caja, ancla, contenedor, "ap-1");
  return <section ref={caja} id="caja" data-arriba={String(arriba)} />;
}

function montar() {
  const contenedor = document.createElement("div");
  const ancla = document.createElement("span");
  document.body.append(contenedor, ancla);
  vi.spyOn(contenedor, "getBoundingClientRect").mockReturnValue(rect(0, 2000, 0, 900));
  // La marca queda cerca del borde inferior: el detalle se voltea encima de ella.
  vi.spyOn(ancla, "getClientRects").mockReturnValue([rect(800, 20)] as unknown as DOMRectList);
  vi.spyOn(ancla, "getBoundingClientRect").mockReturnValue(rect(800, 20));
  const vista = render(<Prueba ancla={ancla} contenedor={contenedor} />);
  return { ...vista, caja: document.getElementById("caja") as HTMLElement };
}

describe("usePosicionPopover", () => {
  const ancho = window.innerWidth;
  const alto = window.innerHeight;

  beforeEach(() => {
    altoCaja = 300;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => altoCaja });
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(0);
      return 1;
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: ancho });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: alto });
    Reflect.deleteProperty(HTMLElement.prototype, "offsetHeight");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    ObservadorFalso.ultimo = null;
    document.body.innerHTML = "";
  });

  it("encima de la marca, se recoloca cuando cambia su propio alto para seguir pegado a ella", () => {
    vi.stubGlobal("ResizeObserver", ObservadorFalso);
    const { caja } = montar();
    expect(caja.dataset["arriba"]).toBe("true");
    expect(caja.style.top).toBe(`${800 - 300 - 12}px`);
    const observador = ObservadorFalso.ultimo;
    expect(observador?.observados).toEqual([caja]);

    // Tras subir el certificado la ayuda desaparece y el detalle se encoge: su borde inferior sigue sobre la marca.
    altoCaja = 150;
    observador?.disparar();
    expect(caja.style.top).toBe(`${800 - 150 - 12}px`);
  });

  it("no se recoloca si el alto no cambió", () => {
    vi.stubGlobal("ResizeObserver", ObservadorFalso);
    const { caja } = montar();
    caja.style.top = "1px";
    ObservadorFalso.ultimo?.disparar();
    expect(caja.style.top).toBe("1px");
  });

  it("deja de observar al cerrarse", () => {
    vi.stubGlobal("ResizeObserver", ObservadorFalso);
    const { unmount } = montar();
    const observador = ObservadorFalso.ultimo;
    unmount();
    expect(observador?.desconectado).toBe(true);
  });

  it("funciona en un navegador sin ResizeObserver", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    expect(() => montar()).not.toThrow();
  });
});
