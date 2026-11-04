import { signal } from "@preact/signals";
import type { TipoAviso } from "../ui/Aviso";

export interface Toast {
  id: number;
  texto: string;
  tipo: TipoAviso;
}

export interface OpcionesToast {
  tipo?: TipoAviso;
  ms?: number;
}

export const MS_TOAST = 3500;

export const toasts = signal<Toast[]>([]);

let siguiente = 1;
const temporizadores = new Map<number, ReturnType<typeof setTimeout>>();

export function cerrarToast(id: number): void {
  const t = temporizadores.get(id);
  if (t !== undefined) clearTimeout(t);
  temporizadores.delete(id);
  toasts.value = toasts.value.filter((x) => x.id !== id);
}

export function mostrarToast(texto: string, { tipo = "info", ms = tipo === "error" ? 0 : MS_TOAST }: OpcionesToast = {}): number {
  const id = siguiente++;
  toasts.value = [...toasts.value, { id, texto, tipo }];
  if (ms > 0) temporizadores.set(id, setTimeout(() => cerrarToast(id), ms));
  return id;
}
