import type { CasoResumen } from "../../api/contrato";
import { fechaRelativa, plural } from "../../estado";
import { Boton, Chip, cx } from "../../ui";
import { accionDe, descripcionAvance, hrefCaso, partesDe, tonoDe, tramosDe, varianteDe } from "./agrupar";
import { estadoDe, infoEstado, infoProceso, procesoDe, type DatoFila } from "./facetas";
import { IconoProceso } from "./iconos";
import "./ficha.css";

export interface PropsFicha {
  caso: CasoResumen;
  nivel?: 3 | 4;
  /** Línea superior con el proceso del caso (Inicio con varios procesos a la vista). */
  mostrarProceso?: boolean;
  /** Datos propios del proceso; `eco` los resalta porque explican por qué el caso pasa los filtros. */
  datos?: readonly Dato[];
}

const fechaLarga = new Intl.DateTimeFormat("es-CO", { dateStyle: "long", timeStyle: "short" });

function Cuando({ iso, clase }: { iso: string; clase?: string }) {
  const fecha = new Date(iso);
  const titulo = Number.isNaN(fecha.getTime()) ? undefined : `Última actividad: ${fechaLarga.format(fecha)}`;
  return (
    <small class={clase} title={titulo}>
      {fechaRelativa(iso)}
    </small>
  );
}

const Alertas = ({ n }: { n: number }) =>
  n > 0 ? (
    <Chip tono="alerta" title="Alertas detectadas al leer el expediente">
      {plural(n, "alerta")}
    </Chip>
  ) : null;

type Dato = DatoFila & { eco?: boolean };

/** Los datos propios como chips; los que reflejan un filtro elegido van resaltados (.dato.eco). */
const Datos = ({ datos }: { datos: readonly Dato[] }) => (
  <>
    {datos.map((d) => (
      <Chip key={d.texto} tono={d.eco ? "neutro" : d.tono} title={d.texto} class={cx("dato", d.eco && "eco")}>
        {d.texto}
      </Chip>
    ))}
  </>
);

function Accion({ caso, clase }: { caso: CasoResumen; clase?: string }) {
  const accion = accionDe(caso.estado);
  return (
    <Boton href={hrefCaso(caso)} variante={varianteDe(caso.estado)} class={clase} aria-label={`${accion}: ${caso.nombre}`}>
      {accion}
    </Boton>
  );
}

export function Ficha({ caso, nivel = 4, mostrarProceso, datos }: PropsFicha) {
  const Titulo = `h${nivel}` as const;
  const partes = partesDe(caso);
  const proceso = procesoDe(caso);
  return (
    <article class={cx("ficha", tonoDe(caso.estado))}>
      <div class="datos">
        {mostrarProceso && (
          <p class="ceja">
            <IconoProceso tipo={proceso} />
            {infoProceso(proceso).corto}
          </p>
        )}
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
        {datos && datos.length > 0 && (
          <div class="extras">
            <Datos datos={datos} />
          </div>
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
          <Alertas n={caso.n_alertas} />
        </div>
      </div>
      <div class="accion">
        <Accion caso={caso} />
        <Cuando iso={caso.actualizado} />
      </div>
    </article>
  );
}

/**
 * La misma ficha en una línea, para la vista Compacta. El enlace conserva el nombre accesible de la ficha. De los
 * datos propios solo muestra el primero de los resaltados, para que la fila siga siendo una línea.
 */
export function FichaCompacta({ caso, nivel = 4, mostrarProceso, datos = [] }: PropsFicha) {
  const Titulo = `h${nivel}` as const;
  const estado = estadoDe(caso);
  const sub = [mostrarProceso && infoProceso(procesoDe(caso)).corto, caso.radicado && `Radicado ${caso.radicado}`, caso.juzgado_a_quo]
    .filter(Boolean)
    .join(" · ");
  return (
    <article class={cx("fila-c", tonoDe(caso.estado), `e-${estado}`)}>
      <span class="punto-estado" title={infoEstado(estado).etiqueta} aria-hidden="true" />
      <div class="c-nombre">
        <Titulo title={caso.nombre}>{caso.nombre}</Titulo>
        {sub && <small title={sub}>{sub}</small>}
      </div>
      <p class="c-sig">{caso.siguiente_paso}</p>
      <div class="c-marcas">
        <Datos datos={datos.filter((d) => d.eco).slice(0, 1)} />
        <Alertas n={caso.n_alertas} />
      </div>
      <Cuando iso={caso.actualizado} clase="c-cuando" />
      <Accion caso={caso} clase="chico" />
    </article>
  );
}
