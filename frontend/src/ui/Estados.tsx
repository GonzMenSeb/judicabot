import type { ComponentChildren } from "preact";
import { Boton } from "./Boton";
import { cx } from "./clases";

export interface PropsCargando {
  texto?: string;
  class?: string;
}

export function Cargando({ texto = "Cargando…", class: clase }: PropsCargando) {
  return (
    <div class={cx("cargando-caja", clase)} role="status">
      <span class="giro" aria-hidden="true" />
      <span>{texto}</span>
    </div>
  );
}

export interface PropsVacio {
  titulo: string;
  accion?: ComponentChildren;
  class?: string;
  children?: ComponentChildren;
}

export function Vacio({ titulo, accion, class: clase, children }: PropsVacio) {
  return (
    <div class={cx("vacio", clase)}>
      <b>{titulo}</b>
      {children && <p>{children}</p>}
      {accion && <div class="acciones">{accion}</div>}
    </div>
  );
}

export interface PropsCasoNoEncontrado {
  class?: string;
}

export function CasoNoEncontrado({ class: clase }: PropsCasoNoEncontrado) {
  return (
    <Vacio
      class={clase}
      titulo="No se encontró el caso"
      accion={
        <Boton variante="primario" href="#/segunda">
          Volver a los casos
        </Boton>
      }
    >
      El caso no existe o fue eliminado.
    </Vacio>
  );
}
