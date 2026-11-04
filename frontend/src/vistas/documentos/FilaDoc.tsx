import { Boton, Chip, cx } from "../../ui";
import { plural, pluralizar, porcentaje } from "../../estado";
import { ROLES, etiquetaRol } from "./tipos";
import type { DocResumen, RolDoc } from "./tipos";

const esRol = (valor: string | null): valor is RolDoc => ROLES.some((r) => r.id === valor);

export interface PropsFila {
  doc: DocResumen;
  rol: RolDoc;
  tocado: boolean;
  editable: boolean;
  abierto: boolean;
  onRol: (doc: DocResumen, rol: RolDoc) => void;
  onConservar: (doc: DocResumen, marcado: boolean) => void;
  onAlternar: (doc: DocResumen) => void;
}

function IconoPdf() {
  return (
    <svg class="docs-icono" viewBox="0 0 24 30" fill="none" aria-hidden="true">
      <path d="M3 1h12l7 7v21H3z" fill="#fff" stroke="#8da0a9" stroke-width="1.5" stroke-linejoin="round" />
      <path d="M15 1v7h7" stroke="#8da0a9" stroke-width="1.5" stroke-linejoin="round" />
      <rect x="6" y="17" width="12" height="5" rx="1" fill="#a8281f" />
    </svg>
  );
}

function Flecha() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function Confianza({ doc, rol, tocado, editable, onAceptar }: { doc: DocResumen; rol: RolDoc; tocado: boolean; editable: boolean; onAceptar: () => void }) {
  const usuario = tocado || doc.rol_origen === "usuario";
  const propuesto = doc.jev_rol;
  if (propuesto === null || doc.jev_confianza === null) {
    return usuario ? (
      <span class="docs-jev">Asignado por usted</span>
    ) : (
      <span class="docs-jev reglas" title="El rol salió de las reglas del código; Jev no dio opinión.">
        Reglas del código
      </span>
    );
  }
  const pct = `${porcentaje(doc.jev_confianza)} de confianza`;
  const bajo = doc.jev_umbral !== null && doc.jev_confianza < doc.jev_umbral;
  const titulo = bajo ? "Por debajo del umbral configurado: Jev no actúa." : undefined;
  const nota = usuario ? <small class="docs-origen">Asignado por usted</small> : null;
  if (propuesto === rol) {
    return (
      <span class={cx("docs-jev", bajo ? "bajo" : "alto")} title={titulo}>
        <span class="docs-jev-q">Jev</span> <span class="docs-pct">{pct}</span>
        {nota}
      </span>
    );
  }
  return (
    <span class="docs-jev discrepa" title={titulo}>
      <span class="docs-jev-q">Jev</span> propone {etiquetaRol(propuesto)}, <span class="docs-pct">{pct}</span>
      {editable && esRol(propuesto) && (
        <Boton variante="fantasma" onClick={onAceptar} aria-label={`Aceptar ${etiquetaRol(propuesto)} como rol de ${doc.nombre}`}>
          Aceptar
        </Boton>
      )}
      {nota}
    </span>
  );
}

export function FilaDoc({ doc, rol, tocado, editable, abierto, onRol, onConservar, onAlternar }: PropsFila) {
  const idPanel = `ev-${doc.doc_id}`;
  const sinTexto = doc.paginas_sin_texto;
  return (
    <li class={cx("docs-doc", abierto && "abierto")}>
      <div class="docs-fila">
        <IconoPdf />
        <div class="docs-nombre">
          <b>{doc.nombre}</b>
          <small>
            {plural(doc.paginas, "página")}
            {sinTexto > 0 && (
              <>
                , <span class="docs-sin-texto">{sinTexto} sin texto</span>
              </>
            )}
          </small>
          {(doc.ajeno || doc.ruido || doc.revisar) && (
            <span class="docs-etiquetas">
              {doc.ajeno && (
                <Chip tono="mal" title="Sus CUIs no corresponden a este caso; no se usa.">
                  Ajeno
                </Chip>
              )}
              {doc.revisar && (
                <Chip tono="alerta" title="Su encabezado es de otro radicado, pero el texto nombra a las partes de este caso. Se usa, con una marca para el modelo.">
                  Para revisar
                </Chip>
              )}
              {doc.ruido && (
                <Chip title="Certificado de existencia o duplicado exacto; no se usa.">Ruido</Chip>
              )}
            </span>
          )}
          {doc.revisar && (
            <small class="docs-motivo">
              {tocado
                ? "Confirmado al guardar: se entrega al modelo sin marca."
                : "Su encabezado es de otro radicado, pero el texto nombra a las partes de este caso: se entrega al modelo con una marca."}
            </small>
          )}
        </div>
        <div class="docs-rol-col">
          <select
            class={cx("docs-rol", tocado && "cambiado")}
            value={rol}
            disabled={!editable}
            aria-label={`Rol de ${doc.nombre}`}
            onChange={(e) => onRol(doc, e.currentTarget.value as RolDoc)}
          >
            {ROLES.map((r) => (
              <option key={r.id} value={r.id}>
                {r.etiqueta}
              </option>
            ))}
          </select>
          {(doc.ajeno || doc.revisar) && editable && (
            <label class="docs-conservar">
              <input type="checkbox" checked={tocado} onChange={(e) => onConservar(doc, e.currentTarget.checked)} />{" "}
              {doc.revisar ? "Es de este caso: confirmar" : "No es ajeno: conservar"}
            </label>
          )}
        </div>
        <Confianza doc={doc} rol={rol} tocado={tocado} editable={editable} onAceptar={() => onRol(doc, doc.jev_rol as RolDoc)} />
        <button type="button" class="docs-expandir" aria-expanded={abierto} aria-controls={idPanel} onClick={() => onAlternar(doc)}>
          <span>
            Evidencia <span class="solo-lectura">de {doc.nombre}</span>
          </span>
          <Flecha />
        </button>
      </div>
      {abierto && (
        <div class="docs-detalle" id={idPanel}>
          <q>{doc.evidencia || "Sin evidencia registrada."}</q>
          {doc.ruta && doc.ruta !== doc.nombre && <p class="docs-ruta">Ruta en el caso: {doc.ruta}</p>}
          {sinTexto > 0 && (
            <p class="docs-alerta">
              {sinTexto} de {doc.paginas} {pluralizar(doc.paginas, "página")} {sinTexto === 1 ? "es imagen y no tiene" : "son imagen y no tienen"} texto. Su contenido no
              llegará al modelo.
            </p>
          )}
        </div>
      )}
    </li>
  );
}
