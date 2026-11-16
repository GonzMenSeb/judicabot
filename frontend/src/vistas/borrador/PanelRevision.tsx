import { useEffect, useRef, useState } from "preact/hooks";
import { porcentaje } from "../../estado";
import { Boton, cx } from "../../ui";
import "./panel.css";
import type { DetalleRevision, FilaJev, ItemRevision, NivelRevision } from "./tipos";

export interface PropsPanelRevision {
  items: ItemRevision[];
  revisados: ReadonlySet<string>;
  alRevisar: (clave: string) => void;
  abierta: string | null;
  alAbrir: (clave: string | null) => void;
  seleccionada: string | null;
  alVerEnTexto: (citaId: string, desde: HTMLElement) => void;
  umbralJev?: number;
  avisoEstado: string | null;
  abiertoMovil: boolean;
  onCerrarMovil: () => void;
}

type NivelPendiente = Exclude<NivelRevision, "ok">;

const NIVELES: { id: NivelPendiente; nombre: string }[] = [
  { id: "mal", nombre: "Corregir antes de firmar" },
  { id: "alerta", nombre: "Revisar" },
  { id: "info", nombre: "Para tener en cuenta" },
];

const TRAZO = { fill: "none", stroke: "currentColor", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" } as const;

function IconoCheck() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" stroke-width="3" {...TRAZO}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

function IconoChevron() {
  return (
    <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" stroke-width="2" {...TRAZO}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function IconoIr() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" stroke-width="2" {...TRAZO}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function IconoExterno() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" stroke-width="2" {...TRAZO}>
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

function IconoCerrar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2" {...TRAZO}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function Lectura({ etiqueta, principal, nota }: { etiqueta: string; principal: string; nota: string | null }) {
  return (
    <div>
      <span class="que">{etiqueta}</span>
      <strong>{principal}</strong>
      {nota && <small>{nota}</small>}
    </div>
  );
}

function DetalleJev({ fila, umbral }: { fila: FilaJev; umbral: number | undefined }) {
  const confianza = fila.jev.confianza === null ? null : `${porcentaje(fila.jev.confianza)} de confianza`;
  const notaJev = [confianza, fila.jev.nota].filter(Boolean).join(", ") || null;
  return (
    <>
      <div class="bor-comparar">
        <Lectura etiqueta="El borrador dice" principal={fila.borrador.principal ?? "Sin dato"} nota={fila.borrador.secundario} />
        <Lectura etiqueta="Jev lee en el expediente" principal={fila.jev.principal ?? "Sin lectura"} nota={notaJev} />
      </div>
      {fila.estado === "difiere" && fila.motivo && <p class="bor-nota alerta">{fila.motivo}</p>}
      <p class="bor-nota">
        Jev leyó por su cuenta el fallo de primera instancia y la impugnación.
        {umbral !== undefined && ` Solo compara con al menos ${porcentaje(umbral)} de confianza.`}
      </p>
    </>
  );
}

function Detalle({ detalle, umbral, alVerEnTexto }: { detalle: DetalleRevision; umbral: number | undefined; alVerEnTexto: PropsPanelRevision["alVerEnTexto"] }) {
  if (detalle.tipo === "cita") {
    const { cita, motivos } = detalle;
    return (
      <>
        {cita.texto && <q>{cita.texto}</q>}
        <div class="bor-medidor">
          <span>Cobertura</span>
          <span class="riel">
            <i class={cita.estado} style={{ width: `${Math.round((cita.cobertura ?? 0) * 100)}%` }} />
          </span>
          <b>{porcentaje(cita.cobertura)}</b>
        </div>
        {motivos.length > 0 && (
          <ul class={cx("bor-motivos", cita.estado)}>
            {motivos.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}
        <div class="bor-acciones-fila">
          <Boton variante="fantasma" onClick={(e) => alVerEnTexto(cita.id, e.currentTarget)}>
            Ver en el texto <IconoIr />
          </Boton>
          {cita.estado === "verificada" && cita.url && (
            <a class="btn fantasma" href={cita.url} target="_blank" rel="noopener noreferrer">
              Abrir en la relatoría <IconoExterno />
              <span class="solo-lectura"> (se abre en una pestaña nueva)</span>
            </a>
          )}
        </div>
      </>
    );
  }
  if (detalle.tipo === "jev") return <DetalleJev fila={detalle.fila} umbral={umbral} />;
  if (detalle.tipo === "archivo") {
    return (
      <>
        <code class="bor-archivo">{detalle.archivo}</code>
        <p class="bor-nota">{detalle.nota}</p>
      </>
    );
  }
  return (
    <div class="bor-comparar">
      {detalle.lecturas.map((lectura) => (
        <div key={lectura.etiqueta}>
          <span class="que">{lectura.etiqueta}</span>
          {lectura.valores.length > 1 ? (
            <ul>
              {lectura.valores.map((valor, i) => (
                <li key={i}>{valor}</li>
              ))}
            </ul>
          ) : (
            <strong>{lectura.valores[0] ?? "—"}</strong>
          )}
        </div>
      ))}
    </div>
  );
}

interface PropsFila {
  item: ItemRevision;
  hecha: boolean;
  abierta: boolean;
  activa: boolean;
  umbral: number | undefined;
  alRevisar: (clave: string) => void;
  alAbrir: (clave: string | null) => void;
  alVerEnTexto: PropsPanelRevision["alVerEnTexto"];
}

function Fila({ item, hecha, abierta, activa, umbral, alRevisar, alAbrir, alVerEnTexto }: PropsFila) {
  const expandida = abierta && item.detalle !== null;
  const contenido = (
    <>
      <span class="bor-fila-tipo">{item.origen}</span>
      <span class="bor-fila-titulo">{item.titulo}</span>
      {item.linea && !expandida && <span class={cx("bor-fila-sub", item.lineaCompleta && "completa")}>{item.linea}</span>}
    </>
  );
  return (
    <li class={cx("bor-fila", `n-${item.nivel}`, expandida && "abierta", hecha && "hecha", activa && "bor-fila-activa")}>
      {item.nivel === "ok" ? (
        <span class="bor-marca-revisado fija" aria-hidden="true">
          <IconoCheck />
        </span>
      ) : (
        <button
          type="button"
          class="bor-marca-revisado"
          aria-pressed={hecha}
          title={hecha ? "Marcar como pendiente" : "Marcar como revisado"}
          onClick={() => alRevisar(item.clave)}
        >
          <IconoCheck />
          <span class="solo-lectura">Revisado: {item.titulo}</span>
        </button>
      )}
      {item.detalle ? (
        <button type="button" class="bor-fila-boton" aria-expanded={expandida} onClick={() => alAbrir(expandida ? null : item.clave)}>
          {contenido}
          <IconoChevron />
        </button>
      ) : (
        <div class="bor-fila-boton">{contenido}</div>
      )}
      {expandida && item.detalle && (
        <div class="bor-fila-detalle">
          <Detalle detalle={item.detalle} umbral={umbral} alVerEnTexto={alVerEnTexto} />
        </div>
      )}
    </li>
  );
}

export function PanelRevision({
  items,
  revisados,
  alRevisar,
  abierta,
  alAbrir,
  seleccionada,
  alVerEnTexto,
  umbralJev,
  avisoEstado,
  abiertoMovil,
  onCerrarMovil,
}: PropsPanelRevision) {
  const [verComprobado, setVerComprobado] = useState(false);
  const cuerpo = useRef<HTMLDivElement>(null);

  const pendientes = NIVELES.flatMap((nivel) => items.filter((i) => i.nivel === nivel.id));
  const comprobados = items.filter((i) => i.nivel === "ok");
  const hechos = pendientes.filter((i) => revisados.has(i.clave)).length;

  useEffect(() => {
    if (seleccionada === null || window.innerWidth < 1024) return;
    cuerpo.current?.querySelector(".bor-fila-activa")?.scrollIntoView?.({ block: "nearest" });
  }, [seleccionada]);

  const fila = (item: ItemRevision) => (
    <Fila
      key={item.clave}
      item={item}
      hecha={revisados.has(item.clave)}
      abierta={abierta === item.clave}
      activa={seleccionada !== null && item.cita === seleccionada}
      umbral={umbralJev}
      alRevisar={alRevisar}
      alAbrir={alAbrir}
      alVerEnTexto={alVerEnTexto}
    />
  );

  return (
    <aside id="bor-panel" class={cx("bor-panel", abiertoMovil && "abierto")} aria-labelledby="bor-panel-titulo">
      <div class="bor-panel-cabeza">
        <div class="bor-panel-cabeza-fila">
          <div>
            <h2 id="bor-panel-titulo">Antes de decidir</h2>
            <p class="bor-panel-resumen">
              {pendientes.length > 0 ? (
                <>
                  Lleva <b>{`${hechos} de ${pendientes.length}`}</b> revisados. Nada de esto bloquea la decisión.
                </>
              ) : (
                "Nada pendiente en lo que el sistema pudo comprobar."
              )}
            </p>
          </div>
          <button type="button" class="bor-panel-cerrar" aria-label="Cerrar la revisión" onClick={onCerrarMovil}>
            <IconoCerrar />
          </button>
        </div>
        {pendientes.length > 0 && (
          <div class="bor-progreso" role="progressbar" aria-label="Puntos revisados" aria-valuemin={0} aria-valuemax={pendientes.length} aria-valuenow={hechos}>
            {pendientes.map((i) => (
              <i key={i.clave} class={cx(`n-${i.nivel}`, revisados.has(i.clave) && "hecho")} />
            ))}
          </div>
        )}
      </div>
      {avisoEstado && <p class="bor-panel-aviso">{avisoEstado}</p>}
      <div class="bor-panel-cuerpo" ref={cuerpo}>
        {pendientes.length === 0 && (
          <div class="bor-todo-bien">
            <IconoCheck />
            <div>
              <b>Todo salió bien</b>
              <span>Las citas se encontraron en la relatoría y Jev coincide con el borrador.</span>
            </div>
          </div>
        )}
        {NIVELES.map((nivel) => {
          const grupo = pendientes.filter((i) => i.nivel === nivel.id);
          if (grupo.length === 0) return null;
          const quedan = grupo.filter((i) => !revisados.has(i.clave)).length;
          return (
            <section key={nivel.id} class="bor-nivel" aria-labelledby={`bor-nv-${nivel.id}`}>
              <div class={cx("bor-nivel-cabeza", `n-${nivel.id}`)}>
                <i />
                <h3 class="nombre" id={`bor-nv-${nivel.id}`}>
                  {nivel.nombre}
                </h3>
                <span class="cuenta">{quedan > 0 ? `${quedan} de ${grupo.length}` : "✓"}</span>
              </div>
              <ul class="bor-filas">{grupo.map(fila)}</ul>
            </section>
          );
        })}
        {comprobados.length > 0 && (
          <section class="bor-nivel">
            <button
              type="button"
              class="bor-nivel-cabeza n-ok plegable"
              aria-expanded={verComprobado}
              onClick={() => setVerComprobado((v) => !v)}
            >
              <i />
              <span class="nombre">Comprobado</span>
              <span class="cuenta">{comprobados.length}</span>
              <IconoChevron />
            </button>
            {verComprobado && <ul class="bor-filas">{comprobados.map(fila)}</ul>}
          </section>
        )}
      </div>
    </aside>
  );
}
