import "./dock.css";
import { Boton, cx } from "../../ui";

export interface PropsDock {
  pendientes: number;
  revisados: number;
  total: number;
  alertas?: "cargando" | "fallo" | "listo";
  enCurso: boolean;
  bloqueo?: string | null;
  hrefDecision: string;
  puedeCorregir: boolean;
  motivoNoCorregir: string | null;
  alCorregir: () => void;
}

type Tono = "alerta" | "ok" | "info";

function Icono({ tono }: { tono: Tono }) {
  return (
    <span class={cx("bor-dock-icono", tono)}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        {tono === "ok" ? <path d="M5 12.5l4.5 4.5L19 7.5" /> : <path d="M12 6v7M12 17.5v.5" />}
      </svg>
    </span>
  );
}

function mensaje({ pendientes, revisados, total, enCurso, bloqueo, alertas = "listo" }: PropsDock): { tono: Tono; titulo: string; linea: string } {
  if (enCurso) return { tono: "info", titulo: "Hay una redacción en curso", linea: "Podrá decidir cuando termine." };
  if (bloqueo) return { tono: "alerta", titulo: "Revise los apoderados no verificados", linea: bloqueo };
  if (total === 0 && alertas === "cargando") return { tono: "info", titulo: "Comprobando el borrador", linea: "Leyendo las alertas del caso." };
  if (total === 0 && alertas === "fallo") {
    return { tono: "alerta", titulo: "No se pudieron leer las alertas", linea: "Las citas no tienen objeciones; las demás comprobaciones no están disponibles." };
  }
  if (total === 0) return { tono: "ok", titulo: "El borrador está listo para su decisión", linea: "Todas las comprobaciones salieron bien." };
  if (pendientes === 0) {
    return { tono: "ok", titulo: total === 1 ? "Revisó el único punto" : `Revisó los ${total} puntos`, linea: "Puede pasar a la decisión." };
  }
  return {
    tono: "alerta",
    titulo: `${pendientes === 1 ? "Queda 1 punto" : `Quedan ${pendientes} puntos`} por revisar`,
    linea: `Lleva ${revisados} de ${total}. No bloquean la decisión.`,
  };
}

export function Dock(props: PropsDock) {
  const { enCurso, bloqueo, hrefDecision, puedeCorregir, motivoNoCorregir, alCorregir } = props;
  const { tono, titulo, linea } = mensaje(props);
  return (
    <div class="bor-dock">
      <div class="bor-dock-fila">
        <div class="bor-dock-estado">
          <Icono tono={tono} />
          <div>
            <b>{titulo}</b>
            <span id="bor-dock-linea">{motivoNoCorregir && !enCurso && !bloqueo ? motivoNoCorregir : linea}</span>
          </div>
        </div>
        <div class="bor-dock-acciones">
          <Boton onClick={alCorregir} disabled={!puedeCorregir}>
            Pedir correcciones
          </Boton>
          <Boton variante="sello" grande href={hrefDecision} disabled={enCurso || Boolean(bloqueo)} aria-describedby={bloqueo ? "bor-dock-linea" : undefined}>
            Pasar a la decisión
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Boton>
        </div>
      </div>
    </div>
  );
}
