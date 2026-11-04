import type { ComponentChildren, Ref } from "preact";
import { useState } from "preact/hooks";
import type { CitaVista } from "../../api/contrato";
import { plural, porcentaje } from "../../estado";
import { Boton, Chip, cx } from "../../ui";
import { conteoCitas, ETIQUETA_ESTADO_CITA } from "./datos";
import type { EntradaIndice, ItemRevision } from "./tipos";

const TONO_CITA = { verificada: "ok", revisar: "alerta", rechazada: "mal" } as const;
const VISIBLES = 5;

export interface PropsDetalleCita {
  cita: CitaVista;
  titulo: Ref<HTMLHeadingElement>;
  onCerrar: () => void;
}

export function DetalleCita({ cita, titulo, onCerrar }: PropsDetalleCita) {
  return (
    <section
      id="bor-detalle"
      class="bor-detalle"
      aria-labelledby="bor-detalle-titulo"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCerrar();
        }
      }}
    >
      <h3 id="bor-detalle-titulo" ref={titulo} tabIndex={-1}>
        {cita.fuente || cita.id}
      </h3>
      <div>
        <Chip tono={TONO_CITA[cita.estado]}>{ETIQUETA_ESTADO_CITA[cita.estado]}</Chip>
      </div>
      {cita.texto && <q>{cita.texto}</q>}
      <dl>
        <dt>Fuente</dt>
        <dd>{cita.fuente || "—"}</dd>
        <dt>Cobertura</dt>
        <dd>{porcentaje(cita.cobertura)}</dd>
        <dt>Estado</dt>
        <dd>{ETIQUETA_ESTADO_CITA[cita.estado]}</dd>
      </dl>
      {cita.detalle && <p class={cx("bor-detalle-motivo", cita.estado)}>{cita.detalle}</p>}
      <div>
        <Boton onClick={onCerrar}>Cerrar</Boton>
      </div>
    </section>
  );
}

export interface PropsRiel {
  indice: EntradaIndice[];
  activa: string | null;
  alSeccion: (id: string) => void;
  origen: boolean;
  alOrigen: (valor: boolean) => void;
  citas: CitaVista[];
  items: ItemRevision[];
  alVerCita: (id: string, disparador: HTMLElement) => void;
  puedeCorregir: boolean;
  motivoNoCorregir: string | null;
  alCorregir: () => void;
  detalle: ComponentChildren;
  avisoEstado: string | null;
}

export function Riel({
  indice,
  activa,
  alSeccion,
  origen,
  alOrigen,
  citas,
  items,
  alVerCita,
  puedeCorregir,
  motivoNoCorregir,
  alCorregir,
  detalle,
  avisoEstado,
}: PropsRiel) {
  const [todos, setTodos] = useState(false);
  const conteo = conteoCitas(citas);
  const mostrados = todos ? items : items.slice(0, VISIBLES);
  return (
    <aside class="bor-riel" aria-label="Revisión del borrador">
      {detalle}
      <section aria-labelledby="bor-sec-secciones">
        <h2 id="bor-sec-secciones">Secciones</h2>
        <ul class="bor-indice">
          {indice.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                class={cx(e.sub && "sub-i")}
                aria-current={activa === e.id ? "location" : undefined}
                onClick={() => alSeccion(e.id)}
              >
                {e.titulo}
              </button>
            </li>
          ))}
        </ul>
        <label class="bor-origen-opcion">
          <input type="checkbox" checked={origen} onChange={(e) => alOrigen(e.currentTarget.checked)} />
          <span>
            <span class="bor-leyenda" aria-hidden="true" />
            Marcar el texto que sale de plantillas
          </span>
        </label>
        {origen && (
          <p class="bor-origen-nota">Sombreado: texto de plantilla. Sin sombrear: redactado por el modelo a partir del expediente.</p>
        )}
      </section>
      <section aria-labelledby="bor-sec-revisar">
        <h2 id="bor-sec-revisar">Qué conviene revisar</h2>
        {citas.length > 0 && (
          <div class="bor-conteo">
            <Chip tono="ok">{plural(conteo.verificada, "verificada")}</Chip>
            <Chip tono="alerta">{conteo.revisar} con alerta</Chip>
            <Chip tono="mal">{plural(conteo.rechazada, "no verificada", "no verificadas")}</Chip>
          </div>
        )}
        {avisoEstado && <p class="sub bor-nota">{avisoEstado}</p>}
        {items.length === 0 ? (
          <p class="sub">Nada pendiente en lo que el sistema pudo comprobar.</p>
        ) : (
          <ul class="bor-lista-rev">
            {mostrados.map((item) => (
              <li key={item.clave}>
                <Chip tono={item.tono}>{item.etiqueta}</Chip>
                <span>
                  {item.texto}
                  {item.detalle && <small>{item.detalle}</small>}
                  {item.cita && (
                    <Boton variante="fantasma" onClick={(e) => alVerCita(item.cita as string, e.currentTarget)}>
                      Ver en el texto
                    </Boton>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        {items.length > VISIBLES && (
          <Boton variante="fantasma" onClick={() => setTodos(!todos)} aria-expanded={todos}>
            {todos ? "Mostrar menos" : `Ver las ${items.length - VISIBLES} restantes`}
          </Boton>
        )}
      </section>
      <section aria-labelledby="bor-sec-corregir">
        <h2 id="bor-sec-corregir">El borrador no sirve</h2>
        <p class="sub bor-nota">Indique qué debe corregirse y el modelo vuelve a redactar esa parte.</p>
        <Boton onClick={alCorregir} disabled={!puedeCorregir}>
          Pedir correcciones
        </Boton>
        {motivoNoCorregir && <p class="sub bor-nota">{motivoNoCorregir}</p>}
      </section>
    </aside>
  );
}
