import type { JSX, Ref } from "preact";
import { useRef } from "preact/hooks";
import type { ApoderadoVista, EstadoApoderado } from "../../api/contrato";
import { Boton, Chip, cx } from "../../ui";
import type { TonoChip } from "../../ui";
import {
  admiteCedula,
  admiteDescartar,
  admiteDeshacerDescarte,
  admitePoderManual,
  ETIQUETA_ESTADO_APODERADO,
  ETIQUETA_PODER,
  etiquetaVigencia,
  type EvidenciaApoderado,
  formatoTarjeta,
  fuenteEvidencia,
  FUENTE_VIGENCIA,
  mascaraCedula,
  momentoConsulta,
  necesitaCertificado,
  noInscritoEnRojo,
  partirResaltado,
  pedidoVisor,
  subtituloApoderado,
  TITULO_PODER,
  tonoPoder,
  tonoVigencia,
  tratamiento,
} from "./apoderados";
import "./apoderados.css";
import { AyudaVigencia } from "./AyudaVigencia";
import "./documento.css";
import { usePosicionPopover } from "./posicion";
import type { PedidoAjuste, PedidoVisor } from "./tipos";

/** Donde se valida el código del certificado de vigencia. */
export const URL_FIRMA_ELECTRONICA = "https://firmaelectronica.ramajudicial.gov.co/FirmaElectronica";
/** El certificado de antecedentes disciplinarios de abogados: un enlace simple, no se le envía ningún dato. */
export const URL_SANCIONES = "https://antecedentesdisciplinarios.ramajudicial.gov.co/";

export interface PropsPopoverApoderado {
  apoderado: ApoderadoVista;
  /** El caso espera la decisión: se puede marcar revisado y subir el certificado. */
  editable: boolean;
  ancla: HTMLElement;
  contenedor: HTMLElement;
  titulo: Ref<HTMLHeadingElement>;
  onCerrar: () => void;
  alRevisar: (revisado: boolean) => void;
  alVerEvidencia: (pedido: PedidoVisor, desde: HTMLElement) => void;
  alSubir: (archivo: File) => Promise<void>;
  /** «Reintentar consulta automática»; sin él (consulta apagada o sin cédula) no se ofrece. */
  alReintentar?: () => Promise<void>;
  /** Abre el diálogo de una corrección a mano (descartar el poder, señalarlo o escribir la cédula). */
  alCorregir: (tipo: PedidoAjuste["tipo"], desde: HTMLElement) => void;
  /** «Deshacer el descarte»: vuelve a tomar el poder hallado. */
  alRestaurarPoder: () => void;
}

const TRAZO: Record<EstadoApoderado, { tono: TonoChip; trazo: string }> = {
  verificado: { tono: "ok", trazo: "M5 12.5l4.5 4.5L19 7.5" },
  revisar: { tono: "alerta", trazo: "M12 6v7M12 17.5v.5" },
  no_verificado: { tono: "mal", trazo: "M7 7l10 10M17 7L7 17" },
};

const VENCIDA = "Lo había marcado como revisado, pero la evidencia cambió: revíselo de nuevo.";
const AVISO_SANCIONES = "Revise el certificado y, si aplica, las sanciones disciplinarias antes de dar por válida su intervención.";
export const AVISO_NO_INSCRITO_ROJO =
  "El Registro Nacional de Abogados certifica que la cédula que consta en el expediente no está inscrita como abogado(a). Si actúa con licencia temporal, esta consulta no la cubre; revise el certificado y las sanciones disciplinarias antes de dar por válida su intervención.";
export const AVISO_NO_INSCRITO_AMBAR =
  "El Registro Nacional de Abogados certifica que esta cédula no está inscrita como abogado(a). La cédula pudo leerse o escribirse mal: verifique el número. Si actúa con licencia temporal, esta consulta no la cubre.";

const mayuscula = (texto: string) => (texto ? texto[0]!.toUpperCase() + texto.slice(1) : texto);

/** Cierra la frase sin duplicar el punto de nombres como «S.A.S.». */
const conPunto = (texto: string) => (/[.!?…]$/.test(texto) ? texto : `${texto}.`);

const claseBloque = (tono: TonoChip) => cx("ev", (tono === "alerta" || tono === "mal") && tono);

function Icono({ trazo, tamano, grosor = 2 }: { trazo: string; tamano: number; grosor?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={grosor} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={trazo} />
    </svg>
  );
}

function EnlaceExterno({ href, clase = "btn", children }: { href: string; clase?: string; children: string }) {
  return (
    <a class={clase} href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <Icono trazo="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" tamano={13} />
      <span class="solo-lectura"> (se abre en una pestaña nueva)</span>
    </a>
  );
}

/** La cita del expediente con el nombre del abogado resaltado; todo va como texto, nunca como HTML. */
function Cita({ texto, nombre }: { texto: string; nombre: string }) {
  if (!texto) return null;
  return <q>{partirResaltado(texto, nombre).map((p, i) => (p.marcado ? <mark key={i}>{p.texto}</mark> : p.texto))}</q>;
}

function Dato({ termino, children }: { termino: string; children: JSX.Element | string }) {
  return (
    <>
      <dt>{termino}</dt>
      <dd>{children}</dd>
    </>
  );
}

type PropsBloqueTarjeta = Pick<PropsPopoverApoderado, "editable" | "alSubir" | "alReintentar" | "alCorregir"> & { ap: ApoderadoVista };

function BloqueTarjeta({ ap, editable, alSubir, alReintentar, alCorregir }: PropsBloqueTarjeta) {
  const { vigencia } = ap;
  const tono = tonoVigencia(ap);
  const tarjeta = formatoTarjeta(ap.tarjeta ?? vigencia.tarjeta_registro);
  const cedula = mascaraCedula(ap.cedula ?? vigencia.cedula);
  const cuando = momentoConsulta(vigencia.consultado_en);
  const noVigente = vigencia.estado === "no_vigente";
  const noInscrito = vigencia.estado === "no_inscrito";
  // El enlace a las sanciones va con lo que deja al abogado en rojo: tarjeta no vigente o cédula no inscrita sin OCR.
  const sanciones = noVigente || noInscritoEnRojo(ap);
  const datos = tarjeta || cedula || cuando || vigencia.origen;
  return (
    <section class={claseBloque(tono)} aria-labelledby="bor-ev-tarjeta">
      <div class="ev-cab">
        <span class="ev-num" aria-hidden="true">
          1
        </span>
        <h4 class="ev-tit" id="bor-ev-tarjeta">
          Tarjeta profesional
        </h4>
        <Chip tono={tono}>{etiquetaVigencia(ap)}</Chip>
      </div>
      {datos ? (
        <dl class="ev-datos">
          {tarjeta && <Dato termino="Tarjeta">{`T.P. ${tarjeta}`}</Dato>}
          {cedula && <Dato termino="Documento">{`C.C. ${cedula}`}</Dato>}
          {cuando && <Dato termino="Consultado">{mayuscula(cuando)}</Dato>}
          {vigencia.origen && <Dato termino="Fuente">{FUENTE_VIGENCIA[vigencia.origen]}</Dato>}
          {vigencia.numero_certificado && <Dato termino="Certificado">{`N.° ${vigencia.numero_certificado}`}</Dato>}
          {vigencia.codigo_verificacion && (
            <Dato termino="Código">
              <code>{vigencia.codigo_verificacion}</code>
            </Dato>
          )}
        </dl>
      ) : (
        <p class="ev-nota">No constan la tarjeta profesional ni la cédula en el expediente.</p>
      )}
      {vigencia.fase === "consultando" && (
        <p class="ev-nota ev-giro" role="status">
          <span class="giro" aria-hidden="true" />
          Consultando la Rama Judicial…
        </p>
      )}
      {vigencia.fase === "en_cola" && <p class="ev-nota">En cola para consultar la Rama Judicial.</p>}
      {noVigente && <p class="ev-nota">{AVISO_SANCIONES}</p>}
      {noInscrito && <p class="ev-nota">{noInscritoEnRojo(ap) ? AVISO_NO_INSCRITO_ROJO : AVISO_NO_INSCRITO_AMBAR}</p>}
      {(vigencia.certificado_url || vigencia.codigo_verificacion || sanciones) && (
        <div class="ev-acc">
          {vigencia.certificado_url && <EnlaceExterno href={vigencia.certificado_url}>Ver certificado (PDF)</EnlaceExterno>}
          {vigencia.codigo_verificacion && (
            <EnlaceExterno href={URL_FIRMA_ELECTRONICA} clase="btn fantasma">
              Validar el código
            </EnlaceExterno>
          )}
          {sanciones && (
            <EnlaceExterno href={URL_SANCIONES} clase="btn fantasma">
              Consultar sanciones (CNDJ)
            </EnlaceExterno>
          )}
        </div>
      )}
      {editable && admiteCedula(ap) && (
        <div class="ev-acc">
          <Boton variante="fantasma" onClick={(e) => alCorregir("cedula", e.currentTarget)}>
            Escribir la cédula
          </Boton>
        </div>
      )}
      {editable && necesitaCertificado(ap) && (
        <AyudaVigencia
          apoderado={ap}
          editable
          compacta
          alSubir={alSubir}
          alReintentar={alReintentar}
          destinoFoco={() => document.getElementById("bor-detalle-titulo")}
        />
      )}
    </section>
  );
}

function LineaCadena({ ap }: { ap: ApoderadoVista }) {
  const { poder } = ap;
  if (ap.tipo_persona === "natural") return <p class="ev-cadena">Persona natural: basta el poder firmado por ella.</p>;
  const cadena = poder.cadena;
  const otorgante = cadena?.otorgante || poder.otorgante;
  const ref = cadena?.evidencia ? ` (Doc. ${cadena.evidencia.doc_id}, p. ${cadena.evidencia.pagina})` : "";
  switch (cadena?.estado) {
    case "confirmada":
      return (
        <p class="ev-cadena">
          Lo otorga <b>{otorgante}</b>
          {cadena.cargo && `, ${cadena.cargo}`}, según el certificado de existencia y representación{ref}.
        </p>
      );
    case "contradicha":
      return (
        <p class="ev-cadena">
          El certificado de existencia y representación{ref} no muestra a <b>{otorgante || "quien firma el poder"}</b> como representante de {conPunto(ap.parte)}
        </p>
      );
    case "sin_certificado":
      return <p class="ev-cadena">No se halló el certificado de existencia y representación de {ap.parte}: no se pudo confirmar quién otorga el poder.</p>;
    case "no_aplica":
      return <p class="ev-cadena">Para esta parte no se exige certificado de existencia: basta el poder.</p>;
    default:
      return otorgante ? (
        <p class="ev-cadena">
          Lo otorga <b>{otorgante}</b>.
        </p>
      ) : null;
  }
}

function sinPoder(ap: ApoderadoVista): string {
  const { poder } = ap;
  if (poder.estado === "descartado") return "El poder se descartó en la revisión.";
  const revisados = poder.documentos_revisados;
  const cuantos = revisados === 1 ? "Se revisó 1 documento y no le otorga" : `Se revisaron ${revisados} documentos y ninguno le otorga`;
  return conPunto(`${cuantos} poder para ${ap.parte}`);
}

/** Las correcciones del poder: «No es correcto…», «Señalar el poder a mano…» y deshacer un descarte. */
function CorregirPoder({ ap, alCorregir, alRestaurarPoder }: { ap: ApoderadoVista } & Pick<PropsPopoverApoderado, "alCorregir" | "alRestaurarPoder">) {
  const descartar = admiteDescartar(ap);
  const manual = admitePoderManual(ap);
  const deshacer = admiteDeshacerDescarte(ap);
  if (!descartar && !manual && !deshacer) return null;
  return (
    <div class="ev-acc">
      {descartar && (
        <Boton variante="fantasma" onClick={(e) => alCorregir("descartar", e.currentTarget)}>
          No es correcto…
        </Boton>
      )}
      {manual && (
        <Boton variante="fantasma" onClick={(e) => alCorregir("poder", e.currentTarget)}>
          Señalar el poder a mano…
        </Boton>
      )}
      {deshacer && (
        <Boton variante="fantasma" onClick={alRestaurarPoder}>
          Deshacer el descarte
        </Boton>
      )}
    </div>
  );
}

type PropsBloquePoder = Pick<PropsPopoverApoderado, "editable" | "alVerEvidencia" | "alCorregir" | "alRestaurarPoder"> & { ap: ApoderadoVista };

function BloquePoder({ ap, editable, alVerEvidencia, alCorregir, alRestaurarPoder }: PropsBloquePoder) {
  const { poder } = ap;
  const tono = tonoPoder(ap);
  const evidencia = poder.evidencia;
  const certificado = poder.cadena?.evidencia ?? null;
  const ver = (cual: EvidenciaApoderado) => (e: JSX.TargetedMouseEvent<HTMLElement>) => {
    const pedido = pedidoVisor(ap, cual);
    if (pedido) alVerEvidencia(pedido, e.currentTarget);
  };
  return (
    <section class={claseBloque(tono)} aria-labelledby="bor-ev-poder">
      <div class="ev-cab">
        <span class="ev-num" aria-hidden="true">
          2
        </span>
        <h4 class="ev-tit" id="bor-ev-poder">
          Facultad para representar
        </h4>
        <Chip tono={tono}>{ETIQUETA_PODER[poder.estado]}</Chip>
      </div>
      {evidencia ? (
        <>
          <Cita texto={evidencia.cita} nombre={ap.nombre} />
          <span class="ev-fuente">{fuenteEvidencia(TITULO_PODER[poder.tipo ?? "poder"], evidencia)}</span>
          {poder.estado === "ajeno" ? (
            <p class="ev-nota">
              El poder hallado es para {poder.parte || "otra parte"}, no para {conPunto(ap.parte)}
            </p>
          ) : (
            <LineaCadena ap={ap} />
          )}
          <div class="ev-acc">
            <Boton onClick={ver("poder")}>Ver poder · p. {evidencia.pagina}</Boton>
            {certificado && (
              <Boton variante="fantasma" onClick={ver("certificado")}>
                Ver certificado de existencia · p. {certificado.pagina}
              </Boton>
            )}
          </div>
        </>
      ) : (
        <>
          <p class="ev-nota">{sinPoder(ap)}</p>
          {poder.mencion && (
            <>
              <Cita texto={poder.mencion.cita} nombre={ap.nombre} />
              <span class="ev-fuente">{fuenteEvidencia("Su escrito", poder.mencion)}</span>
              <div class="ev-acc">
                <Boton onClick={ver("escrito")}>Ver su escrito · p. {poder.mencion.pagina}</Boton>
              </div>
            </>
          )}
        </>
      )}
      {editable && <CorregirPoder ap={ap} alCorregir={alCorregir} alRestaurarPoder={alRestaurarPoder} />}
    </section>
  );
}

export function PopoverApoderado({
  apoderado: ap,
  editable,
  ancla,
  contenedor,
  titulo,
  onCerrar,
  alRevisar,
  alVerEvidencia,
  alSubir,
  alReintentar,
  alCorregir,
  alRestaurarPoder,
}: PropsPopoverApoderado) {
  const caja = useRef<HTMLElement>(null);
  const arriba = usePosicionPopover(caja, ancla, contenedor, ap.id);
  const { tono, trazo } = TRAZO[ap.estado];
  const etiqueta = ap.estado === "verificado" ? (tratamiento(ap) === "Apoderada" ? "Abogada verificada" : "Abogado verificado") : ETIQUETA_ESTADO_APODERADO[ap.estado];
  const motivos = [...(ap.revision_vencida ? [VENCIDA] : []), ...(ap.estado === "verificado" ? [] : ap.motivos)];

  return (
    <section
      id="bor-detalle"
      role="dialog"
      ref={caja}
      class={cx("bor-pop bor-pop-apo", arriba && "arriba")}
      aria-labelledby="bor-detalle-titulo"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        onCerrar();
      }}
    >
      <div class="bor-pop-cabeza">
        <div>
          <Chip tono={tono}>
            <Icono trazo={trazo} tamano={13} grosor={3} />
            {etiqueta}
          </Chip>
          <h3 id="bor-detalle-titulo" ref={titulo} tabIndex={-1}>
            {ap.nombre}
          </h3>
          <p class="pop-sub">{subtituloApoderado(ap)}</p>
        </div>
        <button type="button" class="bor-pop-cerrar" aria-label="Cerrar" onClick={onCerrar}>
          <Icono trazo="M6 6l12 12M18 6L6 18" tamano={18} />
        </button>
      </div>
      <div class="bor-pop-cuerpo">
        {motivos.length > 0 && (
          <ul class={cx("bor-motivos", ap.estado === "no_verificado" ? "rechazada" : "revisar")}>
            {motivos.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}
        <BloqueTarjeta ap={ap} editable={editable} alSubir={alSubir} alReintentar={alReintentar} alCorregir={alCorregir} />
        <BloquePoder ap={ap} editable={editable} alVerEvidencia={alVerEvidencia} alCorregir={alCorregir} alRestaurarPoder={alRestaurarPoder} />
      </div>
      <div class="pop-pie">
        <span>Cotejo automático. Confirme contra el documento original.</span>
        <Boton
          aria-pressed={ap.revisado}
          disabled={!editable}
          title={editable ? undefined : "Solo se puede cambiar mientras el caso espera la decisión"}
          onClick={() => alRevisar(!ap.revisado)}
        >
          {ap.revisado && <Icono trazo="M5 12.5l4.5 4.5L19 7.5" tamano={13} grosor={3} />}
          Marcar revisado
        </Boton>
      </div>
    </section>
  );
}
