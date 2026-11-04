import { cx } from "./clases";

export type SeccionTopbar = "inicio" | "formato" | "ia";

export interface PropsTopbar {
  seccion?: SeccionTopbar | null;
  clave: boolean | null;
  modelo?: string | null;
}

function estadoClave(clave: boolean | null): string {
  if (clave === null) return "estado de la clave desconocido";
  return clave ? "clave lista" : "falta la clave";
}

export function Topbar({ seccion = null, clave, modelo }: PropsTopbar) {
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
        <a class="enlace-barra" href="#/formato" aria-current={actual("formato")} aria-label="Formato de documentos">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 2h9l5 5v15H6z" />
            <path d="M15 2v5h5" />
            <path d="M9 13h7M9 17h5" />
          </svg>
          <span class="txt">Formato de documentos</span>
        </a>
        <a class="enlace-barra" href="#/ia" aria-current={actual("ia")}>
          <span class={cx("punto", clave === null ? "nulo" : clave ? false : "mal")} aria-hidden="true" />
          <span class="solo-lectura">Inteligencia artificial, {estadoClave(clave)}. </span>
          <span class="txt">{modelo || "Inteligencia artificial"}</span>
        </a>
      </nav>
    </header>
  );
}
