import type { RefObject } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

const ANCHO_MOVIL = 760;
const HOLGURA = 16;

const altoDe = (selector: string) => document.querySelector(selector)?.getBoundingClientRect().height ?? 0;

const reducirMovimiento = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Coloca el detalle bajo la marca del texto (o encima si abajo no cabe), con la flecha apuntando a la marca, y lo
 * recoloca al desplazar o redimensionar la ventana y cuando cambia su propio alto (el de un abogado crece o se
 * encoge con la consulta, la subida del certificado o la revisión; encima de la marca, su borde inferior debe
 * seguir pegado a ella). En un teléfono el CSS lo fija abajo y aquí no se toca. Si al abrirse lo taparía la barra
 * inferior, desplaza la página lo justo. Devuelve si quedó encima de la marca.
 */
export function usePosicionPopover(caja: RefObject<HTMLElement>, ancla: HTMLElement, contenedor: HTMLElement, clave: string): boolean {
  const [arriba, setArriba] = useState(false);

  useLayoutEffect(() => {
    const el = caja.current;
    if (!el) return;

    const colocar = (): boolean => {
      if (window.innerWidth <= ANCHO_MOVIL) return false;
      const col = contenedor.getBoundingClientRect();
      const rects = ancla.getClientRects();
      const r = rects.length > 0 ? rects[rects.length - 1]! : ancla.getBoundingClientRect();
      const ancho = el.offsetWidth;
      const alto = el.offsetHeight;
      const izq = Math.max(12, Math.min(r.left - col.left + r.width / 2 - 40, col.width - ancho - 12));
      const espacioAbajo = window.innerHeight - r.bottom - altoDe(".bor-dock");
      const espacioArriba = r.top - altoDe(".barra") - 60;
      const voltear = espacioAbajo < alto + 24 && espacioArriba > alto;
      el.style.left = `${izq}px`;
      el.style.top = `${voltear ? r.top - col.top - alto - 12 : r.bottom - col.top + 12}px`;
      el.style.setProperty("--flecha", `${Math.max(14, Math.min(r.left - col.left + r.width / 2 - izq - 6, ancho - 26))}px`);
      setArriba(voltear);
      return voltear;
    };

    const voltea = colocar();

    if (window.innerWidth > ANCHO_MOVIL && !voltea) {
      const dock = document.querySelector(".bor-dock");
      const rect = el.getBoundingClientRect();
      if (dock && rect.height > 0) {
        const sobra = rect.bottom - (dock.getBoundingClientRect().top - HOLGURA);
        const margen = ancla.getBoundingClientRect().top - altoDe(".barra") - 70;
        const desplazar = Math.min(sobra, margen);
        if (sobra > 0 && desplazar > 0) window.scrollBy({ top: desplazar, behavior: reducirMovimiento() ? "auto" : "smooth" });
      }
    }

    let pendiente = 0;
    const reponer = () => {
      if (pendiente) return;
      pendiente = requestAnimationFrame(() => {
        pendiente = 0;
        colocar();
      });
    };
    window.addEventListener("scroll", reponer, { passive: true });
    window.addEventListener("resize", reponer);
    let alto = el.offsetHeight;
    const observador =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(() => {
            if (el.offsetHeight === alto) return;
            alto = el.offsetHeight;
            reponer();
          })
        : null;
    observador?.observe(el);
    return () => {
      window.removeEventListener("scroll", reponer);
      window.removeEventListener("resize", reponer);
      observador?.disconnect();
      if (pendiente) cancelAnimationFrame(pendiente);
    };
  }, [ancla, contenedor, clave]);

  return arriba;
}
