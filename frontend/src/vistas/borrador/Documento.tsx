import type { ComponentChildren, JSX } from "preact";
import type { ApoderadoVista, Bloque, CitaVista, Segmento, Vista } from "../../api/contrato";
import { cx, Hoja } from "../../ui";
import { CLASE_MARCA, LECTURA_MARCA } from "./apoderados";
import "./apoderados.css";
import { agruparBloques, ETIQUETA_ESTADO_CITA } from "./datos";
import "./documento.css";
import type { Seleccion } from "./tipos";

const COLUMNAS_ANCHA = 3;

export interface ContextoDocumento {
  citas: Map<string, CitaVista>;
  /** Los abogados que devolvió `/apoderados`; mientras carga o si falla está vacío y los nombres van sin marca. */
  apoderados: Map<string, ApoderadoVista>;
  seleccionada: Seleccion | null;
  alCita: (id: string, ancla: HTMLElement) => void;
  alApoderado: (id: string, ancla: HTMLElement) => void;
}

interface PropsSegmentos extends ContextoDocumento {
  segmentos: Segmento[];
}

/** Las marcas del texto se comportan como botones: Enter y Espacio las abren sin desplazar la página. */
function teclaDeBoton(abrir: (ancla: HTMLElement) => void) {
  return (e: JSX.TargetedKeyboardEvent<HTMLElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    abrir(e.currentTarget);
  };
}

/** El nombre con su última palabra aparte: el glifo del estado va pegado a ella y nunca baja solo al renglón siguiente. */
function conCola(texto: string): ComponentChildren {
  const cola = /\S+\s*$/.exec(texto);
  if (!cola) return texto;
  return (
    <>
      {texto.slice(0, cola.index)}
      <span class="bor-apo-cola">{cola[0]}</span>
    </>
  );
}

function Fragmento({ segmento, citas, apoderados, seleccionada, alCita, alApoderado }: ContextoDocumento & { segmento: Segmento }) {
  const texto = segmento.texto.replace(/\t/g, " ");
  const conFormato = (contenido: ComponentChildren): ComponentChildren => {
    let nodo = contenido;
    if (segmento.negrita) nodo = <strong>{nodo}</strong>;
    if (segmento.cursiva) nodo = <em>{nodo}</em>;
    return nodo;
  };
  const nodo = conFormato(texto);
  const cita = segmento.cita_id ? citas.get(segmento.cita_id) : undefined;
  if (cita) {
    const activa = seleccionada?.tipo === "cita" && seleccionada.id === cita.id;
    return (
      <span
        role="button"
        tabIndex={0}
        class={cx("bor-cita", cita.estado, activa && "sel")}
        data-cita={cita.id}
        aria-pressed={activa}
        aria-haspopup="dialog"
        aria-controls={activa ? "bor-detalle" : undefined}
        onClick={(e) => alCita(cita.id, e.currentTarget)}
        onKeyDown={teclaDeBoton((ancla) => alCita(cita.id, ancla))}
      >
        {nodo}
        <span class="solo-lectura"> ({ETIQUETA_ESTADO_CITA[cita.estado]})</span>
      </span>
    );
  }
  const apoderado = segmento.apoderado_id ? apoderados.get(segmento.apoderado_id) : undefined;
  if (!apoderado) return <>{nodo}</>;
  const activo = seleccionada?.tipo === "apoderado" && seleccionada.id === apoderado.id;
  return (
    <span
      role="button"
      tabIndex={0}
      class={cx("bor-apo", CLASE_MARCA[apoderado.estado], activo && "sel")}
      data-apoderado={apoderado.id}
      aria-pressed={activo}
      aria-haspopup="dialog"
      aria-controls={activo ? "bor-detalle" : undefined}
      onClick={(e) => alApoderado(apoderado.id, e.currentTarget)}
      onKeyDown={teclaDeBoton((ancla) => alApoderado(apoderado.id, ancla))}
    >
      {conFormato(conCola(texto))}
      <span class="solo-lectura"> ({LECTURA_MARCA[apoderado.estado]})</span>
    </span>
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
  plantilla: boolean;
}

export function Documento({ vista, plantilla, ...contexto }: PropsDocumento) {
  const total = vista.paginas.length;
  return (
    <Hoja etiqueta="Borrador del fallo, secciones I a V" class={cx("bor-hoja", plantilla && "bor-con-plantilla")}>
      <span class="bor-sello">Borrador · aún no es el fallo</span>
      {vista.paginas.map((pagina, i) => {
        const cuerpo = pagina.bloques.filter((b) => b.tipo !== "pie");
        const pie = i === total - 1 ? pagina.bloques.filter((b) => b.tipo === "pie") : [];
        return (
          <div key={i} class="bor-pagina" data-pagina={`Página ${i + 1} de ${total}`}>
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
