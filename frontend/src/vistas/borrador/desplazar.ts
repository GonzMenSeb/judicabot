const MARGEN = 8;

const margenDe = (valor: string): number => Math.max(MARGEN, Number.parseFloat(valor) || 0);

/**
 * Lleva `el` a la vista desplazando solo `contenedor` (el cuerpo del panel o del detalle), nunca la ventana:
 * scrollIntoView movería también la página y cortaría el desplazamiento hacia la marca («Ver en el texto») o el que
 * aparta el detalle de la barra inferior. Respeta el scroll-margin de `el` (la fila deja a la vista la cabecera fija
 * de su grupo). Lo que es más alto que el contenedor se muestra desde arriba (la fila de un abogado, desde su nombre);
 * lo demás, lo justo para verse entero.
 */
export function mostrarDentro(contenedor: HTMLElement, el: HTMLElement): void {
  const caja = contenedor.getBoundingClientRect();
  if (caja.height <= 0) return;
  const r = el.getBoundingClientRect();
  const estilo = getComputedStyle(el);
  const margenArriba = margenDe(estilo.scrollMarginTop);
  const margenAbajo = margenDe(estilo.scrollMarginBottom);
  const arriba = r.top - caja.top - margenArriba;
  const abajo = r.bottom - caja.bottom + margenAbajo;
  const delta = r.height > caja.height - margenArriba - margenAbajo || arriba < 0 ? arriba : Math.max(0, abajo);
  if (delta !== 0) contenedor.scrollTop += delta;
}
