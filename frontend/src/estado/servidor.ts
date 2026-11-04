import { signal } from "@preact/signals";
import { api } from "../api/cliente";
import type { EstadoServidor } from "../api/contrato";

export const estadoServidor = signal<EstadoServidor | null>(null);
export const errorEstadoServidor = signal(false);

let pendiente: Promise<void> | null = null;

export function cargarEstadoServidor(forzar = false): Promise<void> {
  if (pendiente && !forzar) return pendiente;
  const actual = api.get<EstadoServidor>("/api/estado-servidor").then(
    (valor) => {
      estadoServidor.value = valor;
      errorEstadoServidor.value = false;
    },
    () => {
      errorEstadoServidor.value = true;
      if (pendiente === actual) pendiente = null;
    },
  );
  pendiente = actual;
  return actual;
}
