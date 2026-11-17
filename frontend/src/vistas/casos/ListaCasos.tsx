import type { ComponentChildren } from "preact";
import { Fragment } from "preact";
import { useEffect, useId, useMemo, useRef, useState } from "preact/hooks";
import type { CasoResumen } from "../../api/contrato";
import { plural, pluralizar } from "../../estado";
import { consulta, reemplazarConsulta, ruta } from "../../rutas";
import { Boton, cx, Vacio } from "../../ui";
import { esPropia, estadoDe, generales, PROCESOS, procesoDe, propias as propiasDe, type TipoProceso } from "./facetas";
import { hrefCaso } from "./agrupar";
import { Ficha, FichaCompacta } from "./Ficha";
import {
  activos,
  AGRUPACIONES,
  agruparPor,
  contar,
  conteoPestanas,
  datosFila,
  deserializar,
  deshacer,
  elegirEstado,
  inicial,
  limpiar,
  ORDENES,
  ordenarPor,
  pasa,
  predicados,
  procesoActivo,
  quitarFiltro,
  serializar,
  sugerencia,
  type Agrupacion,
  type Filtros,
  type Orden,
} from "./filtros";
import { IconoLupa, IconoProceso } from "./iconos";
import { Tablero } from "./Tablero";
import "./lista.css";

export interface PropsListaCasos {
  casos: readonly CasoResumen[];
  /** Página de un proceso: lo fija, agrupa por estado y se titula «Casos». Sin él es «Mi trabajo» de Inicio. */
  proceso?: TipoProceso;
  /** Ocupa el lugar de la lista mientras carga o si falló. */
  aviso?: ComponentChildren;
  /** Se muestra si no hay ningún caso. */
  vacio?: ComponentChildren;
}

const PAGINA = 10;
const CLAVE_DENSIDAD = "judicabot:densidad";

function leerCompacta(): boolean {
  try {
    return localStorage.getItem(CLAVE_DENSIDAD) === "compacta";
  } catch {
    return false;
  }
}

function guardarCompacta(compacta: boolean): void {
  try {
    localStorage.setItem(CLAVE_DENSIDAD, compacta ? "compacta" : "fichas");
  } catch {
    return;
  }
}

export function ListaCasos({ casos, proceso, aviso, vacio }: PropsListaCasos) {
  const id = useId();
  return (
    <section class="trabajo" aria-labelledby={id}>
      {aviso || casos.length === 0 ? (
        <>
          <div class="cabeza-trabajo">
            <h2 id={id}>{proceso ? "Casos" : "Mi trabajo"}</h2>
          </div>
          {aviso ?? vacio}
        </>
      ) : (
        <Lista casos={casos} proceso={proceso} id={id} />
      )}
    </section>
  );
}

function Lista({ casos, proceso, id }: { casos: readonly CasoResumen[]; proceso?: TipoProceso; id: string }) {
  const defaults = useMemo(() => inicial(proceso), [proceso]);
  const leer = (q: string) => deserializar(q, { defaults, casos });
  const [filtros, setFiltros] = useState(() => leer(consulta.peek()));
  const [guardado, setGuardado] = useState<Filtros | null>(null);
  const [limite, setLimite] = useState(PAGINA);
  const [compacta, setCompacta] = useState(leerCompacta);
  const escrita = useRef(consulta.peek());
  const vista = useRef(ruta.peek().vista);
  const cuenta = useRef<HTMLParagraphElement>(null);
  const buscar = useRef<HTMLInputElement>(null);
  const enfocar = useRef(false);
  /** Enlace del primer caso que trajo «Mostrar más», para no perder el foco al desmontarse el botón. */
  const primeroNuevo = useRef<string | null>(null);

  // Atrás/Adelante u otro cambio de la consulta que no escribió esta lista.
  const externa = consulta.value;
  useEffect(() => {
    if (externa === escrita.current || ruta.peek().vista !== vista.current) return;
    escrita.current = externa;
    setFiltros(leer(externa));
    setGuardado(null);
    setLimite(PAGINA);
  }, [externa]);

  useEffect(() => {
    if (!enfocar.current) return;
    enfocar.current = false;
    (cuenta.current?.querySelector("button") ?? buscar.current)?.focus();
  });

  useEffect(() => {
    const href = primeroNuevo.current;
    if (!href) return;
    primeroNuevo.current = null;
    const enlaces = cuenta.current?.closest(".trabajo")?.querySelectorAll<HTMLAnchorElement>("a[href]") ?? [];
    [...enlaces].find((a) => a.getAttribute("href") === href)?.focus();
  });

  const escribir = (f: Filtros) => {
    setFiltros(f);
    escrita.current = serializar(f, defaults);
    // Mientras carga la página siguiente esta lista sigue montada: no escribir en la URL ajena.
    if (ruta.peek().vista === vista.current) reemplazarConsulta(escrita.current);
  };
  const cambiar = (f: Filtros) => {
    escribir(f);
    setGuardado(null);
    setLimite(PAGINA);
  };
  const cambiarYEnfocar = (f: Filtros, nuevoGuardado: Filtros | null = null) => {
    cambiar(f);
    setGuardado(nuevoGuardado);
    enfocar.current = true;
  };
  const verCompacta = (si: boolean) => {
    setCompacta(si);
    guardarCompacta(si);
  };

  const hoy = new Date();
  const proc = procesoActivo(filtros, casos);
  const alcance = useMemo(() => (filtros.proceso === "todos" ? casos : casos.filter((c) => procesoDe(c) === filtros.proceso)), [casos, filtros.proceso]);
  const facetas = useMemo(() => generales(proc, alcance), [proc, alcance]);
  const propias = propiasDe(proc);
  const todas = [...facetas, ...propias];
  const preds = predicados(filtros, hoy);
  const visibles = casos.filter((c) => pasa(c, preds));
  const aplicados = activos(filtros, defaults, todas);
  const presentes = new Set(casos.map(procesoDe));
  const ordenados = ordenarPor(visibles, filtros.orden);
  const grupos = agruparPor(ordenados, filtros.agrupar, limite);
  const agrupado = filtros.agrupar !== "ninguno";
  const nivel = agrupado ? 4 : 3;
  const restantes = ordenados.length - Math.min(limite, ordenados.length);

  let sinResultados: ComponentChildren = null;
  if (visibles.length === 0) {
    const terminados = aplicados.length === 0 ? contar(casos, preds, "estado", (c) => estadoDe(c) === "terminado") : 0;
    const sug = terminados ? null : sugerencia(casos, filtros, defaults, todas, hoy);
    const soloBusqueda = aplicados.length === 1 && aplicados[0]!.clave === "q";
    sinResultados = terminados ? (
      <Vacio
        titulo="No hay casos abiertos"
        accion={
          <Boton variante="primario" onClick={() => cambiarYEnfocar(elegirEstado(filtros, "terminado"))}>
            Ver los terminados ({terminados})
          </Boton>
        }
      />
    ) : (
      <Vacio
        class="sin-resultados"
        titulo={soloBusqueda ? `Ningún caso coincide con «${filtros.q.trim()}».` : "Ningún caso coincide con estos filtros."}
        accion={
          sug && (
            <Boton variante="primario" onClick={() => cambiarYEnfocar(quitarFiltro(filtros, sug.clave, defaults))}>
              Quitar {sug.texto} · {plural(sug.n, "caso")}
            </Boton>
          )
        }
      />
    );
  }

  const pestanas = !proceso && presentes.size > 1 && conteoPestanas(casos, preds);

  return (
    <>
      <div class="cabeza-trabajo">
        <h2 id={id}>{proceso ? "Casos" : "Mi trabajo"}</h2>
        <label class="buscar">
          <IconoLupa />
          <input
            ref={buscar}
            type="search"
            autocomplete="off"
            placeholder="Radicado, partes o juzgado"
            aria-label="Buscar casos"
            value={filtros.q}
            onInput={(e) => cambiar({ ...filtros, q: e.currentTarget.value })}
          />
        </label>
      </div>
      {pestanas && (
        <div class="pestanas" role="group" aria-label="Proceso">
          {PROCESOS.filter((p) => p.id === "todos" || presentes.has(p.id)).map((p) => (
            <button
              key={p.id}
              type="button"
              class="pestana"
              aria-pressed={filtros.proceso === p.id}
              onClick={() => cambiar({ ...filtros, proceso: p.id, sel: Object.fromEntries(Object.entries(filtros.sel).filter(([k]) => !esPropia(k))) })}
            >
              {p.id !== "todos" && <IconoProceso tipo={p.id} />}
              {p.corto}
              <span class="conteo">{pestanas[p.id]}</span>
            </button>
          ))}
        </div>
      )}
      <Tablero
        casos={casos}
        filtros={filtros}
        defaults={defaults}
        preds={preds}
        generales={facetas}
        propias={propias}
        proceso={proc}
        hoy={hoy}
        visibles={visibles.length}
        estadoCambiado={aplicados.some((a) => a.clave === "estado")}
        cambiar={cambiar}
      />
      <div class="resultados">
        <p class="lista-cuenta" ref={cuenta}>
          <span role="status">
            <b>{visibles.length}</b> {aplicados.length ? `de ${plural(alcance.length, "caso")}` : pluralizar(visibles.length, "caso abierto", "casos abiertos")}
          </span>
          {aplicados.length > 0 && (
            <button
              type="button"
              class="enlace"
              onClick={() => {
                const r = limpiar(filtros, defaults);
                cambiarYEnfocar(r.filtros, r.deshacer);
              }}
            >
              Limpiar filtros
            </button>
          )}
          {guardado && aplicados.length === 0 && (
            <>
              Filtros limpiados.
              <button type="button" class="enlace" onClick={() => cambiarYEnfocar(deshacer(filtros, guardado))}>
                Deshacer
              </button>
            </>
          )}
        </p>
        <div class="lista-orden">
          <label>
            Ordenar
            <select value={filtros.orden} onChange={(e) => escribir({ ...filtros, orden: e.currentTarget.value as Orden })}>
              {ORDENES.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.etiqueta}
                </option>
              ))}
            </select>
          </label>
          <label>
            Agrupar
            <select value={filtros.agrupar} onChange={(e) => escribir({ ...filtros, agrupar: e.currentTarget.value as Agrupacion })}>
              {AGRUPACIONES.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.etiqueta}
                </option>
              ))}
            </select>
          </label>
          <div class="densidad" role="group" aria-label="Densidad de la lista">
            <button type="button" aria-pressed={!compacta} aria-label="Fichas" title="Fichas" onClick={() => verCompacta(false)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true">
                <rect x="3" y="4" width="18" height="7" rx="2" />
                <rect x="3" y="13" width="18" height="7" rx="2" />
              </svg>
            </button>
            <button type="button" aria-pressed={compacta} aria-label="Compacta" title="Compacta" onClick={() => verCompacta(true)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                <path d="M4 6h16M4 10h16M4 14h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
      {sinResultados}
      {grupos.map((g) => {
        const fichas = (
          <div class={cx("fichas", compacta && "compacta")}>
            {g.casos.map((caso) =>
              compacta ? (
                <FichaCompacta key={caso.id} caso={caso} nivel={nivel} mostrarProceso={!proc} />
              ) : (
                <Ficha key={caso.id} caso={caso} nivel={nivel} mostrarProceso={!proc} datos={datosFila(caso, filtros)} />
              ),
            )}
          </div>
        );
        return agrupado ? (
          <section key={g.id} class="grupo" aria-labelledby={`${id}-${g.id}`}>
            <h3 id={`${id}-${g.id}`}>
              {g.titulo} <span>{g.total}</span>
            </h3>
            {fichas}
          </section>
        ) : (
          <Fragment key={g.id}>{fichas}</Fragment>
        );
      })}
      {restantes > 0 && (
        <div class="mas">
          <Boton
            onClick={() => {
              primeroNuevo.current = hrefCaso(ordenados[limite]!);
              setLimite(limite + PAGINA);
            }}
          >Mostrar {Math.min(PAGINA, restantes)} más</Boton>
        </div>
      )}
    </>
  );
}
