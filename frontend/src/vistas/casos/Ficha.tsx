import type { CasoResumen } from "../../api/contrato";
import { fechaRelativa, plural } from "../../estado";
import { Boton, Chip, cx } from "../../ui";
import { accionDe, descripcionAvance, hrefCaso, partesDe, tonoDe, tramosDe, varianteDe } from "./agrupar";
import "./ficha.css";

export interface PropsFicha {
  caso: CasoResumen;
  compacta?: boolean;
  nivel?: 3 | 4;
}

export function Ficha({ caso, compacta, nivel = 4 }: PropsFicha) {
  const Titulo = `h${nivel}` as const;
  const accion = accionDe(caso.estado);
  const partes = partesDe(caso);
  return (
    <article class={cx("ficha", tonoDe(caso.estado), compacta && "compacta")}>
      <div class="datos">
        <Titulo>{caso.nombre}</Titulo>
        <div class="meta">
          {caso.radicado && <span class="radicado">Radicado {caso.radicado}</span>}
          {caso.juzgado_a_quo && <span title={caso.juzgado_a_quo}>{caso.juzgado_a_quo}</span>}
        </div>
        {partes && (
          <p class="partes" title={partes}>
            {partes}
          </p>
        )}
      </div>
      <div class="avance">
        <div class="seg4" role="img" aria-label={descripcionAvance(caso.etapa)}>
          {tramosDe(caso.etapa).map((tramo, i) => (
            <i key={i} class={tramo || undefined} />
          ))}
        </div>
        <div class="siguiente">
          <small>{caso.siguiente_paso}</small>
          {caso.n_alertas > 0 && (
            <Chip tono="alerta" title="Alertas detectadas al leer el expediente">
              {plural(caso.n_alertas, "alerta")}
            </Chip>
          )}
        </div>
      </div>
      <div class="accion">
        <Boton href={hrefCaso(caso)} variante={varianteDe(caso.estado)} aria-label={`${accion}: ${caso.nombre}`}>
          {accion}
        </Boton>
        <small>{fechaRelativa(caso.actualizado)}</small>
      </div>
    </article>
  );
}
