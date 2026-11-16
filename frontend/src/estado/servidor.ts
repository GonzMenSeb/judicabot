import { signal } from "@preact/signals";
import { api } from "../api/cliente";
import type { EstadoServidor, Proveedor } from "../api/contrato";

export const DATOS_PROVEEDOR: Record<Proveedor, { nombre: string; corto: string; rutaClave: string }> = {
  anthropic: { nombre: "Anthropic", corto: "Anthropic", rutaClave: "/api/api-key" },
  gemini: { nombre: "Gemini (Google)", corto: "Gemini", rutaClave: "/api/gemini-key" },
};

export const claveDe = (claves: Pick<EstadoServidor, "api_key" | "gemini_key">, proveedor: Proveedor): boolean =>
  proveedor === "gemini" ? claves.gemini_key : claves.api_key;

export const claveActiva = (servidor: EstadoServidor): boolean => claveDe(servidor, servidor.proveedor);

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
