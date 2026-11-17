import { signal } from "@preact/signals";
import type { TipoAviso } from "../ui/Aviso";

export interface AccionToast {
  texto: string;
  alHacer: () => void;
}

export interface Toast {
  id: number;
  texto: string;
  tipo: TipoAviso;
  accion?: AccionToast;
}

export interface OpcionesToast {
  tipo?: TipoAviso;
  ms?: number;
  accion?: AccionToast;
}

export const MS_TOAST = 3500;

export const toasts = signal<Toast[]>([]);

let siguiente = 1;
const temporizadores = new Map<number, ReturnType<typeof setTimeout>>();
const duraciones = new Map<number, number>();

export function cerrarToast(id: number): void {
  pausarToast(id);
  duraciones.delete(id);
  toasts.value = toasts.value.filter((x) => x.id !== id);
}

/** Deja de contar el tiempo del aviso (foco o puntero dentro de un aviso con acción). */
export function pausarToast(id: number): void {
  clearTimeout(temporizadores.get(id));
  temporizadores.delete(id);
}

/** Vuelve a contar el tiempo del aviso desde cero; no hace nada si el aviso no se cierra solo. */
export function reanudarToast(id: number): void {
  const ms = duraciones.get(id);
  if (!ms) return;
  pausarToast(id);
  temporizadores.set(id, setTimeout(() => cerrarToast(id), ms));
}

export function mostrarToast(texto: string, { tipo = "info", ms = tipo === "error" ? 0 : MS_TOAST, accion }: OpcionesToast = {}): number {
  const id = siguiente++;
  toasts.value = [...toasts.value, accion ? { id, texto, tipo, accion } : { id, texto, tipo }];
  if (ms > 0) {
    duraciones.set(id, ms);
    reanudarToast(id);
  }
  return id;
}
