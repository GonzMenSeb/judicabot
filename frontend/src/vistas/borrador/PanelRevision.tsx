import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { porcentaje } from "../../estado";
import { Aviso, Boton, Chip, cx } from "../../ui";
import { mostrarDentro } from "./desplazar";
import "./panel.css";
import {
  type AccionesApoderado,
  BarraApoderados,
  DetalleApoderado,
  ResumenApoderados,
  TabApoderados,
  textoBloqueoPanel,
  type PanelApoderados,
} from "./TabApoderados";
import type { DetalleRevision, FilaJev, ItemRevision, NivelRevision, PedidoAjuste, PedidoVisor, Pestana, Seleccion } from "./tipos";

export interface PropsPanelRevision {
  items: ItemRevision[];
  revisados: ReadonlySet<string>;
  alRevisar: (clave: string) => void;
  abierta: string | null;
  alAbrir: (clave: string | null) => void;
  seleccionada: Seleccion | null;
  alVerEnTexto: (marca: Seleccion, desde: HTMLElement) => void;
  /** Abre el visor de evidencia en la página citada (el poder, el certificado de existencia o el escrito del abogado). */
  alVerEvidencia: (pedido: PedidoVisor, desde: HTMLElement) => void;
  /** Abre el diálogo de una corrección a mano de un abogado. */
  alCorregir: (pedido: PedidoAjuste, desde: HTMLElement) => void;
  /** «Deshacer el descarte» del poder de un abogado. */
  alRestaurarPoder: (id: string) => void;
  /** Los abogados cuyo nombre está marcado en el texto, para saber si «Ver en el texto» tiene adónde ir. */
  apoderadosEnTexto: ReadonlySet<string>;
  umbralJev?: number;
  avisoEstado: string | null;
  alertasLeidas?: boolean;
  abiertoMovil: boolean;
  onCerrarMovil: () => void;
  pestana: Pestana;
  alPestana: (pestana: Pestana) => void;
  apoderados: PanelApoderados;
}

const mismaMarca = (a: Seleccion | null, b: Seleccion | null): boolean => a !== null && b !== null && a.tipo === b.tipo && a.id === b.id;

const PESTANAS: { id: Pestana; nombre: string }[] = [
  { id: "citas", nombre: "Citas" },
  { id: "apoderados", nombre: "Apoderados" },
];

const FOCO = "button:not([disabled]):not([tabindex='-1']), a[href]:not([tabindex='-1']), [tabindex]:not([tabindex='-1'])";

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
      {fila.motivo && <p class={cx("bor-nota", fila.estado === "difiere" && "alerta")}>{fila.motivo}</p>}
      <p class="bor-nota">
        Jev leyó por su cuenta el fallo de primera instancia y la impugnación.
        {umbral !== undefined && ` Solo compara con al menos ${porcentaje(umbral)} de confianza.`}
      </p>
    </>
  );
}

interface PropsDetalle {
  detalle: DetalleRevision;
  umbral: number | undefined;
  alVerEnTexto: PropsPanelRevision["alVerEnTexto"];
  acciones: AccionesApoderado;
}

function Detalle({ detalle, umbral, alVerEnTexto, acciones }: PropsDetalle) {
  if (detalle.tipo === "apoderado") return <DetalleApoderado apoderado={detalle.apoderado} acciones={acciones} />;
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
          <Boton variante="fantasma" onClick={(e) => alVerEnTexto({ tipo: "cita", id: cita.id }, e.currentTarget)}>
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
  soloLectura: boolean;
  umbral: number | undefined;
  alRevisar: (clave: string) => void;
  alAbrir: (clave: string | null) => void;
  alVerEnTexto: PropsPanelRevision["alVerEnTexto"];
  acciones: AccionesApoderado;
}

function Fila({ item, hecha, abierta, activa, soloLectura, umbral, alRevisar, alAbrir, alVerEnTexto, acciones }: PropsFila) {
  const expandida = abierta && item.detalle !== null;
  const { etiqueta } = item;
  const chip = etiqueta && !etiqueta.giro ? etiqueta : null;
  const contenido = (
    <>
      <span class="bor-fila-tipo">{item.origen}</span>
      <span class="bor-fila-titulo">{item.titulo}</span>
      {/* Lo que está en curso va en su renglón, con el giro (mesa Consulta), y también con la fila abierta. */}
      {etiqueta?.giro && (
        <span class="bor-fila-curso">
          <span class="giro" aria-hidden="true" />
          {etiqueta.texto}
        </span>
      )}
      {(item.linea || chip) && !expandida && (
        <span class={cx("bor-fila-sub", item.lineaCompleta && "completa")}>
          {chip && (
            <>
              <Chip tono={chip.tono}>{chip.texto}</Chip>{" "}
            </>
          )}
          {item.linea}
        </span>
      )}
    </>
  );
  return (
    <li
      class={cx("bor-fila", `n-${item.nivel}`, expandida && "abierta", hecha && "hecha", activa && "bor-fila-activa")}
      data-clave={item.clave}
    >
      {item.nivel === "ok" ? (
        <span class="bor-marca-revisado fija" aria-hidden="true">
          <IconoCheck />
        </span>
      ) : (
        <button
          type="button"
          class="bor-marca-revisado"
          aria-pressed={hecha}
          disabled={soloLectura}
          title={soloLectura ? "Solo se puede cambiar mientras el caso espera la decisión" : hecha ? "Marcar como pendiente" : "Marcar como revisado"}
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
          <Detalle detalle={item.detalle} umbral={umbral} alVerEnTexto={alVerEnTexto} acciones={acciones} />
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
  alVerEvidencia,
  alCorregir,
  alRestaurarPoder,
  apoderadosEnTexto,
  umbralJev,
  avisoEstado,
  alertasLeidas = true,
  abiertoMovil,
  onCerrarMovil,
  pestana,
  alPestana,
  apoderados,
}: PropsPanelRevision) {
  const [verComprobado, setVerComprobado] = useState(false);
  const cuerpo = useRef<HTMLDivElement>(null);
  const aside = useRef<HTMLElement>(null);
  // El último control del panel que tuvo el foco y la fila donde estaba (su data-clave), para devolvérselo si
  // los datos lo quitan sin que nadie toque nada; se olvida en cuanto el foco va a otra parte o se hace clic.
  const ultimoFoco = useRef<{ elemento: HTMLElement; clave: string | null } | null>(null);

  useEffect(() => {
    const alEnfocar = (e: FocusEvent) => {
      const destino = e.target instanceof HTMLElement ? e.target : null;
      ultimoFoco.current =
        destino && aside.current?.contains(destino) ? { elemento: destino, clave: destino.closest<HTMLElement>("li[data-clave]")?.dataset["clave"] ?? null } : null;
    };
    const alPulsar = () => {
      ultimoFoco.current = null;
    };
    document.addEventListener("focusin", alEnfocar);
    document.addEventListener("pointerdown", alPulsar, true);
    return () => {
      document.removeEventListener("focusin", alEnfocar);
      document.removeEventListener("pointerdown", alPulsar, true);
    };
  }, []);

  // Un resultado del sondeo puede mover a un abogado de grupo (otra <ul>: su fila se vuelve a crear) o quitar el
  // botón que tenía el foco (el de «Identificar apoderados», el de «Deshacer el descarte»). El foco caería en <body>,
  // fuera de la trampa del cajón en móvil: vuelve a la fila, ya en su sitio nuevo, o al título del panel.
  useLayoutEffect(() => {
    const previo = ultimoFoco.current;
    if (!previo || previo.elemento.isConnected) return;
    const activo = document.activeElement;
    if (activo && activo !== document.body && activo.isConnected) return;
    const fila = previo.clave === null ? undefined : Array.from(aside.current?.querySelectorAll<HTMLElement>("li[data-clave]") ?? []).find((li) => li.dataset["clave"] === previo.clave);
    const destino = fila?.querySelector<HTMLElement>("button.bor-fila-boton") ?? document.getElementById("bor-panel-titulo");
    destino?.focus({ preventScroll: true });
  });

  const contenerFoco = (e: KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const foco = Array.from(aside.current?.querySelectorAll<HTMLElement>(FOCO) ?? []);
    const primero = foco[0];
    const ultimo = foco[foco.length - 1];
    if (!primero || !ultimo) return;
    if (e.shiftKey && document.activeElement === primero) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
      e.preventDefault();
      primero.focus();
    }
  };

  // Cambia de pestaña y deja el foco en ella: el control que la pidió puede desaparecer al cambiar
  // (el «Ver apoderados» del aviso solo existe en Citas) y el foco no debe caer en <body>, fuera
  // de la trampa de foco del cajón en móvil.
  const irAPestana = (id: Pestana) => {
    alPestana(id);
    document.getElementById(`bor-tab-${id}`)?.focus();
  };

  const alTecladoPestanas = (e: KeyboardEvent) => {
    const actual = PESTANAS.findIndex((p) => p.id === pestana);
    const ultima = PESTANAS.length - 1;
    const destino =
      e.key === "ArrowRight" ? (actual + 1) % PESTANAS.length : e.key === "ArrowLeft" ? (actual + ultima) % PESTANAS.length : e.key === "Home" ? 0 : e.key === "End" ? ultima : null;
    const id = destino === null ? undefined : PESTANAS[destino]?.id;
    if (!id) return;
    e.preventDefault();
    irAPestana(id);
  };

  const citas = items.filter((i) => i.grupo === "citas");
  const deApoderados = items.filter((i) => i.grupo === "apoderados");
  const pendientes = NIVELES.flatMap((nivel) => citas.filter((i) => i.nivel === nivel.id));
  const comprobados = citas.filter((i) => i.nivel === "ok");
  const hechos = pendientes.filter((i) => revisados.has(i.clave)).length;
  const datosApoderados = apoderados.datos;
  const bloqueos = (datosApoderados?.apoderados ?? []).filter((a) => a.bloquea).length;
  const cuentaApoderados = datosApoderados?.identificacion === "lista" ? datosApoderados.apoderados.length : null;
  const { consultar } = apoderados;
  const acciones: AccionesApoderado = {
    editable: datosApoderados?.editable ?? false,
    consulta: datosApoderados?.consulta ?? null,
    enTexto: apoderadosEnTexto,
    alVerEnTexto,
    alVerEvidencia,
    alSubir: apoderados.subir,
    alReintentar: (id) => consultar([id], true),
    alCorregir,
    alRestaurarPoder,
  };

  // Solo se desplaza el cuerpo del panel: mover la ventana cortaría el camino hacia la marca o el del detalle.
  useEffect(() => {
    if (seleccionada === null || window.innerWidth < 1024 || !cuerpo.current) return;
    const fila = cuerpo.current.querySelector<HTMLElement>(".bor-fila-activa");
    if (fila) mostrarDentro(cuerpo.current, fila);
  }, [seleccionada]);

  const fila = (item: ItemRevision, soloLectura = false) => (
    <Fila
      key={item.clave}
      item={item}
      hecha={revisados.has(item.clave)}
      abierta={abierta === item.clave}
      activa={mismaMarca(item.marca, seleccionada)}
      soloLectura={soloLectura}
      umbral={umbralJev}
      alRevisar={alRevisar}
      alAbrir={alAbrir}
      alVerEnTexto={alVerEnTexto}
      acciones={acciones}
    />
  );

  const contenidoCitas = (
    <>
      {pendientes.length === 0 && (
        <div class="bor-todo-bien">
          <IconoCheck />
          <div>
            {alertasLeidas ? (
              <>
                <b>Todo salió bien</b>
                <span>Las citas se encontraron en la relatoría y Jev coincide con el borrador.</span>
              </>
            ) : (
              <>
                <b>Citas sin objeciones</b>
                <span>Las alertas del caso y la lectura de Jev no se han podido comprobar.</span>
              </>
            )}
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
            <ul class="bor-filas">{grupo.map((i) => fila(i))}</ul>
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
          {verComprobado && <ul class="bor-filas">{comprobados.map((i) => fila(i))}</ul>}
        </section>
      )}
    </>
  );

  return (
    <aside
      id="bor-panel"
      ref={aside}
      class={cx("bor-panel", abiertoMovil && "abierto")}
      role={abiertoMovil ? "dialog" : undefined}
      aria-modal={abiertoMovil ? true : undefined}
      aria-labelledby="bor-panel-titulo"
      onKeyDown={abiertoMovil ? contenerFoco : undefined}
    >
      <div key="cabeza" class="bor-panel-cabeza">
        <div class="bor-panel-cabeza-fila">
          <div>
            <h2 id="bor-panel-titulo" tabIndex={-1}>
              Antes de decidir
            </h2>
            <p class="bor-panel-resumen">
              {pestana === "apoderados" ? (
                // El progreso de la consulta («1 de 4 listo · consultando la Rama Judicial») se anuncia al cambiar.
                <span role="status">
                  <ResumenApoderados apoderados={apoderados} />
                </span>
              ) : pendientes.length > 0 ? (
                <>
                  Lleva <b>{`${hechos} de ${pendientes.length}`}</b> revisados.{bloqueos === 0 && " Nada de esto bloquea la decisión."}
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
        {pestana === "apoderados" ? (
          <BarraApoderados key="barra-apoderados" datos={datosApoderados} />
        ) : (
          pendientes.length > 0 && (
            <div key="barra-citas" class="bor-progreso" role="progressbar" aria-label="Puntos revisados" aria-valuemin={0} aria-valuemax={pendientes.length} aria-valuenow={hechos}>
              {pendientes.map((i) => (
                <i key={i.clave} class={cx(`n-${i.nivel}`, revisados.has(i.clave) && "hecho")} />
              ))}
            </div>
          )
        )}
        <div key="pestanas" class="bor-tabs" role="tablist" aria-label="Qué revisar">
          {PESTANAS.map(({ id, nombre }) => {
            const activa = pestana === id;
            const cuenta = id === "citas" ? citas.length : cuentaApoderados;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                id={`bor-tab-${id}`}
                class="bor-tab"
                aria-selected={activa}
                aria-controls={`bor-tp-${id}`}
                tabIndex={activa ? 0 : -1}
                onClick={() => alPestana(id)}
                onKeyDown={alTecladoPestanas}
              >
                {nombre}
                {cuenta !== null && (
                  <>
                    {" "}
                    <span class="n">{cuenta}</span>
                  </>
                )}
                {id === "apoderados" && bloqueos > 0 && (
                  <>
                    <span class="punto" aria-hidden="true" />
                    <span class="solo-lectura">, con apoderados no verificados</span>
                  </>
                )}
              </button>
            );
          })}
        </div>
      </div>
      {bloqueos > 0 && (
        <Aviso
          key="bloqueo"
          tipo="error"
          class="bor-panel-bloqueo"
          acciones={
            pestana === "citas" ? (
              <Boton variante="fantasma" onClick={() => irAPestana("apoderados")}>
                Ver apoderados
              </Boton>
            ) : undefined
          }
        >
          {textoBloqueoPanel(bloqueos)}
        </Aviso>
      )}
      {avisoEstado && (
        <p key="aviso" class="bor-panel-aviso">
          {avisoEstado}
        </p>
      )}
      <div key="cuerpo" class="bor-panel-cuerpo" ref={cuerpo}>
        {PESTANAS.map(({ id }) => (
          <div key={id} role="tabpanel" id={`bor-tp-${id}`} aria-labelledby={`bor-tab-${id}`} hidden={pestana !== id}>
            {pestana === id &&
              (id === "citas" ? contenidoCitas : <TabApoderados apoderados={apoderados} items={deApoderados} revisados={revisados} fila={fila} />)}
          </div>
        ))}
      </div>
    </aside>
  );
}
