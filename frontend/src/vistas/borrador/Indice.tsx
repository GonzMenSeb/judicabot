import "./indice.css";
import { Fragment } from "preact";
import { pluralizar } from "../../estado";
import { cx } from "../../ui";
import type { EntradaIndice, MarcaIndice, Redaccion } from "./tipos";

export interface PropsIndice {
  entradas: EntradaIndice[];
  marcas: Record<string, MarcaIndice>;
  activa: string | null;
  alSeccion: (id: string) => void;
  redaccion: Redaccion[];
  abierto: boolean;
}

/** Lo que oye un lector de pantalla junto al número: «2 citas por revisar», «1 cita y 1 abogado por revisar». */
export function lecturaMarca({ n, apoderados = 0 }: MarcaIndice): string {
  const citas = n - apoderados;
  const partes = [citas > 0 && `${citas} ${pluralizar(citas, "cita", "citas")}`, apoderados > 0 && `${apoderados} ${pluralizar(apoderados, "abogado", "abogados")}`];
  return `${partes.filter(Boolean).join(" y ")} por revisar`;
}

export function Indice({ entradas, marcas, activa, alSeccion, redaccion, abierto }: PropsIndice) {
  const primerAnexo = entradas.findIndex((e) => e.anexo);
  return (
    <nav id="bor-indice" class={cx("bor-indice", abierto && "abierto")} aria-label="Contenido del borrador">
      <p class="bor-rotulo">Contenido</p>
      <ul class="bor-indice-lista">
        {entradas.map((e, i) => {
          const marca = marcas[e.id];
          return (
            <Fragment key={e.id}>
              {i === primerAnexo && <li class="bor-corte" role="presentation" />}
              <li class={cx(e.sub && "sub", e.anexo && "anexo")}>
                <button type="button" aria-current={activa === e.id ? "location" : undefined} onClick={() => alSeccion(e.id)}>
                  <span>{e.titulo}</span>
                  {marca && (
                    <span class={cx("bor-marcador", marca.mal ? "mal" : "alerta")}>
                      <span aria-hidden="true">{marca.n}</span>
                      <span class="solo-lectura"> {lecturaMarca(marca)}</span>
                    </span>
                  )}
                </button>
              </li>
            </Fragment>
          );
        })}
      </ul>
      {redaccion.length > 0 && (
        <section class="bor-autoria" aria-labelledby="bor-sec-redaccion">
          <h2 id="bor-sec-redaccion" class="bor-rotulo">
            Quién redactó
          </h2>
          <ul>
            {redaccion.map((r) => (
              <li key={r.nodo}>
                <b>{r.secciones}</b>
                <span>{r.modelo}</span>
                {r.pedido && r.pedido !== r.modelo && <small>Se pidió {r.pedido}; respondió {r.modelo}.</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </nav>
  );
}
