import { cx } from "./clases";

export type SeccionTopbar = "inicio" | "configuracion";

export interface PropsTopbar {
  seccion?: SeccionTopbar | null;
  clave: boolean | null;
}

export const ID_CONFIGURACION = "boton-configuracion";

export function estadoClave(clave: boolean | null): string {
  if (clave === null) return "estado de la clave desconocido";
  return clave ? "clave lista" : "falta la clave";
}

export const claseClave = (clave: boolean | null) => cx("punto", clave === null ? "nulo" : clave ? false : "mal");

export function Topbar({ seccion = null, clave }: PropsTopbar) {
  const actual = (s: SeccionTopbar) => (seccion === s ? "page" : undefined);
  return (
    <header class="barra">
      <a class="marca" href="#/" aria-label="Judicabot, ir al inicio">
        <img src="/marca.svg" alt="" width="30" height="30" />
        <b>Judicabot</b>
      </a>
      <span class="relleno" />
      <nav class="barra-nav" aria-label="Principal">
        <a class="enlace-barra" href="#/" aria-current={actual("inicio")} aria-label="Inicio">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 11l9-8 9 8" />
            <path d="M5 10v10h14V10" />
          </svg>
          <span class="txt">Inicio</span>
        </a>
        <a id={ID_CONFIGURACION} class="enlace-barra engranaje" href="#/configuracion" aria-current={actual("configuracion")}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.46 4.76L10.78 2.07L13.22 2.07L13.54 4.76A7.4 7.4 0 0 1 16.03 5.79L18.16 4.12L19.88 5.84L18.21 7.97A7.4 7.4 0 0 1 19.24 10.46L21.93 10.78L21.93 13.22L19.24 13.54A7.4 7.4 0 0 1 18.21 16.03L19.88 18.16L18.16 19.88L16.03 18.21A7.4 7.4 0 0 1 13.54 19.24L13.22 21.93L10.78 21.93L10.46 19.24A7.4 7.4 0 0 1 7.97 18.21L5.84 19.88L4.12 18.16L5.79 16.03A7.4 7.4 0 0 1 4.76 13.54L2.07 13.22L2.07 10.78L4.76 10.46A7.4 7.4 0 0 1 5.79 7.97L4.12 5.84L5.84 4.12L7.97 5.79A7.4 7.4 0 0 1 10.46 4.76Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          {clave !== true && <span class={claseClave(clave)} aria-hidden="true" />}
          <span class="solo-lectura">{clave === true ? "Configuración" : `Configuración, ${estadoClave(clave)}`}</span>
        </a>
      </nav>
    </header>
  );
}
