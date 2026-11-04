import { cx } from "./clases";

export type EtapaPaso = "documentos" | "proceso" | "borrador" | "decision" | "fallo";

export const PASOS: readonly { id: EtapaPaso; titulo: string; detalle: string }[] = [
  { id: "documentos", titulo: "Documentos", detalle: "Roles y faltantes" },
  { id: "proceso", titulo: "Proceso", detalle: "Redacción en vivo" },
  { id: "borrador", titulo: "Borrador", detalle: "Apertura y consideraciones" },
  { id: "decision", titulo: "Decisión", detalle: "Su decisión como juez" },
  { id: "fallo", titulo: "Fallo", detalle: "Documentos para firmar" },
];

type EstadoPaso = "hecho" | "actual" | "disponible" | "bloqueado";

export interface PropsPasos {
  caso: string;
  actual: EtapaPaso;
  limite?: EtapaPaso;
  detalles?: Partial<Record<EtapaPaso, string>>;
}

const indiceDe = (etapa: EtapaPaso) => PASOS.findIndex((p) => p.id === etapa);

function estadoDe(i: number, actual: number, limite: number): EstadoPaso {
  if (i === actual) return "actual";
  if (i < actual || i < limite) return "hecho";
  return i === limite ? "disponible" : "bloqueado";
}

const TEXTO_ESTADO: Record<EstadoPaso, string> = {
  hecho: " (hecho)",
  actual: " (paso actual)",
  disponible: "",
  bloqueado: " (aún no disponible)",
};

export function Pasos({ caso, actual, limite, detalles }: PropsPasos) {
  const ia = indiceDe(actual);
  const il = Math.max(ia, limite ? indiceDe(limite) : ia);
  return (
    <nav aria-label="Pasos del caso">
      <ol class="pasos">
        {PASOS.map((paso, i) => {
          const estado = estadoDe(i, ia, il);
          const contenido = (
            <>
              <span class="marca-paso" aria-hidden="true">
                {estado === "hecho" ? <Visto /> : i + 1}
              </span>
              <b>
                {paso.titulo}
                <span class="solo-lectura">{TEXTO_ESTADO[estado]}</span>
              </b>
              <small>{detalles?.[paso.id] ?? paso.detalle}</small>
            </>
          );
          return (
            <li key={paso.id} class={cx("paso", estado, paso.id === "decision" && "decide")}>
              {estado === "bloqueado" ? (
                <span class="paso-enlace">{contenido}</span>
              ) : (
                <a
                  class="paso-enlace"
                  href={`#/segunda/${encodeURIComponent(caso)}/${paso.id}`}
                  aria-current={estado === "actual" ? "step" : undefined}
                >
                  {contenido}
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function Visto() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}
