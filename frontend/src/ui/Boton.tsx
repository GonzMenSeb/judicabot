import type { JSX } from "preact";
import { cx } from "./clases";

export type VarianteBoton = "primario" | "secundario" | "peligro" | "fantasma" | "sello";

export interface PropsBoton extends Omit<JSX.HTMLAttributes<HTMLElement>, "type" | "href" | "download" | "ref"> {
  variante?: VarianteBoton;
  grande?: boolean;
  cargando?: boolean;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  href?: string;
  download?: string | boolean;
}

export function Boton({
  variante = "secundario",
  grande,
  cargando,
  type = "button",
  href,
  download,
  disabled,
  class: clase,
  children,
  ...resto
}: PropsBoton) {
  const clases = cx("btn", variante, grande && "grande", cargando && "cargando", typeof clase === "string" && clase);
  const inactivo = Boolean(disabled) || Boolean(cargando);
  const contenido = (
    <>
      {cargando && <span class="giro" aria-hidden="true" />}
      {children}
    </>
  );
  if (href !== undefined) {
    return (
      <a
        {...resto}
        class={clases}
        href={inactivo ? undefined : href}
        download={inactivo ? undefined : download}
        aria-disabled={inactivo ? "true" : undefined}
        aria-busy={cargando ? "true" : undefined}
      >
        {contenido}
      </a>
    );
  }
  return (
    <button {...resto} type={type} class={clases} disabled={inactivo} aria-busy={cargando ? "true" : undefined}>
      {contenido}
    </button>
  );
}
