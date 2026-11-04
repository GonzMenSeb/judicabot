import { Boton, Dialogo } from "../../ui";
import { etiquetaRol } from "./tipos";
import type { DocResumen } from "./tipos";

export interface PropsDialogoRevisar {
  abierto: boolean;
  documentos: DocResumen[];
  onVolver: () => void;
  onContinuar: () => void;
}

export function DialogoRevisar({ abierto, documentos, onVolver, onContinuar }: PropsDialogoRevisar) {
  return (
    <Dialogo
      abierto={abierto}
      titulo="Hay documentos para revisar"
      onCerrar={onVolver}
      acciones={
        <>
          <Boton onClick={onVolver} data-enfoque>
            Volver a revisar
          </Boton>
          <Boton variante="primario" onClick={onContinuar}>
            Continuar de todos modos
          </Boton>
        </>
      }
    >
      <p class="sub">
        Su encabezado es de otro radicado, pero el texto nombra a las partes de este caso. Si sigue sin confirmarlos, se entregan al modelo con una marca de «para
        revisar».
      </p>
      <ul class="docs-revisar-lista">
        {documentos.map((d) => (
          <li key={d.doc_id}>
            <b>{d.nombre}</b> <small>{etiquetaRol(d.rol)}</small>
          </li>
        ))}
      </ul>
    </Dialogo>
  );
}
