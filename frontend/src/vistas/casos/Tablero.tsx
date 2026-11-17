import type { ComponentChildren } from "preact";
import { useId, useRef, useState } from "preact/hooks";
import type { CasoResumen } from "../../api/contrato";
import { plural } from "../../estado";
import { Boton, cx, Desplegable } from "../../ui";
import { plano } from "./agrupar";
import { ESTADOS, infoProceso, TRABAJADO, type Faceta, type TipoProceso } from "./facetas";
import { alternar, conteoEstados, conteoOpciones, elegirEstado, fijar, quitarFiltro, textoFecha, type Filtros, type Predicado } from "./filtros";
import { FiltroFecha } from "./FiltroFecha";
import { IconoProceso } from "./iconos";

export interface PropsTablero {
  /** Todos los casos de la lista; cada conteo ignora el filtro al que pertenece. */
  casos: readonly CasoResumen[];
  filtros: Filtros;
  defaults: Filtros;
  preds: readonly Predicado[];
  generales: readonly Faceta[];
  propias: readonly Faceta[];
  /** El proceso de las facetas propias. */
  proceso: TipoProceso | null;
  hoy: Date;
  /** Casos que pasan todos los filtros, para «Listo · N casos». */
  visibles: number;
  estadoCambiado: boolean;
  cambiar: (f: Filtros) => void;
}

const X = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);

interface PropsPastilla {
  corto: string;
  etiqueta: string;
  valor: string;
  valorTitulo: string;
  ancho?: boolean;
  abierto: boolean;
  setAbierto: (abierto: boolean) => void;
  quitar: () => void;
  visibles: number;
  children: ComponentChildren;
}

/** Pastilla plegada: muestra su valor y su ✕; al tocarla abre el control del filtro. */
function Pastilla({ corto, etiqueta, valor, valorTitulo, ancho, abierto, setAbierto, quitar, visibles, children }: PropsPastilla) {
  const caja = useRef<HTMLDivElement>(null);
  const quitarConFoco = () => {
    caja.current?.querySelector<HTMLElement>(".desplegable-boton")?.focus();
    quitar();
  };
  return (
    <div ref={caja} class={cx("pastilla", valor && "con-valor")}>
      <Desplegable
        etiqueta={
          <>
            {valor ? `${corto}: ` : corto}
            {valor && (
              <span class="pastilla-valor" title={valorTitulo}>
                {valor}
              </span>
            )}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </>
        }
        titulo={etiqueta}
        abierto={abierto}
        onAbrir={() => setAbierto(true)}
        onCerrar={() => setAbierto(false)}
        ancho={ancho}
        pie={
          <>
            <button type="button" class="enlace" onClick={quitar}>
              Quitar
            </button>
            <Boton variante="primario" class="chico" onClick={() => setAbierto(false)}>
              Listo · {plural(visibles, "caso")}
            </Boton>
          </>
        }
      >
        {children}
      </Desplegable>
      {valor && (
        <button type="button" class="pastilla-x" aria-label={`Quitar el filtro ${etiqueta}`} onClick={quitarConFoco}>
          {X}
        </button>
      )}
    </div>
  );
}

interface PropsOpciones {
  faceta: Faceta;
  casos: readonly CasoResumen[];
  preds: readonly Predicado[];
  filtros: Filtros;
  cambiar: (f: Filtros) => void;
}

/** Casillas de una faceta; solo se monta con el desplegable abierto, así que solo entonces cuenta. */
function ListaOpciones({ faceta, casos, preds, filtros, cambiar }: PropsOpciones) {
  const [busqueda, setBusqueda] = useState("");
  const conteo = conteoOpciones(casos, preds, faceta);
  const elegidos = filtros.sel[faceta.clave] ?? [];
  const q = plano(busqueda.trim());
  const opciones = q ? faceta.opciones.filter((o) => plano(o.etiqueta).includes(q)) : faceta.opciones;
  return (
    <>
      {faceta.tipo === "buscable" && (
        <input
          type="search"
          class="pop-buscar"
          autocomplete="off"
          placeholder="Buscar…"
          aria-label={`Buscar en ${faceta.etiqueta}`}
          value={busqueda}
          onInput={(e) => setBusqueda(e.currentTarget.value)}
        />
      )}
      {opciones.map((o) => {
        const n = conteo.get(o.id) ?? 0;
        const on = elegidos.includes(o.id);
        return (
          <label key={o.id} class={cx("op", n === 0 && !on && "cero")}>
            <input type="checkbox" checked={on} title={plural(n, "caso")} onChange={() => cambiar(alternar(filtros, faceta.clave, o.id))} />
            {o.etiqueta}
            <span class="conteo" aria-hidden="true">
              {n}
            </span>
          </label>
        );
      })}
      {opciones.length === 0 && <p class="pop-nada">Ninguna opción coincide.</p>}
    </>
  );
}

export function Tablero(props: PropsTablero) {
  const { casos, filtros, defaults, preds, generales, propias, proceso, hoy, visibles, estadoCambiado, cambiar } = props;
  const id = useId();
  const [abierto, setAbierto] = useState<string | null>(null);
  const control = (clave: string) => ({
    abierto: abierto === clave,
    setAbierto: (si: boolean) => setAbierto((actual) => (si ? clave : actual === clave ? null : actual)),
    quitar: () => cambiar(quitarFiltro(filtros, clave, defaults)),
    visibles,
  });
  const n = conteoEstados(casos, preds);

  const pastilla = (f: Faceta) => {
    const elegidos = filtros.sel[f.clave] ?? [];
    if (f.tipo === "interruptor" && f.activo) {
      const on = elegidos.includes(f.activo);
      const cuantos = conteoOpciones(casos, preds, f).get(f.activo) ?? 0;
      return (
        <button key={f.clave} type="button" class="interruptor" aria-pressed={on} title={plural(cuantos, "caso")} onClick={() => cambiar(fijar(filtros, f.clave, on ? [] : [f.activo!]))}>
          <span class="casilla" aria-hidden="true">
            {on && (
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2.5 6.2l2.3 2.3 4.7-5" />
              </svg>
            )}
          </span>
          {f.corto}
          <span class="conteo" aria-hidden="true">
            {cuantos}
          </span>
        </button>
      );
    }
    const nombres = elegidos.map((e) => f.opciones.find((o) => o.id === e)?.etiqueta ?? e);
    return (
      <Pastilla
        key={f.clave}
        corto={f.corto}
        etiqueta={f.etiqueta}
        valor={nombres.length ? `${nombres[0]}${nombres.length > 1 ? ` +${nombres.length - 1}` : ""}` : ""}
        valorTitulo={nombres.join(", ")}
        ancho={f.tipo === "buscable"}
        {...control(f.clave)}
      >
        <ListaOpciones faceta={f} casos={casos} preds={preds} filtros={filtros} cambiar={cambiar} />
      </Pastilla>
    );
  };

  const fecha = textoFecha(filtros);
  const nPropios = propias.filter((f) => filtros.sel[f.clave]?.length).length;

  return (
    <div class="tablero">
      <div class="triage" role="group" aria-labelledby={`${id}-estado`}>
        <p class="rotulo">
          <span id={`${id}-estado`}>Estado</span>
          {estadoCambiado ? (
            <button type="button" class="enlace" onClick={() => cambiar(quitarFiltro(filtros, "estado", defaults))}>
              Ver todos los abiertos
            </button>
          ) : (
            <small>Toque uno para ver solo ese; luego sume otros.</small>
          )}
        </p>
        <div class="franja">
          {ESTADOS.map((e) => {
            const on = filtros.estado.includes(e.id);
            const oculto = e.id === "terminado" && !on;
            return (
              <button
                key={e.id}
                type="button"
                class={`seg-estado e-${e.id}${n[e.id] === 0 ? " cero" : ""}`}
                style={{ flexGrow: Math.max(n[e.id], 1) }}
                aria-pressed={on}
                aria-label={e.etiqueta}
                title={`${plural(n[e.id], "caso")}${on ? "" : oculto ? ", ocultos" : ", no se muestran"}`}
                onClick={() => cambiar(elegirEstado(filtros, e.id))}
              >
                <b>{n[e.id]}</b>
                <span>{oculto ? `${e.etiqueta} · ocultos` : e.etiqueta}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div class="carriles">
        <div class="carril" role="group" aria-label="Filtros generales">
          <p class="carril-cab">Generales</p>
          <div class="pastillas">
            <Pastilla corto={TRABAJADO.corto} etiqueta={TRABAJADO.etiqueta} valor={fecha} valorTitulo={fecha} ancho {...control(TRABAJADO.clave)}>
              <FiltroFecha filtros={filtros} casos={casos} preds={preds} hoy={hoy} cambiar={cambiar} />
            </Pastilla>
            {generales.map(pastilla)}
          </div>
        </div>
        {proceso && propias.length > 0 && (
          <div class="carril propio" role="group" aria-label={`Filtros propios de ${infoProceso(proceso).corto}`}>
            <p class="carril-cab">
              <span class="carril-ico" aria-hidden="true">
                <IconoProceso tipo={proceso} />
              </span>
              Propios de {infoProceso(proceso).corto}
              {nPropios > 0 && (
                <>
                  <span class="cuantos" aria-hidden="true" title={plural(nPropios, "filtro propio aplicado", "filtros propios aplicados")}>
                    {nPropios}
                  </span>
                  <span class="solo-lectura">{plural(nPropios, "filtro propio aplicado", "filtros propios aplicados")}</span>
                </>
              )}
            </p>
            <div class="pastillas">{propias.map(pastilla)}</div>
          </div>
        )}
      </div>
    </div>
  );
}
