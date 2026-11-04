import { useLayoutEffect, useRef, useState } from "preact/hooks";
import type { CampoFormato, Despacho, FormatoRespuesta } from "../../api/contrato";
import { PreviaDocumento, ProveedorPrevia } from "./previas";
import { nombreCorto } from "./modelo";
import type { Plantilla } from "./modelo";

const MARGEN_INFERIOR = 90;

interface PropsPrevia {
  documentos: FormatoRespuesta["documentos"];
  campos: readonly CampoFormato[];
  documento: string;
  valores: Despacho;
  plantilla: Plantilla;
  foco: string | null;
  onDocumento: (id: string) => void;
}

export function Previa({ documentos, campos, documento, valores, plantilla, foco, onDocumento }: PropsPrevia) {
  const marco = useRef<HTMLDivElement>(null);
  const [ausente, setAusente] = useState(false);
  const actual = documentos.find((d) => d.id === documento);
  const campoFoco = foco ? campos.find((c) => c.clave === foco) : undefined;

  useLayoutEffect(() => {
    const caja = marco.current;
    if (!caja || !foco) {
      setAusente(false);
      return;
    }
    const marcados = Array.from(caja.querySelectorAll<HTMLElement>("[data-c]")).filter((el) => el.dataset.c === foco);
    setAusente(marcados.length === 0);
    const primero = marcados[0];
    if (!primero) return;
    const cuadro = caja.getBoundingClientRect();
    const r = primero.getBoundingClientRect();
    const abajo = Math.min(cuadro.bottom, window.innerHeight - MARGEN_INFERIOR);
    if (r.top < cuadro.top || r.bottom > abajo) caja.scrollTop += r.top - cuadro.top - (abajo - cuadro.top) / 2;
  }, [foco, documento, plantilla]);

  return (
    <aside class="fmt-previa" aria-label="Vista previa">
      <div class="fmt-cambiar" role="group" aria-label="Documento de la vista previa">
        {documentos.map((d) => (
          <button type="button" key={d.id} aria-pressed={d.id === documento} title={d.nombre} onClick={() => onDocumento(d.id)}>
            {nombreCorto(d.id, documentos)}
          </button>
        ))}
      </div>
      {ausente && campoFoco && (
        <p class="fmt-nota" role="status">
          «{campoFoco.etiqueta}» no aparece en esta vista previa con la plantilla {plantilla}.
        </p>
      )}
      <div class="fmt-marco" ref={marco} tabIndex={0} role="region" aria-label={`Vista previa: ${actual?.nombre ?? documento}`}>
        <ProveedorPrevia value={{ valores, plantilla, foco, campos }}>
          <PreviaDocumento id={documento} />
        </ProveedorPrevia>
      </div>
      <p class="fmt-aclaracion">Vista esquemática: las líneas grises y los datos del caso son ilustrativos. En Word se usa Bookman Old Style y la paginación puede variar.</p>
    </aside>
  );
}
