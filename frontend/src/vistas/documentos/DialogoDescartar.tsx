import { Boton, Dialogo } from "../../ui";

export interface PropsDialogoDescartar {
  abierto: boolean;
  cmd: "nuevo" | "iniciar";
  mensaje: string;
  confirmando?: boolean;
  onCancelar: () => void;
  onConfirmar: () => void;
}

const TEXTOS = {
  nuevo: { titulo: "¿Volver a procesar los documentos?", confirmar: "Descartar y volver a procesar" },
  iniciar: { titulo: "¿Iniciar la redacción de nuevo?", confirmar: "Descartar e iniciar" },
} as const;

/** Confirmación destructiva: el servidor se negó (409) a descartar el trabajo ya generado sin que se confirme. */
export function DialogoDescartar({ abierto, cmd, mensaje, confirmando, onCancelar, onConfirmar }: PropsDialogoDescartar) {
  const { titulo, confirmar } = TEXTOS[cmd];
  return (
    <Dialogo
      abierto={abierto}
      titulo={titulo}
      onCerrar={onCancelar}
      acciones={
        <>
          <Boton onClick={onCancelar} data-enfoque>
            Cancelar
          </Boton>
          <Boton variante="peligro" onClick={onConfirmar} cargando={confirmando}>
            {confirmar}
          </Boton>
        </>
      }
    >
      <p class="sub">{mensaje}</p>
      <p class="sub">Si este caso avanzó en otra pestaña o ventana, cancele: la página ya muestra su estado actual.</p>
    </Dialogo>
  );
}
