import type { ComponentChildren } from "preact";
import { cx } from "./clases";

export type TipoAviso = "info" | "alerta" | "error" | "ok";

export interface PropsAviso {
  tipo?: TipoAviso;
  titulo?: string;
  acciones?: ComponentChildren;
  class?: string;
  children?: ComponentChildren;
}

export function Aviso({ tipo = "info", titulo, acciones, class: clase, children }: PropsAviso) {
  return (
    <div class={cx("aviso", tipo !== "info" && tipo, clase)} role={tipo === "error" ? "alert" : "status"}>
      <div>
        {titulo && <b>{titulo}</b>}
        {children}
      </div>
      {acciones && <div class="acciones">{acciones}</div>}
    </div>
  );
}
