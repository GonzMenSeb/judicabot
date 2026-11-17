import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { Bloque, CitaVista, PiezaEdicion, Segmento, Vista } from "../../api/contrato";
import { mostrarToast } from "../../estado";
import { cx, Hoja } from "../../ui";
import { agruparBloques, ETIQUETA_ESTADO_CITA, unidadesDe } from "./datos";
import { type BorradorParrafo, EditorParrafo } from "./EditorParrafo";
import type { UnidadEdicion } from "./tipos";
import "./documento.css";

const COLUMNAS_ANCHA = 3;
const AYUDA_QUITADOS = "Se quitó al menos un párrafo del texto de la IA. Al editar este texto puede restaurarlo.";
const AVISO_PERDIDO = "El párrafo que estaba editando ya no existe en el borrador actualizado; su cambio no se guardó.";

export interface ContextoDocumento {
  citas: Map<string, CitaVista>;
  seleccionada: string | null;
  alCita: (id: string, ancla: HTMLElement) => void;
}

export interface EdicionDocumento {
  caso: string;
  activa: boolean;
  piezas: Record<string, PiezaEdicion>;
  conflictos: string[];
  recargar: () => Promise<void>;
  alSucio?: (sucio: boolean) => void;
}

interface ContextoUnidades extends EdicionDocumento {
  unidades: Map<string, UnidadEdicion>;
  ultimos: Map<string, string>;
  abierta: string | null;
  abrir: (unidad: UnidadEdicion) => void;
  cerrar: () => void;
  borrador: (unidad: UnidadEdicion, original: string) => BorradorParrafo;
  boton: (clave: string, el: HTMLButtonElement | null) => void;
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
    <span
      role="button"
      tabIndex={0}
      class={cx("bor-cita", cita.estado, activa && "sel")}
      data-cita={cita.id}
      aria-pressed={activa}
      aria-haspopup="dialog"
      aria-controls={activa ? "bor-detalle" : undefined}
      onClick={(e) => alCita(cita.id, e.currentTarget)}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        alCita(cita.id, e.currentTarget);
      }}
    >
      {nodo}
      <span class="solo-lectura"> ({ETIQUETA_ESTADO_CITA[cita.estado]})</span>
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

function IconoLapiz() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" />
    </svg>
  );
}

function BloqueUnidad({ bloque, unidades, ...contexto }: ContextoDocumento & { bloque: Bloque; unidades?: ContextoUnidades | undefined }) {
  const nodo = <BloqueTexto bloque={bloque} {...contexto} />;
  const unidad = unidades?.unidades.get(bloque.id);
  const datos = unidad ? unidades?.piezas[unidad.pieza] : undefined;
  if (!unidades || !unidad || !datos) return nodo;
  const { activa, abierta } = unidades;
  const primero = unidad.ids[0] === bloque.id;
  const editada = datos.editados.includes(unidad.parrafo);
  const quitados = datos.modificada && datos.editados.length === 0 && unidad.parrafo === 0;
  const editando = activa && abierta === unidad.clave;
  let contenido: ComponentChildren = nodo;
  if (editando) {
    contenido = primero ? (
      <div class="bor-unidad editando" data-unidad={unidad.clave}>
        <EditorParrafo
          caso={unidades.caso}
          pieza={unidad.pieza}
          parrafo={unidad.parrafo}
          borrador={unidades.borrador(unidad, datos.parrafos[unidad.parrafo] ?? "")}
          actual={datos.parrafos[unidad.parrafo] ?? ""}
          restaurable={datos.modificada}
          recargar={unidades.recargar}
          onCerrar={unidades.cerrar}
          alSucio={unidades.alSucio}
        />
      </div>
    ) : null;
  } else if (primero && (activa || editada || quitados)) {
    const motivo = unidades.conflictos.includes(unidad.pieza)
      ? "Resuelva el conflicto de este texto antes de editarlo."
      : abierta !== null
        ? "Guarde o cancele la edición abierta antes de editar otro párrafo."
        : undefined;
    contenido = (
      <div class={cx("bor-unidad", editada && "editada")} data-unidad={unidad.clave}>
        <div class="bor-unidad-marcas">
          {editada && (
            <span class="bor-editado" title="Este párrafo difiere del texto de la IA.">
              Editado
            </span>
          )}
          {quitados && (
            <span class="bor-editado" title={AYUDA_QUITADOS}>
              Con párrafos quitados
            </span>
          )}
          {activa && (
            <button
              type="button"
              class="bor-editar"
              ref={(el) => unidades.boton(unidad.clave, el)}
              aria-label="Editar párrafo"
              title={motivo}
              disabled={motivo !== undefined}
              onClick={() => unidades.abrir(unidad)}
            >
              <IconoLapiz />
              Editar
            </button>
          )}
        </div>
        {nodo}
      </div>
    );
  }
  if (!activa || datos.avisos.length === 0 || unidades.ultimos.get(unidad.pieza) !== bloque.id) return contenido;
  return (
    <>
      {contenido}
      <div class="bor-avisos-pieza">
        <b>Avisos sobre su edición</b>
        <ul>
          {datos.avisos.map((aviso, i) => (
            <li key={i}>{aviso}</li>
          ))}
        </ul>
      </div>
    </>
  );
}

function Bloques({ bloques, unidades, ...contexto }: ContextoDocumento & { bloques: Bloque[]; unidades?: ContextoUnidades | undefined }) {
  return (
    <>
      {agruparBloques(bloques).map((grupo, i) => {
        if (grupo.tipo === "bloque") {
          const unidad = unidades?.unidades.get(grupo.bloque.id);
          const clave = unidad?.ids[0] === grupo.bloque.id ? unidad.clave : grupo.bloque.id;
          return <BloqueUnidad key={clave} bloque={grupo.bloque} unidades={unidades} {...contexto} />;
        }
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
  edicion?: EdicionDocumento | undefined;
}

export function Documento({ vista, plantilla, edicion, ...contexto }: PropsDocumento) {
  const total = vista.paginas.length;
  const [abierta, setAbierta] = useState<string | null>(null);
  const botones = useRef(new Map<string, HTMLButtonElement>());
  const devolver = useRef<string | null>(null);
  const borrador = useRef<BorradorParrafo | null>(null);
  const conEdicion = edicion !== undefined;
  const mapa = useMemo(() => (conEdicion ? unidadesDe(vista) : null), [vista, conEdicion]);
  const ultimos = useMemo(() => {
    const ultimos = new Map<string, string>();
    for (const unidad of mapa?.values() ?? []) ultimos.set(unidad.pieza, unidad.ids[unidad.ids.length - 1] ?? "");
    return ultimos;
  }, [mapa]);
  const activa = edicion?.activa === true;
  const piezas = edicion?.piezas;
  const vigente = abierta === null || [...(mapa?.values() ?? [])].some((u) => u.clave === abierta && piezas?.[u.pieza] !== undefined);

  useEffect(() => {
    if (abierta !== null || devolver.current === null) return;
    botones.current.get(devolver.current)?.focus();
    devolver.current = null;
  }, [abierta]);

  useEffect(() => {
    if (!activa) {
      borrador.current = null;
      setAbierta(null);
    }
  }, [activa]);

  useEffect(() => {
    if (vigente) return;
    if (activa && borrador.current?.error) mostrarToast(AVISO_PERDIDO, { tipo: "error" });
    borrador.current = null;
    setAbierta(null);
  }, [vigente]);

  const unidades: ContextoUnidades | undefined =
    edicion && mapa
      ? {
          ...edicion,
          unidades: mapa,
          ultimos,
          abierta,
          abrir: (unidad) => setAbierta(unidad.clave),
          cerrar: () => {
            devolver.current = abierta;
            borrador.current = null;
            setAbierta(null);
          },
          borrador: (unidad, original) => {
            if (borrador.current?.clave !== unidad.clave) borrador.current = { clave: unidad.clave, original, texto: original, error: null };
            return borrador.current;
          },
          boton: (clave, el) => {
            if (el) botones.current.set(clave, el);
            else botones.current.delete(clave);
          },
        }
      : undefined;
  return (
    <Hoja etiqueta="Borrador del fallo, secciones I a V" class={cx("bor-hoja", plantilla && "bor-con-plantilla", activa && "bor-editando")}>
      <span class="bor-sello">Borrador · aún no es el fallo</span>
      {vista.paginas.map((pagina, i) => {
        const cuerpo = pagina.bloques.filter((b) => b.tipo !== "pie");
        const pie = i === total - 1 ? pagina.bloques.filter((b) => b.tipo === "pie") : [];
        return (
          <div key={i} class="bor-pagina" data-pagina={`Página ${i + 1} de ${total}`}>
            <Bloques bloques={cuerpo} unidades={unidades} {...contexto} />
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
