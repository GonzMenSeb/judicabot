import { useId, useState } from "preact/hooks";
import type { AjusteCuerpo, ApoderadoVista } from "../../api/contrato";
import { mostrarToast } from "../../estado";
import { Aviso, Boton, Dialogo } from "../../ui";
import { mensajeError } from "../casos/subida";
import type { DocumentoConocido } from "./apoderados";
import "./dialogo.css";
import type { PedidoAjuste } from "./tipos";

/** El mismo patrón de doc_id que valida el servidor (rutas_expediente.PATRON_DOC_ID). */
export const PATRON_DOC_ID = /^[12][a-z]-\d{3,4}$/;
const OTRO = "";

export interface PropsDialogoAjuste {
  tipo: PedidoAjuste["tipo"];
  apoderado: ApoderadoVista;
  /** Los documentos del expediente que el borrador conoce, para elegir dónde está el poder. */
  documentos: DocumentoConocido[];
  alGuardar: (cuerpo: AjusteCuerpo) => Promise<ApoderadoVista>;
  alCerrar: () => void;
}

/** La cédula que se escribe a mano: de 5 a 10 dígitos, con puntos o espacios si se quiere. Devuelve los dígitos o null. */
export function cedulaEscrita(texto: string): string | null {
  const limpio = texto.trim();
  if (!/^[\d.\s]+$/.test(limpio)) return null;
  const digitos = limpio.replace(/\D/g, "");
  return digitos.length >= 5 && digitos.length <= 10 ? digitos : null;
}

/** Cierra la frase sin duplicar el punto de nombres como «S.A.S.». */
const conPunto = (texto: string): string => (/[.!?…]$/.test(texto) ? texto : `${texto}.`);

const TITULO: Record<PedidoAjuste["tipo"], string> = {
  descartar: "¿El poder no es correcto?",
  poder: "Señalar el poder a mano",
  cedula: "Escribir la cédula del abogado",
};

function documentoInicial(ap: ApoderadoVista, documentos: DocumentoConocido[]): string {
  // Lo más probable: el poder va anexo al escrito del abogado, o es el que ya se había hallado.
  const preferido = ap.poder.evidencia?.doc_id ?? ap.poder.mencion?.doc_id;
  return documentos.find((d) => d.doc_id === preferido)?.doc_id ?? documentos[0]?.doc_id ?? OTRO;
}

/**
 * Las correcciones a mano de un apoderado (M5), en un diálogo que viaja en su propio chunk: descartar el poder que se
 * muestra («No es correcto…»), señalar la página del poder (el servidor comprueba que nombre al abogado) o escribir la
 * cédula que falta en el expediente. Lo que el servidor rechaza se explica dentro del diálogo.
 */
export default function DialogoAjuste({ tipo, apoderado: ap, documentos, alGuardar, alCerrar }: PropsDialogoAjuste) {
  const id = useId();
  const [nota, setNota] = useState("");
  const [documento, setDocumento] = useState(() => documentoInicial(ap, documentos));
  const [otro, setOtro] = useState("");
  const [pagina, setPagina] = useState(() => String(ap.poder.evidencia?.pagina ?? ap.poder.mencion?.pagina ?? ""));
  const [cedula, setCedula] = useState("");
  const [intentado, setIntentado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const elegido = documentos.find((d) => d.doc_id === documento) ?? null;
  const docId = documento === OTRO ? otro.trim().toLowerCase() : documento;
  const n = Number(pagina);
  const total = elegido?.total ?? null;
  const faltaDoc = tipo === "poder" && !PATRON_DOC_ID.test(docId);
  const faltaPagina = tipo === "poder" && (!Number.isInteger(n) || n < 1 || (total !== null && n > total));
  const digitos = tipo === "cedula" ? cedulaEscrita(cedula) : null;
  const faltaCedula = tipo === "cedula" && digitos === null;
  const invalido = faltaDoc || faltaPagina || faltaCedula;

  const cerrar = () => {
    if (!enviando) alCerrar();
  };

  async function guardar() {
    setIntentado(true);
    if (invalido) {
      document.getElementById(faltaCedula ? `${id}-cedula` : faltaDoc ? `${id}-${documento === OTRO ? "otro" : "doc"}` : `${id}-pagina`)?.focus();
      return;
    }
    const cuerpo: AjusteCuerpo =
      tipo === "descartar"
        ? { poder_descartado: true, nota: nota.trim() }
        : tipo === "poder"
          ? { poder_manual: { doc_id: docId, pagina: n }, nota: nota.trim() }
          : { cedula: digitos, nota: "" };
    setEnviando(true);
    setError(null);
    try {
      const vista = await alGuardar(cuerpo);
      mostrarToast(
        tipo === "descartar"
          ? `Poder descartado: ${ap.nombre} queda por revisar.`
          : tipo === "poder"
            ? `Poder de ${ap.nombre} señalado a mano: Doc. ${docId}, p. ${n}.`
            : vista.vigencia.fase === "en_cola" || vista.vigencia.fase === "consultando"
              ? `Cédula guardada: se consultará la tarjeta de ${ap.nombre} en la Rama Judicial.`
              : `Cédula de ${ap.nombre} guardada.`,
        { tipo: "ok" },
      );
      alCerrar();
    } catch (e) {
      setEnviando(false);
      setError(mensajeError(e, "No se pudo guardar la corrección. Revise la conexión e intente de nuevo."));
      // Mientras se enviaba, el botón inactivo soltó el foco (<body>, fuera del diálogo): vuelve al campo que se corrige.
      requestAnimationFrame(() => {
        const activo = document.activeElement;
        if (activo && activo !== document.body && activo.isConnected) return;
        document.getElementById(tipo === "cedula" ? `${id}-cedula` : tipo === "poder" ? `${id}-pagina` : `${id}-nota`)?.focus();
      });
    }
  }

  const referencia = ap.poder.evidencia ? `el poder del Doc. ${ap.poder.evidencia.doc_id}, p. ${ap.poder.evidencia.pagina},` : "el poder";
  const errorCampo = (cual: string, texto: string) => (
    <p id={`${id}-${cual}-error`} class="bor-error" role="alert">
      {texto}
    </p>
  );

  return (
    <Dialogo
      abierto
      titulo={TITULO[tipo]}
      onCerrar={cerrar}
      class="bor-dialogo"
      acciones={
        <>
          <Boton onClick={cerrar} disabled={enviando}>
            Cancelar
          </Boton>
          <Boton variante={tipo === "descartar" ? "peligro" : "primario"} cargando={enviando} onClick={() => void guardar()}>
            {tipo === "descartar" ? "Descartar el poder" : tipo === "poder" ? "Señalar el poder" : "Guardar la cédula"}
          </Boton>
        </>
      }
    >
      {tipo === "descartar" && (
        <>
          <p class="sub bor-dialogo-intro">
            Judicabot dejará de tomar {referencia} como evidencia de que {ap.nombre} representa a {conPunto(ap.parte)} Quedará por revisar hasta que
            señale el poder correcto a mano.
          </p>
          <div class="campo">
            <label for={`${id}-nota`}>Por qué no es correcto (opcional)</label>
            <textarea id={`${id}-nota`} rows={3} value={nota} maxLength={2000} onInput={(e) => setNota(e.currentTarget.value)} />
            <small>Queda en el informe de verificación.</small>
          </div>
        </>
      )}
      {tipo === "poder" && (
        <>
          <p class="sub bor-dialogo-intro">
            Indique dónde está el poder de {ap.nombre}. Judicabot comprueba que su nombre aparezca en esa página y toma de ella la cita.
          </p>
          <div class="bor-dlg-campos">
            <div class="campo">
              <label for={`${id}-doc`}>Documento del expediente</label>
              <select id={`${id}-doc`} data-enfoque value={documento} onChange={(e) => setDocumento(e.currentTarget.value)}>
                {documentos.map((d) => (
                  <option key={d.doc_id} value={d.doc_id}>
                    {`Doc. ${d.doc_id} · ${d.documento}`}
                  </option>
                ))}
                <option value={OTRO}>Otro documento…</option>
              </select>
            </div>
            {documento === OTRO && (
              <div class="campo">
                <label for={`${id}-otro`}>Número del documento</label>
                <input
                  id={`${id}-otro`}
                  type="text"
                  value={otro}
                  placeholder="1a-014"
                  autoComplete="off"
                  spellcheck={false}
                  aria-describedby={`${id}-otro-ayuda${intentado && faltaDoc ? ` ${id}-otro-error` : ""}`}
                  aria-invalid={intentado && faltaDoc ? "true" : undefined}
                  onInput={(e) => setOtro(e.currentTarget.value)}
                />
                <small id={`${id}-otro-ayuda`}>Como aparece en la lista de documentos del caso, p. ej. 1a-014.</small>
                {intentado && faltaDoc && errorCampo("otro", "Escriba el número del documento, p. ej. 1a-014.")}
              </div>
            )}
            <div class="campo">
              <label for={`${id}-pagina`}>Página</label>
              <input
                id={`${id}-pagina`}
                type="number"
                inputMode="numeric"
                min={1}
                max={total ?? undefined}
                value={pagina}
                aria-describedby={intentado && faltaPagina ? `${id}-pagina-error` : undefined}
                aria-invalid={intentado && faltaPagina ? "true" : undefined}
                onInput={(e) => setPagina(e.currentTarget.value)}
              />
              {intentado && faltaPagina && errorCampo("pagina", total !== null ? `Indique una página entre 1 y ${total}.` : "Indique el número de la página.")}
            </div>
          </div>
        </>
      )}
      {tipo === "cedula" && (
        <>
          <p class="sub bor-dialogo-intro">
            El expediente no trae la cédula de {ap.nombre}. Escríbala como aparece en el poder o en su tarjeta: solo se usa para el certificado de vigencia de
            la tarjeta profesional.
          </p>
          <div class="campo">
            <label for={`${id}-cedula`}>Número de cédula</label>
            <input
              id={`${id}-cedula`}
              type="text"
              inputMode="numeric"
              autoComplete="off"
              spellcheck={false}
              value={cedula}
              aria-describedby={intentado && faltaCedula ? `${id}-cedula-error` : undefined}
              aria-invalid={intentado && faltaCedula ? "true" : undefined}
              onInput={(e) => setCedula(e.currentTarget.value)}
            />
            {intentado && faltaCedula && errorCampo("cedula", "La cédula debe tener entre 5 y 10 dígitos.")}
          </div>
        </>
      )}
      {error && (
        <Aviso tipo="error" class="bor-dialogo-error">
          {error}
        </Aviso>
      )}
    </Dialogo>
  );
}
