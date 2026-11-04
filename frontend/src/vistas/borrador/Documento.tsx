import type { ComponentChildren } from "preact";
import type { Bloque, CitaVista, Segmento, Vista } from "../../api/contrato";
import { cx, Hoja } from "../../ui";
import { agruparBloques, ETIQUETA_ESTADO_CITA } from "./datos";

const COLUMNAS_ANCHA = 3;

export interface ContextoDocumento {
  citas: Map<string, CitaVista>;
  seleccionada: string | null;
  alCita: (id: string, disparador: HTMLElement) => void;
}

interface PropsSegmentos extends ContextoDocumento {
  segmentos: Segmento[];
}

function Fragmento({ segmento, citas, seleccionada, alCita }: ContextoDocumento & { segmento: Segmento }) {
  let nodo: ComponentChildren = segmento.texto.replace(/\t/g, " ");
  if (segmento.negrita) nodo = <strong>{nodo}</strong>;
  if (segmento.cursiva) nodo = <em>{nodo}</em>;
  const cita = segmento.cita_id ? citas.get(segmento.cita_id) : undefined;
  if (!cita) return <>{nodo}</>;
  const activa = seleccionada === cita.id;
  return (
    <button
      type="button"
      class={cx("bor-cita", cita.estado, activa && "sel")}
      data-cita={cita.id}
      aria-pressed={activa}
      aria-controls={activa ? "bor-detalle" : undefined}
      onClick={(e) => alCita(cita.id, e.currentTarget)}
    >
      {nodo}
      <span class="solo-lectura"> ({ETIQUETA_ESTADO_CITA[cita.estado]})</span>
    </button>
  );
}

function Segmentos({ segmentos, ...contexto }: PropsSegmentos) {
  return (
    <>
      {segmentos.map((segmento, i) => (
        <Fragmento key={i} segmento={segmento} {...contexto} />
      ))}
    </>
  );
}

function BloqueTexto({ bloque, ...contexto }: ContextoDocumento & { bloque: Bloque }) {
  const plantilla = bloque.origen === "plantilla" ? "bor-tpl" : undefined;
  const contenido = <Segmentos segmentos={bloque.segmentos} {...contexto} />;
  switch (bloque.tipo) {
    case "titulo":
      return (
        <h3 id={`b-${bloque.id}`} class={cx("bor-titulo", plantilla)}>
          {contenido}
        </h3>
      );
    case "encabezado":
      return bloque.seccion ? (
        <h4 id={`b-${bloque.id}`} class={cx("bor-sub", plantilla)}>
          {contenido}
        </h4>
      ) : (
        <p class={cx("bor-enc", plantilla)}>{contenido}</p>
      );
    case "cita_bloque":
      return <blockquote class={plantilla}>{contenido}</blockquote>;
    case "firma":
      return <p class={cx("bor-firma", plantilla)}>{contenido}</p>;
    case "resuelve_numeral":
      return <p class={cx("bor-resuelve", plantilla)}>{contenido}</p>;
    default:
      return <p class={plantilla}>{contenido}</p>;
  }
}

function Bloques({ bloques, ...contexto }: ContextoDocumento & { bloques: Bloque[] }) {
  return (
    <>
      {agruparBloques(bloques).map((grupo, i) => {
        if (grupo.tipo === "bloque") return <BloqueTexto key={grupo.bloque.id} bloque={grupo.bloque} {...contexto} />;
        const plantilla = grupo.bloques.every((b) => b.origen === "plantilla") ? "bor-tpl" : undefined;
        if (grupo.tipo === "lista") {
          return (
            <ul key={i} class={cx("bor-lista", plantilla)}>
              {grupo.bloques.map((b) => (
                <li key={b.id}>
                  <Segmentos segmentos={b.segmentos} {...contexto} />
                </li>
              ))}
            </ul>
          );
        }
        const columnas = Math.max(...grupo.bloques.map((f) => f.segmentos.length));
        const ancha = columnas > COLUMNAS_ANCHA;
        return (
          <div
            key={i}
            class={cx("bor-tabla-caja", plantilla)}
            role={ancha ? "region" : undefined}
            tabIndex={ancha ? 0 : undefined}
            aria-label={ancha ? "Tabla, desplazable horizontalmente" : undefined}
          >
            <table
              class={cx("bor-tabla", grupo.bloques.every((f) => f.segmentos.length === 2) && "bor-tabla-2", ancha && "bor-tabla-ancha")}
              style={ancha ? { "--columnas": columnas } : undefined}
            >
              <tbody>
                {grupo.bloques.map((fila) => (
                  <tr key={fila.id}>
                    {fila.segmentos.map((celda, j) => (
                      <td key={j}>
                        <Fragmento segmento={celda} {...contexto} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

export interface PropsDocumento extends ContextoDocumento {
  vista: Vista;
  origen: boolean;
}

export function Documento({ vista, origen, ...contexto }: PropsDocumento) {
  const ultima = vista.paginas.length - 1;
  return (
    <Hoja etiqueta="Borrador del fallo, secciones I a V" class={cx("bor-hoja", origen && "bor-origen")}>
      <span class="bor-sello">Borrador, aún no es el fallo</span>
      {vista.paginas.map((pagina, i) => {
        const cuerpo = pagina.bloques.filter((b) => b.tipo !== "pie");
        const pie = i === ultima ? pagina.bloques.filter((b) => b.tipo === "pie") : [];
        return (
          <div key={i} class="bor-pagina">
            <Bloques bloques={cuerpo} {...contexto} />
            {pie.length > 0 && (
              <footer class="bor-pie">
                {pie.map((b) => (
                  <p key={b.id}>
                    <Segmentos segmentos={b.segmentos} {...contexto} />
                  </p>
                ))}
              </footer>
            )}
          </div>
        );
      })}
    </Hoja>
  );
}
