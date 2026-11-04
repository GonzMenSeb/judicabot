import { Boton } from "../../ui";
import type { EstadoApi } from "./tipos";

export interface PropsBarra {
  caso: string;
  estado: EstadoApi;
  enCurso: boolean;
  resumenCambios: string | null;
  modelo: string | null;
  guardando: boolean;
  iniciando: boolean;
  onGuardar: () => void;
  onIniciar: () => void;
}

const destino = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

export function Barra({ caso, estado, enCurso, resumenCambios, modelo, guardando, iniciando, onGuardar, onIniciar }: PropsBarra) {
  let texto: string;
  let accion;
  if (enCurso) {
    texto = "Hay una ejecución en curso para este caso.";
    accion = (
      <Boton variante="primario" grande href={destino(caso, "proceso")}>
        Ver el proceso
      </Boton>
    );
  } else if (estado === "revision" || estado === "incompleto") {
    texto = `Redactar apertura y consideraciones${modelo ? ` con ${modelo}` : ""} tarda unos minutos y se detiene antes de la decisión.`;
    accion = (
      <>
        {resumenCambios && (
          <Boton onClick={onGuardar} cargando={guardando} disabled={iniciando}>
            Guardar cambios
          </Boton>
        )}
        <Boton
          variante="primario"
          grande
          onClick={onIniciar}
          cargando={iniciando}
          disabled={estado === "incompleto" || guardando}
          title={estado === "incompleto" ? "Faltan piezas obligatorias" : undefined}
        >
          Iniciar redacción
        </Boton>
      </>
    );
  } else if (estado === "esperando_decision") {
    texto = "La redacción terminó. Revise el borrador y tome su decisión.";
    accion = (
      <Boton variante="primario" grande href={destino(caso, "borrador")}>
        Ver el borrador
      </Boton>
    );
  } else if (estado === "terminado") {
    texto = "El fallo está listo.";
    accion = (
      <Boton variante="primario" grande href={destino(caso, "fallo")}>
        Ver el fallo
      </Boton>
    );
  } else {
    texto = "La redacción quedó a medias.";
    accion = (
      <Boton variante="primario" grande href={destino(caso, "proceso")}>
        Ver el proceso
      </Boton>
    );
  }
  return (
    <div class="docs-accion">
      <div>
        <span class="docs-relleno">
          {resumenCambios && !enCurso && (estado === "revision" || estado === "incompleto") && <b>{resumenCambios} </b>}
          {texto}
        </span>
        {accion}
      </div>
    </div>
  );
}
