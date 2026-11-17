import type { JSX } from "preact";
import type { ApoderadosRespuesta, ApoderadoVista, ConsultaEstado } from "../../api/contrato";
import { Aviso, Boton, Cargando, Chip, cx, Vacio } from "../../ui";
import type { TonoChip } from "../../ui";
import {
  admiteCedula,
  admiteDescartar,
  admiteDeshacerDescarte,
  admitePoderManual,
  avisoPausa,
  claveApoderado,
  consultaAutomatica,
  enCurso,
  ETIQUETA_PODER,
  ETIQUETA_ROL_PARTE,
  etiquetaVigencia,
  lineaPoder,
  lineaVigencia,
  admiteCertificado,
  necesitaCertificado,
  pedidoVisor,
  progresoConsulta,
  puedeReintentar,
  resumenApoderados,
  segmentosEstado,
} from "./apoderados";
import { AyudaVigencia } from "./AyudaVigencia";
import type { ItemRevision, NivelRevision, PedidoAjuste, PedidoVisor, Seleccion } from "./tipos";
import type { EstadoApoderados } from "./useApoderados";

export type PanelApoderados = Pick<
  EstadoApoderados,
  "datos" | "error" | "errorRevision" | "recargar" | "subir" | "consultar" | "ajustar" | "identificar" | "identificando" | "errorIdentificacion"
>;

/**
 * Lo que puede hacer la fila abierta de un abogado: ir a su nombre en el texto, abrir la evidencia, subir el
 * certificado, reintentar la consulta automática o corregir a mano lo que se cotejó.
 */
export interface AccionesApoderado {
  editable: boolean;
  /** La consulta automática del caso; sin ella (apagada) no se ofrece reintentarla. */
  consulta: ConsultaEstado | null;
  /** Los abogados cuyo nombre está marcado en el texto del borrador. */
  enTexto: ReadonlySet<string>;
  alVerEnTexto: (marca: Seleccion, desde: HTMLElement) => void;
  alVerEvidencia: (pedido: PedidoVisor, desde: HTMLElement) => void;
  alSubir: (id: string, archivo: File) => Promise<void>;
  alReintentar: (id: string) => Promise<void>;
  /** Abre el diálogo de una corrección a mano (descartar el poder, señalarlo o escribir la cédula). */
  alCorregir: (pedido: PedidoAjuste, desde: HTMLElement) => void;
  /** «Deshacer el descarte»: vuelve a tomar el poder hallado. */
  alRestaurarPoder: (id: string) => void;
}

export interface PropsTabApoderados {
  apoderados: PanelApoderados;
  items: ItemRevision[];
  revisados: ReadonlySet<string>;
  fila: (item: ItemRevision, soloLectura?: boolean) => JSX.Element;
}

const GRUPOS: { nivel: Exclude<NivelRevision, "info">; nombre: string; pendiente: boolean }[] = [
  { nivel: "mal", nombre: "No verificados", pendiente: true },
  { nivel: "alerta", nombre: "Por revisar", pendiente: true },
  { nivel: "ok", nombre: "Verificados", pendiente: false },
];

export function textoBloqueoPanel(n: number): string {
  return n === 1
    ? "Un apoderado no pudo verificarse. Resuélvalo antes de aprobar el borrador."
    : `${n} apoderados no pudieron verificarse. Resuélvalos antes de aprobar el borrador.`;
}

export function ResumenApoderados({ apoderados: { datos, error } }: { apoderados: PanelApoderados }) {
  if (!datos) return <>{error ? "No se pudo leer el estado de los apoderados." : "Cargando los apoderados…"}</>;
  if (datos.identificacion === "no_disponible") return <>Identificación no disponible para este caso.</>;
  if (datos.identificacion === "fallida") return <>No se pudieron identificar los apoderados.</>;
  const progreso = progresoConsulta(datos);
  if (progreso) return <>{progreso}</>;
  if (datos.apoderados.length === 0) return <>No se identificaron apoderados en el expediente.</>;
  const { total, partes } = resumenApoderados(datos);
  return (
    <>
      <b>{total}</b>
      {partes.map((p) => ` · ${p}`).join("")}
    </>
  );
}

export function BarraApoderados({ datos }: { datos: ApoderadosRespuesta | null }) {
  if (datos?.identificacion !== "lista" || datos.apoderados.length === 0) return null;
  return (
    <div class="bor-progreso" aria-hidden="true">
      {segmentosEstado(datos).map((s, i) => (
        <i key={i} class={s} />
      ))}
    </div>
  );
}

function IconoExterno() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

function IconoIr() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function DetalleApoderado({ apoderado: ap, acciones }: { apoderado: ApoderadoVista; acciones: AccionesApoderado }) {
  const evidencia = ap.poder.evidencia ?? ap.poder.mencion;
  const propia = !ap.poder.evidencia && ap.poder.mencion !== null;
  const poder = lineaPoder(ap);
  const pedido = pedidoVisor(ap, propia ? "escrito" : "poder");
  const enTexto = acciones.enTexto.has(ap.id);
  return (
    <>
      {evidencia?.cita && <q>{evidencia.cita}</q>}
      {ap.revision_vencida && <p class="bor-nota alerta">Lo había marcado como revisado, pero la evidencia cambió: revíselo de nuevo.</p>}
      <div class="bor-comparar">
        <div>
          <span class="que">Tarjeta profesional</span>
          <strong>{etiquetaVigencia(ap)}</strong>
          <small>{lineaVigencia(ap)}</small>
        </div>
        <div>
          <span class="que">Facultad para representar</span>
          <strong>{ETIQUETA_PODER[ap.poder.estado]}</strong>
          {poder && <small>{poder}</small>}
          {propia && evidencia && <small>Su escrito · Doc. {`${evidencia.doc_id}, p. ${evidencia.pagina}`}</small>}
        </div>
      </div>
      {ap.estado !== "verificado" && ap.motivos.length > 0 && (
        <ul class={cx("bor-motivos", ap.estado === "no_verificado" ? "rechazada" : "revisar")}>
          {ap.motivos.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
      {acciones.editable && admiteCertificado(ap) && (
        <AyudaVigencia
          apoderado={ap}
          editable
          alSubir={(archivo) => acciones.alSubir(ap.id, archivo)}
          alReintentar={necesitaCertificado(ap) && puedeReintentar(ap, acciones.consulta) ? () => acciones.alReintentar(ap.id) : undefined}
          // Con el resultado, la fila puede pasar a otro grupo: el foco va a la suya, ya en su sitio nuevo.
          destinoFoco={() => document.querySelector<HTMLElement>(`#bor-panel li[data-clave="${claveApoderado(ap.id)}"] .bor-fila-boton`)}
        />
      )}
      <div class="bor-acciones-fila">
        <Boton
          variante="fantasma"
          disabled={!enTexto}
          title={enTexto ? undefined : "Su nombre no está marcado en el texto del borrador."}
          onClick={(e) => acciones.alVerEnTexto({ tipo: "apoderado", id: ap.id }, e.currentTarget)}
        >
          Ver en el texto <IconoIr />
        </Boton>
        {ap.vigencia.certificado_url && (
          <a class="btn fantasma" href={ap.vigencia.certificado_url} target="_blank" rel="noopener noreferrer">
            Certificado PDF <IconoExterno />
            <span class="solo-lectura"> (se abre en una pestaña nueva)</span>
          </a>
        )}
        {pedido && evidencia && (
          <Boton variante="fantasma" onClick={(e) => acciones.alVerEvidencia(pedido, e.currentTarget)}>
            {propia ? "Su escrito" : "Poder"} · p. {evidencia.pagina}
          </Boton>
        )}
      </div>
      {acciones.editable && (
        <AccionesCorreccion apoderado={ap} alCorregir={acciones.alCorregir} alRestaurarPoder={acciones.alRestaurarPoder} clase="bor-acciones-fila" />
      )}
    </>
  );
}

/**
 * Las correcciones a mano de lo que se cotejó (M5): «No es correcto…» descarta el poder que se muestra, «Señalar el
 * poder a mano…» toma la página que indique quien revisa y «Escribir la cédula» completa la que falta en el expediente.
 */
function AccionesCorreccion({
  apoderado: ap,
  alCorregir,
  alRestaurarPoder,
  clase,
}: {
  apoderado: ApoderadoVista;
  alCorregir: AccionesApoderado["alCorregir"];
  alRestaurarPoder: AccionesApoderado["alRestaurarPoder"];
  clase: string;
}) {
  const descartar = admiteDescartar(ap);
  const manual = admitePoderManual(ap);
  const cedula = admiteCedula(ap);
  const deshacer = admiteDeshacerDescarte(ap);
  if (!descartar && !manual && !cedula && !deshacer) return null;
  const pedir = (tipo: PedidoAjuste["tipo"]) => (e: JSX.TargetedMouseEvent<HTMLElement>) => alCorregir({ tipo, apoderado: ap.id }, e.currentTarget);
  return (
    <div class={clase} role="group" aria-label={`Corregir a mano lo cotejado de ${ap.nombre}`}>
      {descartar && (
        <Boton variante="fantasma" onClick={pedir("descartar")}>
          No es correcto…
        </Boton>
      )}
      {manual && (
        <Boton variante="fantasma" onClick={pedir("poder")}>
          Señalar el poder a mano…
        </Boton>
      )}
      {deshacer && (
        <Boton variante="fantasma" onClick={() => alRestaurarPoder(ap.id)}>
          Deshacer el descarte
        </Boton>
      )}
      {cedula && (
        <Boton variante="fantasma" onClick={pedir("cedula")}>
          Escribir la cédula
        </Boton>
      )}
    </div>
  );
}

const EXTENSION: Record<ConsultaEstado["extension"], { chip: string; tono: TonoChip; texto: string; enlace: string | null }> = {
  conectada: {
    chip: "Extensión conectada",
    tono: "ok",
    texto: "La Rama Judicial solo responde a conexiones desde Colombia, así que cada consulta sale de su navegador, una a la vez.",
    enlace: null,
  },
  desactualizada: {
    chip: "Extensión desactualizada",
    tono: "alerta",
    texto: "La extensión instalada no sabe consultar la vigencia: instale la versión nueva. Mientras tanto, suba el certificado a mano.",
    enlace: "Actualizar la extensión",
  },
  no_conectada: {
    chip: "Extensión no conectada",
    tono: "alerta",
    texto: "La Rama Judicial solo responde a conexiones desde Colombia: abra Judicabot en un navegador con la extensión instalada, o suba el certificado a mano.",
    enlace: "Instalar la extensión",
  },
};

export const ENLACE_EXTENSION = "#/configuracion/extension";

/** El aviso de la consulta automática (mesa Consulta): desde dónde se consulta, cómo está la extensión y si hay pausa. */
export function BannerConsulta({ datos }: { datos: ApoderadosRespuesta }) {
  const { consulta, apoderados } = datos;
  const pendiente = apoderados.some((a) => enCurso(a) || a.vigencia.fase === "necesita_ayuda");
  if (!consultaAutomatica(consulta)) {
    // Apagada: nada se consulta solo; basta una nota discreta para quien deba subir certificados.
    return apoderados.some(necesitaCertificado) ? (
      <p class="bor-nota bor-apo-margen">
        La consulta automática de la vigencia está desactivada en esta instalación: descargue el certificado de cada abogado en la página oficial y súbalo
        aquí.
      </p>
    ) : null;
  }
  const pausa = avisoPausa(consulta);
  if (!pendiente && !consulta.activa && !pausa) return null;
  const extension = consulta.modo === "extension" ? EXTENSION[consulta.extension] : null;
  const titulo = consulta.modo === "extension" ? "Consulta desde su navegador" : consulta.modo === "directa" ? "Consulta desde el servidor" : "Consulta simulada";
  const texto =
    extension?.texto ??
    (consulta.modo === "directa"
      ? "El servidor consulta la Rama Judicial directamente, una cédula a la vez."
      : "Modo de prueba: los certificados son inventados y no se consulta la Rama Judicial.");
  return (
    <div class="apo-consulta" role="note" aria-label="Consulta automática de la vigencia">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3.6 9h16.8M3.6 15h16.8M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
      </svg>
      <div>
        <p class="apo-consulta-cab">
          <b>{titulo}</b>
          {extension ? <Chip tono={extension.tono}>{extension.chip}</Chip> : consulta.modo === "fake" && <Chip tono="info">Modo de prueba</Chip>}
        </p>
        <p>
          {texto}
          {extension?.enlace && (
            <>
              {" "}
              <a href={ENLACE_EXTENSION}>{extension.enlace}</a>
            </>
          )}
        </p>
        {pausa && <p class="apo-consulta-pausa">{pausa}</p>}
      </div>
    </div>
  );
}

function Grupo({ id, nivel, nombre, cuenta, children }: { id: string; nivel: NivelRevision; nombre: string; cuenta: string; children: JSX.Element[] }) {
  return (
    <section class="bor-nivel" aria-labelledby={id}>
      <div class={cx("bor-nivel-cabeza", `n-${nivel}`)}>
        <i />
        <h3 class="nombre" id={id}>
          {nombre}
        </h3>
        <span class="cuenta">{cuenta}</span>
      </div>
      <ul class="bor-filas">{children}</ul>
    </section>
  );
}

/**
 * Para los casos anteriores a la identificación (o si falló): buscar a los abogados en el expediente ahora. Mientras
 * busca, el botón (el de `Boton`, con su giro) queda inactivo con aria-disabled y no con disabled, que le quitaría el
 * foco y lo dejaría en <body>; al terminar, el panel lo lleva a la lista (ver `PanelRevision`).
 */
function Identificar({ apoderados: { datos, identificar, identificando, errorIdentificacion } }: { apoderados: PanelApoderados }) {
  return (
    <div>
      <button
        type="button"
        class={cx("btn", "secundario", identificando && "cargando")}
        aria-disabled={identificando ? "true" : undefined}
        aria-busy={identificando ? "true" : undefined}
        onClick={() => {
          if (!identificando) void identificar();
        }}
      >
        {identificando && <span class="giro" aria-hidden="true" />}
        {datos?.identificacion === "fallida" ? "Intentar de nuevo" : "Identificar apoderados"}
      </button>
      <p class="bor-nota" role="status">
        {identificando ? "Buscando a los abogados en el expediente; puede tardar unos minutos." : ""}
      </p>
      {errorIdentificacion && <Aviso tipo="error">{errorIdentificacion}</Aviso>}
    </div>
  );
}

export function TabApoderados({ apoderados, items, revisados, fila }: PropsTabApoderados) {
  const { datos, error, errorRevision, recargar } = apoderados;
  const avisos = items.filter((i) => i.detalle?.tipo !== "apoderado");
  const abogados = items.filter((i) => i.detalle?.tipo === "apoderado");
  const quedan = (lista: ItemRevision[]) => lista.filter((i) => !revisados.has(i.clave)).length;
  const cuentaPendiente = (lista: ItemRevision[]) => (quedan(lista) > 0 ? `${quedan(lista)} de ${lista.length}` : "✓");
  const grupoAvisos = avisos.length > 0 && (
    <Grupo key="avisos" id="bor-ap-nv-avisos" nivel="alerta" nombre="Avisos de la identificación" cuenta={cuentaPendiente(avisos)}>
      {avisos.map((i) => fila(i))}
    </Grupo>
  );

  if (!datos) {
    return (
      <>
        {error ? (
          <div key="error" class="bor-apo-margen">
            <Aviso tipo="error" titulo="No se pudo leer el estado de los apoderados" acciones={<Boton onClick={recargar}>Reintentar</Boton>}>
              {error}
            </Aviso>
          </div>
        ) : (
          <Cargando key="cargando" texto="Cargando los apoderados…" />
        )}
        {grupoAvisos}
      </>
    );
  }

  const soloLectura = !datos.editable;
  // Mientras se identifica el caso no admite cambios, pero el botón sigue a la vista con su progreso.
  const identificar = datos.editable || apoderados.identificando ? <Identificar apoderados={apoderados} /> : undefined;
  const porNivel = (nivel: (typeof GRUPOS)[number]["nivel"]) => {
    const definicion = GRUPOS.find((g) => g.nivel === nivel);
    const grupo = abogados.filter((i) => i.nivel === nivel);
    if (!definicion || grupo.length === 0) return null;
    return (
      <Grupo id={`bor-ap-nv-${nivel}`} nivel={nivel} nombre={definicion.nombre} cuenta={definicion.pendiente ? cuentaPendiente(grupo) : String(grupo.length)}>
        {grupo.map((i) => fila(i, soloLectura))}
      </Grupo>
    );
  };
  return (
    <>
      {errorRevision && (
        <div class="bor-apo-margen">
          <Aviso tipo="error" titulo="No se pudo guardar la revisión">
            {errorRevision}
          </Aviso>
        </div>
      )}
      {error && (
        <p class="bor-nota bor-apo-margen" role="status">
          No se pudo actualizar el estado de los apoderados; se reintentará en unos segundos.
        </p>
      )}
      {soloLectura && abogados.some((i) => i.nivel !== "ok") && (
        <p class="bor-nota bor-apo-margen">La revisión de los apoderados solo se puede cambiar mientras el caso espera la decisión.</p>
      )}
      {datos.identificacion === "no_disponible" && (
        <Vacio class="bor-apo-margen" titulo="Identificación no disponible para este caso" accion={identificar}>
          El borrador se redactó antes de que Judicabot identificara a los apoderados. Pida identificarlos ahora, o revise a mano la tarjeta profesional y el
          poder de cada abogado.
        </Vacio>
      )}
      {datos.identificacion === "fallida" && (
        <Vacio class="bor-apo-margen" titulo="No se pudieron identificar los apoderados" accion={identificar}>
          Revise a mano la tarjeta profesional y el poder de cada abogado. Si pide rehacer la apertura, Judicabot lo intentará de nuevo.
        </Vacio>
      )}
      {datos.identificacion === "lista" && abogados.length > 0 && <BannerConsulta datos={datos} />}
      {datos.identificacion === "lista" && abogados.length === 0 && datos.sin_apoderado.length === 0 && (
        <Vacio class="bor-apo-margen" titulo="No se identificaron apoderados">
          Según el expediente, ninguna parte actúa por medio de abogado.
        </Vacio>
      )}
      {porNivel("mal")}
      {porNivel("alerta")}
      {grupoAvisos}
      {porNivel("ok")}
      {datos.sin_apoderado.length > 0 && (
        <Grupo id="bor-ap-nv-sin" nivel="info" nombre="Sin apoderado" cuenta={String(datos.sin_apoderado.length)}>
          {datos.sin_apoderado.map((p) => (
            <li key={`${p.rol_parte}|${p.nombre}`} class="bor-fila">
              <span class="bor-marca-revisado bor-apo-hueco" aria-hidden="true" />
              <div class="bor-fila-boton">
                <span class="bor-fila-tipo">{ETIQUETA_ROL_PARTE[p.rol_parte]}</span>
                <span class="bor-fila-titulo">{p.nombre}</span>
                <span class="bor-fila-sub completa">{`${p.nota} No hay abogado que verificar.`.trim()}</span>
              </div>
            </li>
          ))}
        </Grupo>
      )}
    </>
  );
}
