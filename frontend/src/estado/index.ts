import { signal } from "@preact/signals";

export interface Preferencias {
  modelo: string | null;
}

export const casoActual = signal<string | null>(null);
export const jobActual = signal<string | null>(null);
export const preferencias = signal<Preferencias>({ modelo: null });

export { sincronizarDataset } from "./dataset";
export { fechaRelativa, nombreModelo, plural, pluralizar, porcentaje } from "./formato";
export { cargarEstadoServidor, claveActiva, claveDe, DATOS_PROVEEDOR, errorEstadoServidor, estadoServidor } from "./servidor";
export { tituloVista, useTitulo } from "./titulo";
export { cerrarToast, mostrarToast, toasts } from "./toasts";
export type { OpcionesToast, Toast } from "./toasts";
