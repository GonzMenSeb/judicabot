import { useRef } from "preact/hooks";
import type { CasoResumen } from "../../api/contrato";

export interface Quitados {
  /** Numera una carga de GET /api/casos que empieza. */
  iniciar: () => number;
  /** Recuerda que el padre quitó el caso de su lista mientras corría la carga actual. */
  quitar: (id: string) => void;
  /** La respuesta de la carga `carga` sin los casos que se quitaron mientras ella estaba en curso. */
  filtrar: (carga: number, lista: CasoResumen[]) => CasoResumen[];
}

/**
 * Una carga que salió antes de eliminar un caso puede responder después y devolverlo a la lista. Las cargas que
 * empiezan después mandan: si el caso volvió (Deshacer), vuelve a aparecer.
 */
export function useQuitados(): Quitados {
  const ref = useRef<Quitados | null>(null);
  if (!ref.current) {
    let cargas = 0;
    const quitados = new Map<string, number>();
    ref.current = {
      iniciar: () => ++cargas,
      quitar: (id) => void quitados.set(id, cargas),
      filtrar: (carga, lista) => lista.filter((c) => (quitados.get(c.id) ?? 0) < carga),
    };
  }
  return ref.current;
}
